from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from local_presence_miner.ui.components.action_toolbar import action_button


class EmptyState(QWidget):
    action_requested = Signal()

    def __init__(
        self,
        title: str,
        message: str,
        action_text: str = "",
        action: Callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 30, 24, 30)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(7)
        title_label = QLabel(title.upper())
        title_label.setProperty("role", "sectionTitle")
        message_label = QLabel(message)
        message_label.setProperty("role", "sectionDescription")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMaximumWidth(520)
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label, alignment=Qt.AlignmentFlag.AlignCenter)
        if action_text:
            button = action_button(action_text, role="primary")
            button.clicked.connect(self.action_requested.emit)
            if action:
                self.action_requested.connect(action)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)
