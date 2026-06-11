"""Tests for the Storage SCP receiving instances into the local store."""

import threading

import pytest
from pydicom import dcmread
from pydicom.uid import CTImageStorage
from pynetdicom import AE
from tests.conftest import free_port
from tests.support.factory import make_ct_dataset

from odw.core.models import InstanceRecord
from odw.core.net.scp import StorageScp


@pytest.fixture
def scp(store):
    scp = StorageScp("ODW_SCP", 0, store)
    scp.start()
    yield scp
    scp.stop()


def _send_c_store(port: int, ds) -> int:
    ae = AE(ae_title="ODW_TEST")
    ae.add_requested_context(CTImageStorage)
    assoc = ae.associate("127.0.0.1", port, ae_title="ODW_SCP")
    assert assoc.is_established
    try:
        status = assoc.send_c_store(ds)
    finally:
        assoc.release()
    return status.Status


def test_scp_starts_on_ephemeral_port(store):
    scp = StorageScp("ODW_SCP", 0, store)
    scp.start()
    try:
        assert scp.port > 0
    finally:
        scp.stop()


def test_cstore_ingests_into_store(scp, store):
    ds = make_ct_dataset()
    status = _send_c_store(scp.port, ds)
    assert status == 0x0000

    records = store.instances_for_series(str(ds.SeriesInstanceUID))
    assert len(records) == 1
    assert records[0].sop_uid == str(ds.SOPInstanceUID)

    stored = dcmread(records[0].path)
    # File meta survived the C-STORE round-trip with the negotiated transfer syntax.
    assert stored.file_meta.TransferSyntaxUID.is_transfer_syntax
    assert stored.file_meta.MediaStorageSOPInstanceUID == str(ds.SOPInstanceUID)
    assert str(stored.PatientName) == "DOE^JANE"


def test_on_instance_callback_invoked_with_record(store):
    received: list[InstanceRecord] = []
    done = threading.Event()

    def on_instance(record: InstanceRecord) -> None:
        received.append(record)
        done.set()

    scp = StorageScp("ODW_SCP", 0, store, on_instance=on_instance)
    scp.start()
    try:
        ds = make_ct_dataset()
        assert _send_c_store(scp.port, ds) == 0x0000
        assert done.wait(timeout=5)
    finally:
        scp.stop()

    assert len(received) == 1
    assert isinstance(received[0], InstanceRecord)
    assert received[0].sop_uid == str(ds.SOPInstanceUID)


def test_stop_releases_port(store):
    port = free_port()
    first = StorageScp("ODW_SCP", port, store)
    first.start()
    first.stop()

    second = StorageScp("ODW_SCP", port, store)
    second.start()
    try:
        assert second.port == port
        assert _send_c_store(second.port, make_ct_dataset()) == 0x0000
    finally:
        second.stop()
