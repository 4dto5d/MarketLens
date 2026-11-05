from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from local_presence_miner.config import AppConfig
from local_presence_miner.domain.categories import category_from_label, opportunity_category_labels, opportunity_reason
from local_presence_miner.domain.models import SearchCriteria
from local_presence_miner.services.google_places import ENRICHMENT_LIMITS, estimate_places_api_calls
from local_presence_miner.services.rendered_auditor import rendered_audit_availability


class NewSearchDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Lead Search")
        self.config = config
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.city = QLineEdit("Flint")
        self.state_region = QLineEdit("MI")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(opportunity_category_labels())
        self.category.setCurrentText("Top Opportunities / roofers")
        self.category.currentTextChanged.connect(self.update_category_reason)
        self.category_reason = QLineEdit()
        self.category_reason.setReadOnly(True)
        self.target_zip = QLineEdit("48502")
        self.radius_miles = QSpinBox()
        self.radius_miles.setRange(1, 30)
        self.radius_miles.setValue(10)
        self.max_results = QSpinBox()
        self.max_results.setRange(1, 100)
        self.max_results.setValue(20)
        self.max_results.valueChanged.connect(self.update_api_estimate)
        self.google_data_depth = QComboBox()
        self.google_data_depth.addItems(ENRICHMENT_LIMITS)
        self.google_data_depth.setCurrentText("Economy")
        self.google_data_depth.setToolTip(
            "Controls how many businesses receive the same Place Details fields: Economy 8, Balanced 20, Deep Prospecting 40."
        )
        self.google_data_depth.currentTextChanged.connect(self.update_api_estimate)
        self.api_estimate = QLabel()
        self.api_estimate.setWordWrap(True)
        self.min_reviews = QSpinBox()
        self.min_reviews.setRange(0, 1000)
        self.min_rating = QDoubleSpinBox()
        self.min_rating.setRange(0, 5)
        self.min_rating.setSingleStep(0.1)
        self.include_no_website = QCheckBox()
        self.include_no_website.setChecked(False)
        self.include_weak_website = QCheckBox()
        self.include_weak_website.setChecked(False)
        self.include_low_rank = QCheckBox()
        self.include_low_rank.setChecked(False)
        self.include_review_growth = QCheckBox()
        self.include_review_growth.setChecked(False)
        for criterion in (
            self.include_no_website,
            self.include_weak_website,
            self.include_low_rank,
            self.include_review_growth,
        ):
            criterion.setEnabled(False)
            criterion.setToolTip("Reserved for a future targeting filter; this control is not applied by this version.")
        self.pagespeed = QCheckBox("Runs only for live websites")
        rendered_available, rendered_reason = rendered_audit_availability()
        self.rendered_available = rendered_available
        self.rendered = QCheckBox(rendered_reason)
        self.screenshots = QCheckBox("Capture desktop and mobile screenshots during rendered verification")
        self.rendered.toggled.connect(self.update_live_controls)
        self.top_mockups = QSpinBox()
        self.top_mockups.setRange(0, 20)
        self.top_mockups.setValue(3)
        self.output_name = QLineEdit("demo-roofers-flint")
        self.safe_live_test = QCheckBox("Real data, maximum 5 businesses, no automatic mockups")
        self.safe_live_test.toggled.connect(self.update_live_controls)
        self.demo_mode = QCheckBox()
        self.demo_mode.setChecked(True)
        self.demo_mode.toggled.connect(self.update_live_controls)

        form.addRow("City", self.city)
        form.addRow("State/region", self.state_region)
        form.addRow("Business category", self.category)
        form.addRow("Why this category", self.category_reason)
        form.addRow("Target ZIP", self.target_zip)
        form.addRow("Target miles", self.radius_miles)
        form.addRow("Maximum results", self.max_results)
        form.addRow("Rich-detail breadth", self.google_data_depth)
        form.addRow("Estimated Google calls", self.api_estimate)
        form.addRow("Minimum review count", self.min_reviews)
        form.addRow("Minimum Google rating", self.min_rating)
        form.addRow("Include no website", self.include_no_website)
        form.addRow("Include website revenue leaks", self.include_weak_website)
        form.addRow("Include lower collected result position", self.include_low_rank)
        form.addRow("Include 0-20 review opportunities", self.include_review_growth)
        form.addRow("Targeting filters", QLabel("The four Include controls are not active in this release; all eligible results are considered."))
        form.addRow("Run PageSpeed checks", self.pagespeed)
        form.addRow("Run rendered browser audit", self.rendered)
        form.addRow("Generate screenshots", self.screenshots)
        form.addRow("Generate mockups for top N", self.top_mockups)
        form.addRow("Search name", self.output_name)
        form.addRow("Safe Live Test", self.safe_live_test)
        form.addRow("Demo mode", self.demo_mode)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        run = QPushButton("Run Search")
        cancel = QPushButton("Cancel")
        run.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(run)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.update_category_reason()
        self.update_live_controls()

    def update_category_reason(self) -> None:
        self.category_reason.setText(opportunity_reason(category_from_label(self.category.currentText().strip())))

    def update_live_controls(self) -> None:
        live = not self.demo_mode.isChecked()
        self.pagespeed.setEnabled(live)
        self.rendered.setEnabled(live and self.rendered_available)
        if not self.rendered.isEnabled():
            self.rendered.setChecked(False)
        self.screenshots.setEnabled(live and self.rendered_available and self.rendered.isChecked())
        if not self.screenshots.isEnabled():
            self.screenshots.setChecked(False)
        self.google_data_depth.setEnabled(live and not self.safe_live_test.isChecked())
        self.update_api_estimate()

    def update_api_estimate(self) -> None:
        if self.demo_mode.isChecked():
            self.api_estimate.setText("0 calls — Demo Mode uses local fixtures.")
            return
        criteria = SearchCriteria(
            city=self.city.text().strip(),
            state_region=self.state_region.text().strip(),
            niche=category_from_label(self.category.currentText().strip()),
            max_results=self.max_results.value(),
            safe_live_test=self.safe_live_test.isChecked(),
            google_data_depth=self.google_data_depth.currentText(),
        )
        discovery, details, total = estimate_places_api_calls(criteria)
        suffix = "Safe Live Test enriches all five." if criteria.safe_live_test else "Actual calls can be lower when fewer results are returned."
        self.api_estimate.setText(f"Up to {total}: {discovery} Text Search + {details} Place Details. {suffix}")

    def criteria(self) -> SearchCriteria:
        return SearchCriteria(
            city=self.city.text().strip(),
            state_region=self.state_region.text().strip(),
            niche=category_from_label(self.category.currentText().strip()),
            target_zip_code=self.target_zip.text().strip(),
            target_radius_miles=self.radius_miles.value(),
            radius_meters=round(self.radius_miles.value() * 1609.344),
            max_results=self.max_results.value(),
            min_review_count=self.min_reviews.value(),
            min_rating=self.min_rating.value(),
            include_no_website=self.include_no_website.isChecked(),
            include_weak_websites=self.include_weak_website.isChecked(),
            include_low_search_position=self.include_low_rank.isChecked(),
            include_review_growth_opportunities=self.include_review_growth.isChecked(),
            run_pagespeed=self.pagespeed.isChecked(),
            run_rendered_audit=self.rendered.isChecked(),
            generate_screenshots=self.screenshots.isChecked(),
            top_mockups=self.top_mockups.value(),
            output_name=self.output_name.text().strip() or "lead-search",
            demo_mode=self.demo_mode.isChecked(),
            safe_live_test=self.safe_live_test.isChecked() and not self.demo_mode.isChecked(),
            google_data_depth=self.google_data_depth.currentText(),
        )
