"""Synchronous C-GET/C-MOVE retrieve SCU. No Qt; blocking calls."""

from collections.abc import Callable

from pydicom.dataset import Dataset
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.pdu_primitives import SCP_SCU_RoleSelectionNegotiation
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelGet

from odw.core.models import PacsNode, RetrieveResult
from odw.core.net import PacsConnectionError
from odw.core.storage import DicomStore

_PENDING = (0xFF00, 0xFF01)
# One presentation context is reserved for the Q/R information model.
_MAX_STORAGE_CONTEXTS = 127


def _count(status: Dataset, keyword: str) -> int:
    value = getattr(status, keyword, None)
    return 0 if value in (None, "") else int(value)


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
        ext_neg = []
        for context in StoragePresentationContexts[:_MAX_STORAGE_CONTEXTS]:
            ae.add_requested_context(context.abstract_syntax)
            role = SCP_SCU_RoleSelectionNegotiation()
            role.sop_class_uid = context.abstract_syntax
            role.scu_role = False
            role.scp_role = True
            ext_neg.append(role)

        def handle_store(event) -> int:
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

        identifier = Dataset()
        identifier.QueryRetrieveLevel = "STUDY"
        identifier.StudyInstanceUID = study_uid

        result = RetrieveResult(completed=0, failed=0, warnings=0)
        try:
            for status, _rsp in assoc.send_c_get(
                identifier, StudyRootQueryRetrieveInformationModelGet
            ):
                if status is None:
                    raise PacsConnectionError(
                        f"Connection to {self._node.ae_title} lost during C-GET"
                    )
                completed = _count(status, "NumberOfCompletedSuboperations")
                remaining = _count(status, "NumberOfRemainingSuboperations")
                if status.Status in _PENDING:
                    if on_progress is not None:
                        on_progress(completed, remaining)
                else:
                    if on_progress is not None:
                        on_progress(completed, remaining)
                    result = RetrieveResult(
                        completed=completed,
                        failed=_count(status, "NumberOfFailedSuboperations"),
                        warnings=_count(status, "NumberOfWarningSuboperations"),
                    )
        finally:
            assoc.release()
        return result
