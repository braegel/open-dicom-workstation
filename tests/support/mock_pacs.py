"""In-process pynetdicom AE acting as a Query/Retrieve SCP for tests."""

from fnmatch import fnmatchcase

from pydicom.dataset import Dataset
from pydicom.uid import CTImageStorage
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
)


def _name_matches(pattern: str, value: str) -> bool:
    """DICOM single-value wildcard matching; empty pattern matches everything."""
    if not pattern:
        return True
    return fnmatchcase(value, pattern)


class MockPacs:
    """In-process pynetdicom AE acting as a Query/Retrieve SCP for tests."""

    aet = "MOCKPACS"

    def __init__(self) -> None:
        self._instances: list[Dataset] = []
        self._server = None
        self._port: int | None = None
        # Mapping of remote AE title -> (host, port); used by a later
        # iteration to resolve C-MOVE destinations.
        self.known_destinations: dict[str, tuple[str, int]] = {}

    def add_instances(self, datasets: list[Dataset]) -> None:
        self._instances.extend(datasets)

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("MockPacs is not running")
        return self._port

    def start(self) -> None:
        ae = AE(ae_title=self.aet)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
        # For C-GET the SCP sends instances on the same association, so the
        # storage SOP class must be supported with both roles accepted.
        ae.add_supported_context(CTImageStorage, scu_role=True, scp_role=True)
        # Requested context for the outgoing store sub-association used by C-MOVE.
        ae.add_requested_context(CTImageStorage)
        self._server = ae.start_server(
            ("127.0.0.1", 0),
            block=False,
            evt_handlers=[
                (evt.EVT_C_FIND, self._handle_find),
                (evt.EVT_C_GET, self._handle_get),
                (evt.EVT_C_MOVE, self._handle_move),
            ],
        )
        self._port = self._server.socket.getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            self._port = None

    def __enter__(self) -> "MockPacs":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # -- C-GET handling ----------------------------------------------------

    def _matches_for_study(self, identifier: Dataset) -> list[Dataset]:
        study_uid = str(getattr(identifier, "StudyInstanceUID", "") or "")
        return [ds for ds in self._instances if str(ds.StudyInstanceUID) == study_uid]

    def _handle_get(self, event):
        matches = self._matches_for_study(event.identifier)
        yield len(matches)
        for ds in matches:
            yield 0xFF00, ds

    # -- C-MOVE handling ---------------------------------------------------

    def _handle_move(self, event):
        dest_aet = str(event.move_destination).strip()
        destination = self.known_destinations.get(dest_aet)
        if destination is None:
            # pynetdicom turns this into 0xA801 (move destination unknown).
            yield None, None
            return
        addr, port = destination
        yield addr, port
        matches = self._matches_for_study(event.identifier)
        yield len(matches)
        for ds in matches:
            yield 0xFF00, ds

    # -- C-FIND handling ---------------------------------------------------

    def _handle_find(self, event):
        identifier = event.identifier
        level = getattr(identifier, "QueryRetrieveLevel", "")
        if level == "STUDY":
            yield from self._find_studies(identifier)
        elif level == "SERIES":
            yield from self._find_series(identifier)

    def _find_studies(self, query: Dataset):
        name_filter = str(getattr(query, "PatientName", "") or "")
        date_filter = str(getattr(query, "StudyDate", "") or "")
        uid_filter = str(getattr(query, "StudyInstanceUID", "") or "")

        studies: dict[str, list[Dataset]] = {}
        for ds in self._instances:
            studies.setdefault(ds.StudyInstanceUID, []).append(ds)

        for study_uid, instances in studies.items():
            first = instances[0]
            if not _name_matches(name_filter, str(first.PatientName)):
                continue
            if date_filter and str(first.StudyDate) != date_filter:
                continue
            if uid_filter and study_uid != uid_filter:
                continue

            series_uids = {ds.SeriesInstanceUID for ds in instances}
            modalities = sorted({str(ds.Modality) for ds in instances})

            rsp = Dataset()
            rsp.QueryRetrieveLevel = "STUDY"
            rsp.StudyInstanceUID = study_uid
            rsp.PatientName = first.PatientName
            rsp.PatientID = first.PatientID
            rsp.StudyDate = first.StudyDate
            rsp.StudyDescription = getattr(first, "StudyDescription", "")
            rsp.AccessionNumber = getattr(first, "AccessionNumber", "")
            rsp.ModalitiesInStudy = modalities
            rsp.NumberOfStudyRelatedSeries = len(series_uids)
            rsp.NumberOfStudyRelatedInstances = len(instances)
            yield 0xFF00, rsp

    def _find_series(self, query: Dataset):
        study_uid = str(getattr(query, "StudyInstanceUID", "") or "")

        series: dict[str, list[Dataset]] = {}
        for ds in self._instances:
            if study_uid and ds.StudyInstanceUID != study_uid:
                continue
            series.setdefault(ds.SeriesInstanceUID, []).append(ds)

        for series_uid, instances in series.items():
            first = instances[0]
            rsp = Dataset()
            rsp.QueryRetrieveLevel = "SERIES"
            rsp.StudyInstanceUID = first.StudyInstanceUID
            rsp.SeriesInstanceUID = series_uid
            rsp.Modality = first.Modality
            rsp.SeriesNumber = getattr(first, "SeriesNumber", None)
            rsp.SeriesDescription = getattr(first, "SeriesDescription", "")
            rsp.NumberOfSeriesRelatedInstances = len(instances)
            yield 0xFF00, rsp
