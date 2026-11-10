"""Per-proposal opt-in; receives only the approved external disclosure whitelist."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout


class ProposalEvidenceDialog(QDialog):
    def __init__(self, choices: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Select AI observations for this proposal')
        self.resize(800,620)
        self.choices = choices
        layout = QVBoxLayout(self)
        note = QLabel('No AI observations are selected by default. Check only those you want in this proposal. '
                      'The preview shows the complete approved external text. Eligibility is checked again before generation.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.observations = QListWidget()
        self.observations.setAccessibleName('AI observations for this proposal')
        for choice in choices:
            item = QListWidgetItem(choice['disclosure'].splitlines()[0])
            item.setData(Qt.ItemDataRole.UserRole,choice['reference'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.observations.addItem(item)
        layout.addWidget(self.observations)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName('Complete approved external text')
        layout.addWidget(self.preview)
        self.observations.currentRowChanged.connect(self.show_preview)
        if choices:
            self.observations.setCurrentRow(0)
        actions = QHBoxLayout()
        generate = QPushButton('Generate with selected evidence')
        generate.clicked.connect(self.accept)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        actions.addWidget(generate)
        actions.addWidget(cancel)
        layout.addLayout(actions)

    def show_preview(self, row: int) -> None:
        self.preview.setPlainText(self.choices[row]['disclosure'] if 0 <= row < len(self.choices) else '')

    def selected_references(self) -> list[str]:
        return [self.observations.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.observations.count())
                if self.observations.item(row).checkState() == Qt.CheckState.Checked]
