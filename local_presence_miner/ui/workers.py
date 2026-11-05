from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    started = Signal()
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(self, func, *args, **kwargs) -> None:
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            self.signals.finished.emit(self.func(*self.args, **self.kwargs))
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
