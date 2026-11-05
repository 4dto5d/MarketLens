from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from local_presence_miner.ui.icons import app_icon


class InfoBanner(QFrame):
    def __init__(self, title: str, message: str = "", tone: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("bannerTone", tone)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        icon = QLabel()
        icon_name = {"danger": "error", "warning": "warning", "success": "success"}.get(tone, "info")
        icon.setPixmap(app_icon(self, icon_name).pixmap(QSize(18, 18)))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QLabel(f"<b>{title}</b>" + (f"<br>{message}" if message else ""))
        text.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(text, 1)

    def set_content(self, title: str, message: str) -> None:
        label = self.findChildren(QLabel)[-1]
        label.setText(f"<b>{title}</b>" + (f"<br>{message}" if message else ""))
