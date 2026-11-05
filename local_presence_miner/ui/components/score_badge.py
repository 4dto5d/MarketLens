from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def score_band(score: int) -> tuple[str, str]:
    if score >= 80:
        return "High triage priority", "success"
    if score >= 60:
        return "Worth Review", "primary"
    if score >= 40:
        return "Moderate", "warning"
    return "Low Priority", "neutral"


class ScoreBadge(QFrame):
    def __init__(self, score: int = 0, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", "subtle")
        self.score = QLabel()
        self.score.setProperty("role", "metricValue")
        self.band = QLabel()
        self.band.setProperty("role", "metricSupport")
        if compact:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(8, 3, 8, 3)
            layout.setSpacing(7)
            layout.addWidget(self.score)
            layout.addWidget(self.band)
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(11, 7, 11, 7)
            layout.setSpacing(0)
            layout.addWidget(self.score)
            layout.addWidget(self.band)
        self.set_score(score)

    def set_score(self, score: int) -> None:
        band, tone = score_band(score)
        self.score.setText(str(score))
        self.band.setText(band)
        self.setProperty("accent", tone)
        self.setToolTip("Growth Score summarizes observable opportunity signals. It is not a close probability.")
        self.setAccessibleName(f"Growth Score {score}, {band}")
