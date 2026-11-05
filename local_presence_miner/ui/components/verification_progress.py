from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class VerificationProgress(QWidget):
    def __init__(self, completed: int = 0, total: int = 0, state: str = "Unverified", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.label = QLabel()
        self.label.setProperty("role", "metricLabel")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        self.set_progress(completed, total, state)

    def set_progress(self, completed: int, total: int, state: str) -> None:
        self.label.setText(f"Verification  {completed} / {total} required checks — {state}")
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(completed)
        self.setAccessibleName(self.label.text())
