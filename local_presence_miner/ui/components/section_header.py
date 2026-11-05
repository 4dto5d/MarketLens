from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class SectionHeader(QWidget):
    def __init__(self, title: str, description: str = "", action: QWidget | None = None, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(1)
        title_label = QLabel(title)
        title_label.setProperty("role", "sectionTitle")
        text.addWidget(title_label)
        if description:
            description_label = QLabel(description)
            description_label.setWordWrap(True)
            description_label.setProperty("role", "sectionDescription")
            text.addWidget(description_label)
        row.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)
        if action:
            self.add_action(action)

    def add_action(self, action: QWidget) -> None:
        self.actions.addWidget(action)
