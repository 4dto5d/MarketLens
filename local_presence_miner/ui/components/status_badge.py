from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from local_presence_miner.ui.theme import repolish


def status_tone(status: str) -> str:
    normalized = status.lower().replace("_", " ").strip()
    if any(word in normalized for word in ["won", "ready", "approved", "verified", "complete", "configured"]):
        return "success"
    if any(word in normalized for word in ["overdue", "blocked", "suppressed", "error", "failed"]):
        return "danger"
    if any(word in normalized for word in ["review", "due", "pending", "negotiating", "warning", "unverified"]):
        return "warning"
    if any(word in normalized for word in ["new", "qualified", "contacted", "replied", "presented", "accepted"]):
        return "primary"
    return "neutral"


class StatusBadge(QLabel):
    def __init__(self, text: str = "", tone: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("badge", True)
        self.set_status(text, tone)
        self.setSizePolicy(self.sizePolicy().Policy.Maximum, self.sizePolicy().Policy.Fixed)

    def set_status(self, text: str, tone: str | None = None) -> None:
        self.setText(text.upper() if text else "—")
        self.setProperty("badgeTone", tone or status_tone(text))
        self.setAccessibleName(f"Status: {text or 'not set'}")
        repolish(self)
