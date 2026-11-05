from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget


class FieldMessage(QLabel):
    def __init__(self, text: str = "", error: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setProperty("tone", "muted")
        self.setStyleSheet("color: #B91C1C;" if error else "")

    def set_error(self, text: str, field: QWidget | None = None) -> None:
        self.setText(text)
        self.setStyleSheet("color: #B91C1C;")
        if field:
            field.setProperty("fieldState", "error")
            field.style().unpolish(field)
            field.style().polish(field)

    def clear_error(self, field: QWidget | None = None) -> None:
        self.clear()
        self.setStyleSheet("")
        if field:
            field.setProperty("fieldState", "")
            field.style().unpolish(field)
            field.style().polish(field)

    def set_message(self, text: str, tone: str = "error", field: QWidget | None = None) -> None:
        if tone == "error":
            self.set_error(text, field)
            return
        self.setText(text)
        self.setStyleSheet("color: #15803D;" if tone == "success" else "")

    def clear_message(self, field: QWidget | None = None) -> None:
        self.clear_error(field)
