"""Synchronous C-GET/C-MOVE retrieve SCU. No Qt; blocking calls."""

from collections.abc import Callable, Iterator
from typing import cast

from pydicom.dataset import Dataset
from pydicom.uid import UID
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.pdu_primitives import _UI, SCP_SCU_RoleSelectionNegotiation
from pynetdicom.sop_class import (  # type: ignore[attr-defined]
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
)

from odw.core.models import PacsNode, RetrieveResult
from odw.core.net import PacsConnectionError
from odw.core.storage import DicomStore

_PENDING = (0xFF00, 0xFF01)
# One presentation context is reserved for the Q/R information model.
_MAX_STORAGE_CONTEXTS = 127


def _count(status: Dataset, keyword: str) -> int:
    value = getattr(status, keyword, None)
    if value is None or value == "":
        return 0
    return int(value)


def _study_identifier(study_uid: str) -> Dataset:
    identifier = Dataset()
    identifier.QueryRetrieveLevel = "STUDY"
    identifier.StudyInstanceUID = study_uid
    return identifier


_STATUS_MESSAGES = {
    0xA801: "Move destination unknown",
}


class RetrieveScu:
    """Blocking Study Root C-GET/C-MOVE SCU. Threading is the caller's concern."""

    def __init__(self, local_aet: str, node: PacsNode) -> None:
        self._local_aet = local_aet
        self._node = node

    def get_study(
        self,
        study_uid: str,
        store: DicomStore,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> RetrieveResult:
        ae = AE(ae_title=self._local_aet)
        ae.acse_timeout = 5
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        ext_neg: list[_UI] = []
        for context in StoragePresentationContexts[:_MAX_STORAGE_CONTEXTS]:
            # Storage presentation contexts always carry an abstract syntax.
            abstract_syntax = cast(UID, context.abstract_syntax)
            ae.add_requested_context(abstract_syntax)
            role = SCP_SCU_RoleSelectionNegotiation()
            role.sop_class_uid = abstract_syntax
            role.scu_role = False
            role.scp_role = True
            ext_neg.append(role)

        def handle_store(event: evt.Event) -> int:
            ds = event.dataset
            ds.file_meta = event.file_meta
            store.ingest(ds)
            return 0x0000

        assoc = ae.associate(
            self._node.host,
            self._node.port,
            ae_title=self._node.ae_title,
            ext_neg=ext_neg,
            evt_handlers=[(evt.EVT_C_STORE, handle_store)],
        )
        if not assoc.is_established:
            raise PacsConnectionError(
                f"Could not associate with {self._node.ae_title} at "
                f"{self._node.host}:{self._node.port}"
            )

        try:
            responses = assoc.send_c_get(
                _study_identifier(study_uid), StudyRootQueryRetrieveInformationModelGet
            )
            return self._collect(responses, "C-GET", on_progress)
        finally:
            assoc.release()

    def move_study(
        self,
        study_uid: str,
        dest_aet: str,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> RetrieveResult:
        ae = AE(ae_title=self._local_aet)
        ae.acse_timeout = 5
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc = ae.associate(self._node.host, self._node.port, ae_title=self._node.ae_title)
        if not assoc.is_established:
            raise PacsConnectionError(
                f"Could not associate with {self._node.ae_title} at "
                f"{self._node.host}:{self._node.port}"
            )
        try:
            responses = assoc.send_c_move(
                _study_identifier(study_uid),
                dest_aet,
                StudyRootQueryRetrieveInformationModelMove,
            )
            return self._collect(responses, "C-MOVE", on_progress)
        finally:
            assoc.release()

    def _collect(
        self,
        responses: Iterator[tuple[Dataset, Dataset | None]],
        operation: str,
        on_progress: Callable[[int, int], None] | None,
    ) -> RetrieveResult:
        """Drain pending responses, reporting progress; build the result from the final one."""
        result = RetrieveResult(completed=0, failed=0, warnings=0)
        for status, _rsp in responses:
            if status is None:
                raise PacsConnectionError(
                    f"Connection to {self._node.ae_title} lost during {operation}"
                )
            completed = _count(status, "NumberOfCompletedSuboperations")
            remaining = _count(status, "NumberOfRemainingSuboperations")
            if on_progress is not None:
                on_progress(completed, remaining)
            if status.Status not in _PENDING:
                result = RetrieveResult(
                    completed=completed,
                    failed=_count(status, "NumberOfFailedSuboperations"),
                    warnings=_count(status, "NumberOfWarningSuboperations"),
                    message=_STATUS_MESSAGES.get(
                        status.Status,
                        "" if status.Status == 0x0000 else f"Status 0x{status.Status:04X}",
                    ),
                )
        return result
