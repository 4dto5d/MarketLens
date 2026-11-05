from __future__ import annotations

from PySide6.QtWidgets import QLabel


class LeadDetailWidget(QLabel):
    def __init__(self) -> None:
        super().__init__("Open a lead from the Leads table to view details.")
