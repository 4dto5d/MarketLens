from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from local_presence_miner.services.prompt_parser import parsed_summary_text


class PromptPasteWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Prompt Paste Helper</h2>"))
        layout.addWidget(
            QLabel(
                "Paste a ChatGPT Plus answer here after using a generated competitor prompt. "
                "This does not send data to any API; it only summarizes pasted text locally."
            )
        )
        self.input = QTextEdit()
        self.input.setPlaceholderText("Paste ChatGPT answer here...")
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        parse = QPushButton("Parse Answer Preview")
        parse.clicked.connect(self.parse)
        layout.addWidget(self.input)
        layout.addWidget(parse)
        layout.addWidget(self.output)

    def parse(self) -> None:
        self.output.setPlainText(parsed_summary_text(self.input.toPlainText()))
