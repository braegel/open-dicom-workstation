"""Integration tests against a real Orthanc PACS.

Skipped unless ODW_ORTHANC_HOST is set. Configuration via environment:

- ODW_ORTHANC_HOST        Orthanc host (required to enable these tests)
- ODW_ORTHANC_DICOM_PORT  Orthanc DICOM port (default 4242)
- ODW_ORTHANC_HTTP_PORT   Orthanc REST API port (default 8042)
- ODW_ORTHANC_AET         Orthanc AE title (default ORTHANC)
- ODW_ORTHANC_MOVE_AET    Our AE title as registered in Orthanc's DicomModalities;
                          enables the C-MOVE test
- ODW_ORTHANC_MOVE_PORT   Fixed local SCP port matching that registration (default 11112)
"""

import io
import os
import urllib.request
from uuid import uuid4

import pytest
from pydicom import dcmwrite
from pydicom.dataset import FileDataset
from tests.support.factory import make_ct_dataset, make_series

from odw.core.models import PacsNode
from odw.core.net.query import QueryScu
from odw.core.net.retrieve import RetrieveScu
from odw.core.net.scp import StorageScp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "ODW_ORTHANC_HOST" not in os.environ,
        reason="requires a running Orthanc test PACS (set ODW_ORTHANC_HOST)",
    ),
]

LOCAL_AET = "ODW"


def orthanc_host() -> str:
    return os.environ["ODW_ORTHANC_HOST"]


def orthanc_node() -> PacsNode:
    return PacsNode(
        name="Orthanc (test)",
        ae_title=os.environ.get("ODW_ORTHANC_AET", "ORTHANC"),
        host=orthanc_host(),
        port=int(os.environ.get("ODW_ORTHANC_DICOM_PORT", "4242")),
    )


def unique_patient_name() -> str:
    return f"ODWTEST^{uuid4().hex[:8].upper()}"


def upload_instance(ds: FileDataset) -> None:
    """POST *ds* as a DICOM file to Orthanc's REST API."""
    buffer = io.BytesIO()
    dcmwrite(buffer, ds, enforce_file_format=True)
    http_port = int(os.environ.get("ODW_ORTHANC_HTTP_PORT", "8042"))
    request = urllib.request.Request(
        f"http://{orthanc_host()}:{http_port}/instances",
        data=buffer.getvalue(),
        headers={"Content-Type": "application/dicom"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 200


def upload_series(n: int, patient_name: str) -> str:
    """Upload an *n*-instance series with *patient_name*; return its StudyInstanceUID."""
    series = make_series(n, patient_name=patient_name)
    for ds in series:
        upload_instance(ds)
    return str(series[0].StudyInstanceUID)


def test_find_uploaded_study():
    patient_name = unique_patient_name()
    ds = make_ct_dataset(patient_name=patient_name)
    upload_instance(ds)

    results = QueryScu(LOCAL_AET, orthanc_node()).find_studies(patient_name=patient_name)

    assert len(results) == 1
    assert results[0].study_uid == str(ds.StudyInstanceUID)


def test_cget_study(store):
    study_uid = upload_series(2, unique_patient_name())

    result = RetrieveScu(LOCAL_AET, orthanc_node()).get_study(study_uid, store)

    assert result.completed == 2
    assert result.failed == 0
    series = store.series_for_study(study_uid)
    assert sum(s.num_instances for s in series) == 2


@pytest.mark.skipif(
    "ODW_ORTHANC_MOVE_AET" not in os.environ,
    reason="C-MOVE needs our AET registered in Orthanc's DicomModalities "
    "(set ODW_ORTHANC_MOVE_AET and ODW_ORTHANC_MOVE_PORT)",
)
def test_cmove_study(store):
    move_aet = os.environ["ODW_ORTHANC_MOVE_AET"]
    move_port = int(os.environ.get("ODW_ORTHANC_MOVE_PORT", "11112"))
    study_uid = upload_series(2, unique_patient_name())

    scp = StorageScp(move_aet, move_port, store)
    scp.start()
    try:
        result = RetrieveScu(LOCAL_AET, orthanc_node()).move_study(study_uid, dest_aet=move_aet)
    finally:
        scp.stop()

    assert result.completed == 2
    assert result.failed == 0
    series = store.series_for_study(study_uid)
    assert sum(s.num_instances for s in series) == 2
