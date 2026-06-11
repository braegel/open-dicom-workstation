"""Synchronous C-FIND SCU for study/series queries. No Qt; blocking calls."""

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pynetdicom import AE
from pynetdicom.sop_class import (  # type: ignore[attr-defined]
    StudyRootQueryRetrieveInformationModelFind,
)

from odw.core.models import PacsNode, SeriesQueryResult, StudyQueryResult
from odw.core.net import PacsConnectionError

_PENDING = (0xFF00, 0xFF01)


def _text(ds: Dataset, keyword: str) -> str:
    value = getattr(ds, keyword, None)
    if value is None:
        return ""
    if isinstance(value, MultiValue):
        return ", ".join(str(v) for v in value)
    return str(value)


def _number(ds: Dataset, keyword: str) -> int | None:
    value = getattr(ds, keyword, None)
    if value is None or value == "":
        return None
    return int(value)


class QueryScu:
    """Blocking Study Root C-FIND SCU. Threading is the caller's concern."""

    def __init__(self, local_aet: str, node: PacsNode) -> None:
        self._local_aet = local_aet
        self._node = node

    def _query(self, identifier: Dataset) -> list[Dataset]:
        ae = AE(ae_title=self._local_aet)
        ae.acse_timeout = 5
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc = ae.associate(self._node.host, self._node.port, ae_title=self._node.ae_title)
        if not assoc.is_established:
            raise PacsConnectionError(
                f"Could not associate with {self._node.ae_title} at "
                f"{self._node.host}:{self._node.port}"
            )
        matches: list[Dataset] = []
        try:
            for status, rsp in assoc.send_c_find(
                identifier, StudyRootQueryRetrieveInformationModelFind
            ):
                if status and status.Status in _PENDING and rsp is not None:
                    matches.append(rsp)
        finally:
            assoc.release()
        return matches

    def find_studies(
        self,
        *,
        patient_name: str = "",
        study_date: str = "",
        accession_number: str = "",
    ) -> list[StudyQueryResult]:
        identifier = Dataset()
        identifier.QueryRetrieveLevel = "STUDY"
        # Requested return keys (empty values).
        identifier.StudyInstanceUID = ""
        identifier.PatientName = ""
        identifier.PatientID = ""
        identifier.StudyDate = ""
        identifier.StudyDescription = ""
        identifier.ModalitiesInStudy = ""
        identifier.AccessionNumber = ""
        identifier.NumberOfStudyRelatedSeries = ""
        identifier.NumberOfStudyRelatedInstances = ""
        # Filters (only non-empty values).
        if patient_name:
            identifier.PatientName = patient_name
        if study_date:
            identifier.StudyDate = study_date
        if accession_number:
            identifier.AccessionNumber = accession_number

        return [
            StudyQueryResult(
                study_uid=_text(ds, "StudyInstanceUID"),
                patient_name=_text(ds, "PatientName"),
                patient_id=_text(ds, "PatientID"),
                study_date=_text(ds, "StudyDate"),
                description=_text(ds, "StudyDescription"),
                modalities=_text(ds, "ModalitiesInStudy"),
                accession_number=_text(ds, "AccessionNumber"),
                num_series=_number(ds, "NumberOfStudyRelatedSeries"),
                num_instances=_number(ds, "NumberOfStudyRelatedInstances"),
            )
            for ds in self._query(identifier)
        ]

    def find_series(self, study_uid: str) -> list[SeriesQueryResult]:
        identifier = Dataset()
        identifier.QueryRetrieveLevel = "SERIES"
        identifier.StudyInstanceUID = study_uid
        # Requested return keys (empty values).
        identifier.SeriesInstanceUID = ""
        identifier.Modality = ""
        identifier.SeriesNumber = ""
        identifier.SeriesDescription = ""
        identifier.NumberOfSeriesRelatedInstances = ""

        return [
            SeriesQueryResult(
                series_uid=_text(ds, "SeriesInstanceUID"),
                study_uid=_text(ds, "StudyInstanceUID") or study_uid,
                modality=_text(ds, "Modality"),
                series_number=_number(ds, "SeriesNumber"),
                description=_text(ds, "SeriesDescription"),
                num_instances=_number(ds, "NumberOfSeriesRelatedInstances"),
            )
            for ds in self._query(identifier)
        ]
