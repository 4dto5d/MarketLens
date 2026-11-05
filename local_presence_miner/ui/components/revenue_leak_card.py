from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from local_presence_miner.ui.components.status_badge import StatusBadge


class RevenueLeakCard(QFrame):
    def __init__(
        self,
        title: str,
        explanation: str = "",
        evidence: str = "",
        impact: str = "Review",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("surface", "subtle")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        row_title = QLabel(title.upper())
        row_title.setProperty("role", "metricLabel")
        layout.addWidget(row_title)
        layout.addWidget(StatusBadge(f"{impact} impact", "warning" if impact.lower() != "low" else "neutral"))
        if explanation:
            detail = QLabel(explanation)
            detail.setWordWrap(True)
            layout.addWidget(detail)
        if evidence:
            evidence_label = QLabel(f"<b>Evidence:</b> {evidence}")
            evidence_label.setWordWrap(True)
            evidence_label.setProperty("tone", "muted")
            layout.addWidget(evidence_label)
