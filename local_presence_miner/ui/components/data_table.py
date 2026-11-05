from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget


class DataTable(QTableWidget):
    def __init__(self, columns: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setSortingEnabled(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(True)
        if columns:
            self.setColumnCount(len(columns))
            self.setHorizontalHeaderLabels(columns)

    def fit_columns(self, *, stretch_column: int | None = None) -> None:
        self.resizeColumnsToContents()
        if stretch_column is not None and 0 <= stretch_column < self.columnCount():
            self.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)


def table_item(value, *, numeric: bool = False, tooltip: str = "", user_data=None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value if value is not None else ""))
    if numeric:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if tooltip or len(item.text()) > 48:
        item.setToolTip(tooltip or item.text())
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    return item
