"""Storage SCP receiving instances into the local DICOM store. No Qt; blocking calls."""

from collections.abc import Callable

from pynetdicom import AE, AllStoragePresentationContexts, evt

from odw.core.models import InstanceRecord
from odw.core.storage import DicomStore


class StorageScp:
    """Non-blocking pynetdicom storage SCP ingesting received instances into a DicomStore."""

    def __init__(
        self,
        ae_title: str,
        port: int,
        store: DicomStore,
        on_instance: Callable[[InstanceRecord], None] | None = None,
    ) -> None:
        self._ae_title = ae_title
        self._requested_port = port
        self._store = store
        self._on_instance = on_instance
        self._server = None
        self._port: int | None = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("StorageScp is not running")
        return self._port

    def start(self) -> None:
        ae = AE(ae_title=self._ae_title)
        ae.supported_contexts = AllStoragePresentationContexts
        self._server = ae.start_server(
            ("0.0.0.0", self._requested_port),
            block=False,
            evt_handlers=[(evt.EVT_C_STORE, self._handle_store)],
        )
        self._port = self._server.socket.getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            self._port = None

    def _handle_store(self, event) -> int:
        try:
            ds = event.dataset
            ds.file_meta = event.file_meta
            record = self._store.ingest(ds)
            if self._on_instance is not None:
                self._on_instance(record)
        except Exception:
            return 0xC001  # Cannot understand / processing failure
        return 0x0000
