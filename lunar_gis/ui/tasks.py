"""M9 background tasks: non-blocking provider work (Qt/QGIS-only parts isolated).

The dock must never freeze on network I/O. Long work (catalog search,
downloads) runs in ``QgsTask`` workers via ``run_in_background``; the
calling thread only handles signals.

Thread-safety contract (hard rule): worker callables MUST NOT touch
live QGIS objects (layers, project, canvas, layouts), QgsSettings, or
Qt widgets. Files/network/pure-Python only — provider handlers satisfy
this (unique sandbox per call, in-memory provenance). Violations will
crash QGIS; keep them out by review, not by runtime checks.

``ProgressState`` is QGIS-free (offline-tested) and doubles as the
transport ``ProgressCallback``. ``FunctionTask`` needs QGIS (built by
``create_task`` with a deferred import; qgis-marked tests cover it).
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class ProgressState:
    """Thread-safe byte progress + cooperative cancellation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._received = 0
        self._total: int | None = None
        self._cancelled = False

    def update(self, received_bytes: int, total_bytes: int | None) -> None:
        with self._lock:
            self._received = received_bytes
            self._total = total_bytes

    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self._total
            received = self._received
        fraction = (received / total) if total else None
        return {"received": received, "total": total, "fraction": fraction, "cancelled": self.cancelled()}


def create_task(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Build a QgsTask running ``fn(*args, **kwargs)`` off the GUI thread.

    Returns the task with ``succeeded(dict)`` and ``failed(str)`` Qt
    signals. Raises ImportError without QGIS. The caller owns
    ``QgsApplication.taskManager().addTask(task)``.
    """
    try:
        from qgis.core import QgsTask  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("QGIS runtime required for background tasks") from exc

    from qgis.PyQt.QtCore import pyqtSignal  # type: ignore[import-not-found]

    class FunctionTask(QgsTask):
        succeeded = pyqtSignal(dict)
        failed = pyqtSignal(str)

        def __init__(self) -> None:
            super().__init__(name, QgsTask.CanCancel)
            self._fn = fn
            self._args = args
            self._kwargs = kwargs
            self._outcome: dict[str, Any] = {"ok": False, "error": "not-run"}

        def run(self) -> bool:
            try:
                self._outcome = {"ok": True, "result": self._fn(*self._args, **self._kwargs)}
                return True
            except Exception as exc:  # worker must never raise out of run()
                self._outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}
                return False

        def finished(self, result: bool) -> None:
            if result and self._outcome.get("ok"):
                self.succeeded.emit(self._outcome)
            else:
                self.failed.emit(str(self._outcome.get("error", "task failed")))

    return FunctionTask()


__all__ = ["ProgressState", "create_task"]
