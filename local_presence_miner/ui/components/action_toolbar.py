from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from local_presence_miner.ui.icons import app_icon
from local_presence_miner.ui.theme import set_button_role


def action_button(
    text: str,
    callback: Callable | None = None,
    *,
    role: str = "secondary",
    icon: str | None = None,
    tooltip: str = "",
    parent: QWidget | None = None,
) -> QPushButton:
    button = QPushButton(text, parent)
    set_button_role(button, role)
    if icon:
        button.setIcon(app_icon(button, icon))
    if tooltip:
        button.setToolTip(tooltip)
    if callback:
        button.clicked.connect(callback)
    return button


class ActionToolbar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

    def add_action(
        self,
        text: str,
        callback: Callable | None = None,
        *,
        role: str = "secondary",
        icon: str | None = None,
        tooltip: str = "",
    ) -> QPushButton:
        button = action_button(text, callback, role=role, icon=icon, tooltip=tooltip, parent=self)
        self.layout.addWidget(button)
        return button

    def add_stretch(self) -> None:
        self.layout.addStretch(1)
