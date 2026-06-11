"""Thread-pool workers: run blocking callables off the UI thread, report via signals."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal


class WorkerSignals(QObject):
    """Signals emitted by a :class:`Worker`. Lives as a QObject so it can own signals."""

    result = Signal(object)
    error = Signal(str)
    finished = Signal()
    progress = Signal(int, int)


class Worker(QRunnable):
    """Run ``fn(*args, **kwargs)`` on a thread pool and report through ``signals``.

    Pass ``forward_progress=True`` to inject an ``on_progress(current, total)``
    keyword argument that re-emits as the ``progress`` signal.
    """

    def __init__(self, fn: Callable[..., object], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        forward_progress = kwargs.pop("forward_progress", False)
        self.signals = WorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        if forward_progress:
            self._kwargs["on_progress"] = lambda current, total: self.signals.progress.emit(
                current, total
            )

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - worker boundary reports all failures
            self.signals.error.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


def run_in_pool(fn: Callable[..., object], *args: Any, **kwargs: Any) -> WorkerSignals:
    """Start ``fn`` on the global thread pool; return the worker's signals.

    The start is deferred to the next event-loop iteration so the caller can
    connect to the signals first — emissions to unconnected signals are lost.
    """
    worker = Worker(fn, *args, **kwargs)
    QTimer.singleShot(0, lambda: QThreadPool.globalInstance().start(worker))
    return worker.signals
