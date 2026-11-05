from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class MetricCard(QFrame):
    def __init__(
        self,
        label: str,
        value: str | int = "0",
        support: str = "",
        *,
        accent: str = "neutral",
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("surface", "card")
        self.setProperty("accent", accent)
        self.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(2)
        self.label_widget = QLabel(label)
        self.label_widget.setProperty("role", "metricLabel")
        self.value_widget = QLabel(str(value))
        self.value_widget.setProperty("role", "metricValue")
        self.support_widget = QLabel(support)
        self.support_widget.setProperty("role", "metricSupport")
        self.support_widget.setWordWrap(True)
        layout.addWidget(self.label_widget)
        layout.addWidget(self.value_widget)
        layout.addWidget(self.support_widget)
        layout.addStretch(1)

    def set_value(self, value: str | int, support: str | None = None) -> None:
        self.value_widget.setText(str(value))
        if support is not None:
            self.support_widget.setText(support)
