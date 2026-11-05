from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from local_presence_miner.ui.components.status_badge import StatusBadge


class PricingRecommendationPanel(QFrame):
    def __init__(self, recommendation=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", "card")
        self.setProperty("accent", "primary")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        heading = QLabel("PRICING RECOMMENDATION")
        heading.setProperty("role", "metricLabel")
        root.addWidget(heading)
        self.project = QLabel("Service-cost band —")
        self.project.setProperty("role", "sectionTitle")
        self.project.setToolTip("Catalog service-cost range, not measured buyer value or ROI. Seller evidence does not change this range.")
        root.addWidget(self.project)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.easy = self._price_block(grid, 0, "EASY-CLOSE")
        self.recommended = self._price_block(grid, 1, "RECOMMENDED", dominant=True)
        self.stretch = self._price_block(grid, 2, "STRETCH")
        root.addLayout(grid)
        confidence_row = QGridLayout()
        confidence_row.addWidget(QLabel("Evidence Confidence"), 0, 0)
        self.confidence = StatusBadge("Low", "warning")
        self.confidence.setToolTip("How much relevant seller/history evidence supports the recommendation. This is not a close probability.")
        confidence_row.addWidget(self.confidence, 0, 1)
        confidence_row.setColumnStretch(2, 1)
        root.addLayout(confidence_row)
        if recommendation:
            self.set_recommendation(recommendation)

    def _price_block(self, grid: QGridLayout, column: int, title: str, dominant: bool = False) -> QLabel:
        title_label = QLabel(title)
        title_label.setProperty("role", "metricLabel")
        value = QLabel("—")
        value.setProperty("role", "metricValue")
        if dominant:
            value.setStyleSheet("color: #93C5FD; font-size: 30px;")
        grid.addWidget(title_label, 0, column)
        grid.addWidget(value, 1, column)
        return value

    def set_recommendation(self, recommendation) -> None:
        self.project.setText(f"Service-cost band  {recommendation.project.range_text}")
        self.easy.setText(recommendation.easy_close_text)
        self.recommended.setText(recommendation.recommended_text)
        self.stretch.setText(recommendation.stretch_text)
        self.confidence.set_status(recommendation.confidence)
