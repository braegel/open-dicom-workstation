"""Tests for thread-pool workers and the SCP-to-UI signal bridge."""

import threading
import time

from PySide6.QtCore import QThread

from odw.ui.scp_bridge import ScpBridge
from odw.ui.workers import Worker, run_in_pool


def test_worker_emits_result(qtbot):
    signals = run_in_pool(lambda: 42)
    with qtbot.waitSignal(signals.result, timeout=5000) as blocker:
        pass
    assert blocker.args == [42]


def test_result_not_lost_when_caller_connects_late(qtbot):
    # The worker must not start before control returns to the event loop:
    # a signal emitted while still unconnected would be silently dropped.
    signals = run_in_pool(lambda: 7)
    time.sleep(0.2)
    with qtbot.waitSignal(signals.result, timeout=5000) as blocker:
        pass
    assert blocker.args == [7]


def test_worker_emits_error_on_exception(qtbot):
    def boom():
        raise ValueError("boom")

    results: list[object] = []
    worker = Worker(boom)
    worker.signals.result.connect(results.append)
    with qtbot.waitSignal(worker.signals.error, timeout=5000) as blocker:
        worker.run()
    assert "boom" in blocker.args[0]
    assert results == []


def test_worker_emits_finished_after_result_and_after_error(qtbot):
    events: list[str] = []

    ok_worker = Worker(lambda: "ok")
    ok_worker.signals.result.connect(lambda _: events.append("result"))
    ok_worker.signals.finished.connect(lambda: events.append("finished"))
    with qtbot.waitSignal(ok_worker.signals.finished, timeout=5000):
        ok_worker.run()
    assert events == ["result", "finished"]

    events.clear()

    def boom():
        raise RuntimeError("nope")

    err_worker = Worker(boom)
    err_worker.signals.error.connect(lambda _: events.append("error"))
    err_worker.signals.finished.connect(lambda: events.append("finished"))
    with qtbot.waitSignal(err_worker.signals.finished, timeout=5000):
        err_worker.run()
    assert events == ["error", "finished"]


def test_worker_forwards_progress(qtbot):
    def stepped(*, on_progress):
        on_progress(1, 2)
        on_progress(2, 1)
        return "done"

    received: list[tuple[int, int]] = []
    worker = Worker(stepped, forward_progress=True)
    worker.signals.progress.connect(lambda c, r: received.append((c, r)))
    with qtbot.waitSignal(worker.signals.finished, timeout=5000):
        worker.run()
    assert received == [(1, 2), (2, 1)]


def test_scp_bridge_delivers_across_threads(qtbot):
    bridge = ScpBridge()
    payload = object()
    delivered: list[tuple[object, QThread]] = []

    def slot(record):
        delivered.append((record, QThread.currentThread()))

    bridge.instance_stored.connect(slot)

    main_thread = QThread.currentThread()
    with qtbot.waitSignal(bridge.instance_stored, timeout=5000):
        worker_thread = threading.Thread(target=bridge.notify, args=(payload,))
        worker_thread.start()
        worker_thread.join()

    assert len(delivered) == 1
    record, thread = delivered[0]
    assert record is payload
    assert thread is main_thread
