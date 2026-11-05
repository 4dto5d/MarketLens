from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout

from local_presence_miner.config import AppConfig, save_settings


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.config = config
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.google_key = QLineEdit(config.google_maps_api_key)
        self.google_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.pagespeed_key = QLineEdit(config.pagespeed_api_key)
        self.pagespeed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.sender_name = QLineEdit(config.sender.name)
        self.sender_business = QLineEdit(config.sender.business_name)
        self.reply_email = QLineEdit(config.sender.reply_email)
        self.sender_phone = QLineEdit(config.sender.phone)
        self.postal_address = QLineEdit(config.sender.postal_address)
        self.opt_out = QLineEdit(config.sender.opt_out_line)
        self.default_radius = QSpinBox()
        self.default_radius.setRange(1, 100000)
        self.default_radius.setValue(config.default_radius_meters)
        self.timeout = QSpinBox()
        self.timeout.setRange(3, 120)
        self.timeout.setValue(config.request_timeout_seconds)
        self.audit_workers = QSpinBox()
        self.audit_workers.setRange(1, 4)
        self.audit_workers.setValue(max(1, min(config.audit_concurrency, 4)))
        self.output_dir = QLineEdit(str(config.output_dir))

        form.addRow("Google Maps API key", self.google_key)
        form.addRow("PageSpeed API key", self.pagespeed_key)
        form.addRow("Default radius meters", self.default_radius)
        form.addRow("Timeout seconds", self.timeout)
        form.addRow("Concurrent raw-audit workers", self.audit_workers)
        form.addRow("Output directory", self.output_dir)
        form.addRow("Sender name", self.sender_name)
        form.addRow("Business name", self.sender_business)
        form.addRow("Reply email", self.reply_email)
        form.addRow("Phone", self.sender_phone)
        form.addRow("Postal address", self.postal_address)
        form.addRow("Opt-out line", self.opt_out)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def save(self) -> None:
        try:
            save_settings(
                self.config.app_data_dir,
                {
                    "google_maps_api_key": self.google_key.text().strip(),
                    "pagespeed_api_key": self.pagespeed_key.text().strip(),
                    "default_radius_meters": str(self.default_radius.value()),
                    "request_timeout_seconds": str(self.timeout.value()),
                    "audit_concurrency": str(self.audit_workers.value()),
                    "output_dir": self.output_dir.text().strip(),
                    "sender_name": self.sender_name.text().strip(),
                    "sender_business": self.sender_business.text().strip(),
                    "reply_email": self.reply_email.text().strip(),
                    "sender_phone": self.sender_phone.text().strip(),
                    "postal_address": self.postal_address.text().strip(),
                    "opt_out_line": self.opt_out.text().strip(),
                },
            )
        except OSError as exc:
            QMessageBox.critical(self, "Settings not saved", str(exc))
            return
        self.accept()
