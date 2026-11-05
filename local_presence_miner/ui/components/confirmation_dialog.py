from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from local_presence_miner.ui.components.info_banner import InfoBanner
from local_presence_miner.ui.theme import set_button_role


def confirm_destructive(parent: QWidget, title: str, message: str, action_text: str = "Delete") -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(430)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(14)
    layout.addWidget(InfoBanner(title, message, "danger"))
    note = QLabel("This action cannot be undone from inside Local Presence Miner.")
    note.setProperty("tone", "muted")
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    destructive = buttons.addButton(action_text, QDialogButtonBox.ButtonRole.DestructiveRole)
    set_button_role(destructive, "danger")
    destructive.clicked.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QDialog.DialogCode.Accepted
