from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class Toast(QFrame):
    @classmethod
    def show_message(cls, parent: QWidget, message: str, tone: str = "success", duration_ms: int = 2600) -> Toast:
        toast = cls(parent)
        toast.setProperty("bannerTone", tone)
        layout = QHBoxLayout(toast)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(QLabel(message))
        toast.adjustSize()
        toast.move(max(12, parent.width() - toast.width() - 18), 18)
        toast.show()
        toast.raise_()
        QTimer.singleShot(duration_ms, toast.deleteLater)
        return toast
