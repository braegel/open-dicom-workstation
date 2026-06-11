"""Bridge from SCP/network threads into the Qt UI thread."""

from PySide6.QtCore import QObject, Signal


class ScpBridge(QObject):
    """The only sanctioned path from SCP/network threads into the UI thread.

    ``notify`` may be called from any thread; Qt's queued signal delivery
    hands the payload to slots on the thread the bridge lives in (the UI thread).
    """

    instance_stored = Signal(object)

    def notify(self, record: object) -> None:
        """Thread-safe: emit ``instance_stored`` with *record*."""
        self.instance_stored.emit(record)
