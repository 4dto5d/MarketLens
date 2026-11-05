from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PageHeader(QFrame):
    def __init__(self, title: str = "", description: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopCommandBar")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(22, 12, 22, 12)
        self.layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(title)
        self.title.setProperty("role", "pageTitle")
        self.description = QLabel(description)
        self.description.setProperty("role", "pageDescription")
        self.description.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.description)
        self.layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.layout.addLayout(self.actions)

    def set_page(self, title: str, description: str = "") -> None:
        self.title.setText(title)
        self.description.setText(description)

    def clear_actions(self) -> None:
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)
