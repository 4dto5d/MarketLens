from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from local_presence_miner.config import AppConfig


class SetupWizardWidget(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>First-Run Setup</h2>"))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.refresh()

    def refresh(self) -> None:
        self.text.setPlainText(
            "\n".join(
                [
                    "1. Start with offline/demo mode if you do not have a Google API key.",
                    "2. Use online mode only after setting GOOGLE_MAPS_API_KEY.",
                    "3. Use AI prompt mode if you have ChatGPT Plus but no API key.",
                    "4. Generate owner_short reports for first share, internal reports for your own notes.",
                    "5. Use proposals and paid-style website exports for warmer leads.",
                    "6. Add a 7-10 second licensed hero video to site_exports/<lead>/assets/hero-video.mp4 for premium sites.",
                    "7. Treat chat/AI bubbles as add-ons; the export includes UI only until connected.",
                    "8. Manual review is required before outreach.",
                    "9. Do not claim profile ownership status unless verified.",
                    "10. Do not create, buy, schedule, or disguise fake reviews.",
                    "",
                    f"Database: {self.config.database_path}",
                    f"Outputs: {self.config.output_dir}",
                    f"Google key present: {'yes' if self.config.google_maps_api_key else 'no'}",
                ]
            )
        )
