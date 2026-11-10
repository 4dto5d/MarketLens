from __future__ import annotations

import json
import logging
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner import __version__
from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import list_leads
from local_presence_miner.database.schema import LeadSearch
from local_presence_miner.services.comparison_service import ComparisonService
from local_presence_miner.services.export_service import ExportService
from local_presence_miner.services.lead_package_service import LeadPackageService
from local_presence_miner.services.mockup_service import MockupService
from local_presence_miner.services.proposal_service import ProposalService
from local_presence_miner.services.report_service import ReportService
from local_presence_miner.services.search_market_service import SearchMarketService
from local_presence_miner.services.search_workflow import SearchWorkflow
from local_presence_miner.services.static_site_service import StaticSiteService
from local_presence_miner.ui.components import InfoBanner, PageHeader, SectionHeader, Toast
from local_presence_miner.ui.components.action_toolbar import action_button
from local_presence_miner.ui.dialogs.lead_detail_dialog import LeadDetailDialog
from local_presence_miner.ui.dialogs.new_search_dialog import NewSearchDialog
from local_presence_miner.ui.dialogs.opportunity_workflow_dialog import OpportunityWorkflowDialog
from local_presence_miner.ui.dialogs.settings_dialog import SettingsDialog
from local_presence_miner.ui.icons import app_icon
from local_presence_miner.ui.theme import load_stylesheet
from local_presence_miner.ui.widgets.activity_log_widget import ActivityLogWidget
from local_presence_miner.ui.widgets.dashboard_widget import DashboardWidget
from local_presence_miner.ui.widgets.industry_intelligence_widget import IndustryIntelligenceWidget
from local_presence_miner.ui.widgets.leads_table import LeadsTableWidget
from local_presence_miner.ui.widgets.outreach_widget import OutreachWidget
from local_presence_miner.ui.widgets.pipeline_widget import PipelineWidget
from local_presence_miner.ui.widgets.pricing_widget import PricingWidget
from local_presence_miner.ui.widgets.prompt_paste_widget import PromptPasteWidget
from local_presence_miner.ui.widgets.review_queue_widget import ReviewQueueWidget
from local_presence_miner.ui.widgets.run_history_widget import RunHistoryWidget
from local_presence_miner.ui.widgets.search_market_widget import SearchMarketWidget
from local_presence_miner.ui.widgets.setup_wizard_widget import SetupWizardWidget
from local_presence_miner.ui.workers import FunctionWorker

log = logging.getLogger(__name__)

PAGE_META = {
    "First-Run Setup": ("Get Started", "Configure the essentials and understand what MarketLens Local keeps manual."),
    "Dashboard": ("Dashboard", "See what needs attention today and move directly into the next useful action."),
    "Lead Searches": ("Lead Searches", "Find local businesses with observable online opportunity gaps."),
    "Run History": ("Run History", "Review completed market searches and their collection context."),
    "Search Market": ("Search Market", "Inspect deterministic multi-query coverage and repeated search capture without changing sales state."),
    "Leads": ("Leads", "Find, filter, and prioritize local businesses with measurable online opportunities."),
    "Review Queue": ("Review Queue", "Qualify new opportunities quickly without losing verification context."),
    "Pipeline": ("Pipeline", "Keep follow-ups and sales state clear, due-first, and actionable."),
    "Outreach": ("Outreach", "Review grounded drafts, satisfy verification gates, and approve text manually."),
    "Pricing Intelligence": ("Pricing Intelligence", "Keep Project Value separate from the ask supported by your real proof and history."),
    "Reports": ("Reports", "Create and manage operator reports, customer proposals, comparisons, concepts, and exports."),
    "Industry Intelligence": ("Industry Intelligence", "Understand patterns in your collected sample without presenting them as market-wide facts."),
    "Prompt Paste": ("Prompt Paste", "Summarize manually pasted ChatGPT output locally without connecting an API."),
    "Suppression List": ("Suppression List", "Protect opt-outs and businesses that must not be contacted."),
    "Settings": ("Settings", "Manage local paths, API configuration, audit behavior, and truthful sender identity."),
    "Activity Log": ("Activity Log", "Review durable operator and system events."),
}


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self.config = config
        self.session_factory = session_factory
        self.thread_pool = QThreadPool.globalInstance()
        self.setWindowTitle(f"MarketLens Local {__version__}")
        self.resize(1366, 768)
        self.setMinimumSize(1100, 680)
        self.setStyleSheet(load_stylesheet())
        central = QWidget()
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.build_sidebar())
        content = QWidget()
        content.setObjectName("MainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.page_header = PageHeader()
        content_layout.addWidget(self.page_header)
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        shell.addWidget(content, 1)
        self.pages: dict[str, QWidget] = {}
        self.nav_rows: list[str] = []
        self.build_pages()
        self.nav.currentRowChanged.connect(self.change_page)
        self.navigate("Dashboard")

    def build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(0)
        identity = QLabel("MarketLens Local")
        identity.setProperty("role", "brand")
        version = QLabel(f"v{__version__} · Business opportunity workstation")
        version.setProperty("role", "version")
        version.setWordWrap(True)
        layout.addWidget(identity)
        layout.addWidget(version)
        layout.addSpacing(16)
        self.nav = QListWidget()
        self.nav.setObjectName("SidebarNav")
        self.nav.setIconSize(QSize(17, 17))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.nav, 1)
        privacy = QLabel("LOCAL-FIRST\nNo automatic outreach")
        privacy.setProperty("role", "version")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(privacy)
        return sidebar

    def build_pages(self) -> None:
        self.setup = SetupWizardWidget(self.config)
        self.dashboard = DashboardWidget(self.session_factory)
        self.dashboard.lead_open_requested.connect(self.open_lead)
        self.dashboard.new_search_requested.connect(self.open_new_search)
        self.dashboard.view_all_requested.connect(lambda: self.navigate("Leads"))
        self.pipeline = PipelineWidget(self.session_factory)
        self.pipeline.lead_open_requested.connect(self.open_lead)
        self.leads = LeadsTableWidget(self.session_factory)
        self.leads.lead_open_requested.connect(self.open_lead)
        self.leads.new_search_requested.connect(self.open_new_search)
        self.review = ReviewQueueWidget(self.session_factory)
        self.review.lead_open_requested.connect(self.open_lead)
        self.outreach = OutreachWidget(self.session_factory, self.config)
        self.outreach.lead_open_requested.connect(self.open_lead)
        self.prompt_paste = PromptPasteWidget()
        self.pricing = PricingWidget(self.session_factory)
        self.industry_intelligence = IndustryIntelligenceWidget(self.session_factory)
        self.run_history = RunHistoryWidget(self.session_factory)
        self.search_market = SearchMarketWidget(self.session_factory)
        self.search_market.run_requested.connect(self.start_search_market)
        self.activity = ActivityLogWidget(self.session_factory)
        page_groups = [
            (
                "WORK",
                [
                    ("Dashboard", self.dashboard, "info"),
                    ("Lead Searches", self.search_page(), "search"),
                    ("Leads", self.leads, "open"),
                    ("Review Queue", self.review, "warning"),
                    ("Pipeline", self.pipeline, "next"),
                    ("Run History", self.run_history, "refresh"),
                ],
            ),
            (
                "SALES",
                [
                    ("Outreach", self.outreach, "report"),
                    ("Pricing Intelligence", self.pricing, "info"),
                    ("Reports", self.reports_page(), "report"),
                ],
            ),
            ("INTELLIGENCE", [
                ("Industry Intelligence", self.industry_intelligence, "info"),
                ("Search Market", self.search_market, "search"),
                ("Prompt Paste", self.prompt_paste, "copy"),
            ]),
            (
                "SYSTEM",
                [
                    ("First-Run Setup", self.setup, "success"),
                    ("Suppression List", self.suppression_page(), "error"),
                    ("Settings", self.settings_page(), "settings"),
                    ("Activity Log", self.activity, "refresh"),
                ],
            ),
        ]
        for group, entries in page_groups:
            group_item = QListWidgetItem(group)
            group_item.setFlags(Qt.ItemFlag.NoItemFlags)
            group_item.setData(257, "group")
            self.nav.addItem(group_item)
            for name, widget, icon in entries:
                self.pages[name] = widget
                self.stack.addWidget(widget)
                item = QListWidgetItem(app_icon(self, icon), name)
                item.setToolTip(PAGE_META[name][1])
                item.setData(256, name)
                self.nav.addItem(item)

    def change_page(self, row: int) -> None:
        item = self.nav.item(row)
        name = item.data(256) if item else None
        if not name:
            return
        self.stack.setCurrentWidget(self.pages[name])
        title, description = PAGE_META[name]
        self.page_header.set_page(title, description)
        self.configure_page_actions(name)
        widget = self.pages[name]
        if hasattr(widget, "refresh"):
            widget.refresh()

    def navigate(self, name: str) -> None:
        for row in range(self.nav.count()):
            if self.nav.item(row).data(256) == name:
                self.nav.setCurrentRow(row)
                return

    def configure_page_actions(self, name: str) -> None:
        self.page_header.clear_actions()
        if name in {"Dashboard", "Lead Searches", "Leads"}:
            self.page_header.add_action(action_button("New Search", self.open_new_search, role="primary", icon="search"))
            self.page_header.add_action(action_button("Add Warm Opportunity", self.add_warm_opportunity, role="secondary", icon="add"))
        elif name == "Review Queue":
            self.page_header.add_action(action_button("Next Lead", self.review.next_lead, role="primary", icon="next"))
        elif name == "Pricing Intelligence":
            self.page_header.add_action(action_button("Record Offer", self.pricing.add_offer, role="primary", icon="add"))
        elif name == "Reports":
            self.page_header.add_action(action_button("Open Reports Folder", self.open_output_folder, role="primary", icon="folder"))
        elif name == "Settings":
            self.page_header.add_action(action_button("Open Settings", self.open_settings, role="primary", icon="settings"))

    def search_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(14)
        key_title = "Demo Mode is ready" if not self.config.google_maps_api_key else "Demo and live Google modes are ready"
        key_message = "Start offline with no key or internet." if not self.config.google_maps_api_key else "A Google Maps key is configured for live searches."
        layout.addWidget(InfoBanner(key_title, key_message, "success"))
        start = QFrame()
        start.setProperty("surface", "card")
        start_layout = QVBoxLayout(start)
        start_layout.setContentsMargins(18, 16, 18, 16)
        start_layout.addWidget(SectionHeader("Start a market search", "Choose a city, niche, lead quality, and optional audit depth."))
        start_layout.addWidget(action_button("New Search", self.open_new_search, role="primary", icon="search"), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(start)
        self.search_status_banner = InfoBanner("Ready", "No search is currently running.")
        layout.addWidget(self.search_status_banner)
        layout.addStretch(1)
        return widget

    def reports_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(14)
        layout.addWidget(
            InfoBanner(
                "Human review required",
                "Customer-facing reports and proposals must be checked before sharing. Internal outputs can contain operator-only context.",
                "warning",
            )
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Report audience"))
        self.report_kind = QComboBox()
        self.report_kind.addItems(["owner_short", "owner_full", "internal"])
        controls.addWidget(self.report_kind)
        controls.addStretch(1)
        layout.addLayout(controls)
        grid = QGridLayout()
        grid.setSpacing(12)
        actions = [
            ("Business Opportunity Reports", "Generate the selected report audience for all leads.", self.generate_all_reports),
            ("Website Concepts", "Generate mockups for the highest-priority leads.", self.generate_top_mockups),
            ("Competitor Comparisons", "Create evidence-grounded local comparisons and prompt files.", self.generate_all_comparisons),
            ("Proposal Drafts", "Create unpriced customer proposal drafts for operator selection.", self.generate_all_proposals),
            ("Static Site Concepts", "Export paid-style concept folders that still require production completion.", self.export_top_sites),
            ("Prospect Lead Packages", "Package shareable prospect assets without private seller pricing history.", self.export_top_packages),
            ("Leads CSV", "Export the reviewed lead table for private analysis.", self.export_csv),
        ]
        for index, (title, description, callback) in enumerate(actions):
            card = QFrame()
            card.setProperty("surface", "card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 13, 15, 13)
            card_layout.addWidget(SectionHeader(title, description))
            card_layout.addWidget(action_button("Generate", callback, role="secondary", icon="report"), alignment=Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)
        self.report_status = QLabel("No output generated during this session.")
        self.report_status.setWordWrap(True)
        self.report_status.setProperty("role", "sectionDescription")
        layout.addWidget(self.report_status)
        layout.addStretch(1)
        return widget

    def suppression_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(14)
        layout.addWidget(
            InfoBanner(
                "Suppression is a safety control",
                "Suppressed businesses cannot have outreach approved. Add opt-outs, phone numbers, domains, URLs, or names that must not be contacted.",
                "danger",
            )
        )
        row = QHBoxLayout()
        self.suppression_value = QLineEdit()
        self.suppression_value.setPlaceholderText("Phone, domain, URL, or business name")
        row.addWidget(self.suppression_value, 1)
        row.addWidget(action_button("Add Suppression Entry", self.add_suppression, role="danger"))
        layout.addLayout(row)
        self.suppression_status = QLabel("No suppression change made during this session.")
        self.suppression_status.setProperty("role", "sectionDescription")
        layout.addWidget(self.suppression_status)
        layout.addStretch(1)
        return widget

    def settings_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(14)
        api = QHBoxLayout()
        google_message = "Configured" if self.config.google_maps_api_key else "Not configured; Demo Mode still works."
        google_tone = "success" if self.config.google_maps_api_key else "info"
        api.addWidget(InfoBanner("GOOGLE MAPS API", google_message, google_tone), 1)
        pagespeed_message = "Configured" if self.config.pagespeed_api_key else "Not configured; rendered/raw auditing still works when enabled."
        pagespeed_tone = "success" if self.config.pagespeed_api_key else "info"
        api.addWidget(InfoBanner("PAGESPEED", pagespeed_message, pagespeed_tone), 1)
        layout.addLayout(api)
        paths = QFrame()
        paths.setProperty("surface", "card")
        paths_layout = QVBoxLayout(paths)
        paths_layout.addWidget(SectionHeader("Local Data", "Runtime data remains on this Windows account unless you explicitly export it."))
        paths_layout.addWidget(QLabel(f"<b>Database</b><br>{self.config.database_path}<br><br><b>Outputs</b><br>{self.config.output_dir}"))
        layout.addWidget(paths)
        actions = QHBoxLayout()
        actions.addWidget(action_button("Open Settings", self.open_settings, role="primary", icon="settings"))
        actions.addWidget(action_button("Open Logs Folder", self.open_logs_folder, role="secondary", icon="folder"))
        actions.addWidget(action_button("Export Redacted Diagnostics", self.export_diagnostics, role="secondary", icon="report"))
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return widget

    def open_output_folder(self) -> None:
        webbrowser.open(self.config.output_dir.resolve().as_uri())

    def open_logs_folder(self) -> None:
        webbrowser.open(self.config.log_path.parent.resolve().as_uri())

    def open_new_search(self) -> None:
        dialog = NewSearchDialog(self.config, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        criteria = dialog.criteria()
        if SearchWorkflow.is_running(self.session_factory):
            QMessageBox.information(
                self,
                "Search already running",
                "One search is already running for this database. Wait for it to finish before starting another.",
            )
            return
        worker = FunctionWorker(SearchWorkflow(self.config, self.session_factory).run, criteria)
        worker.signals.started.connect(
            lambda: self.search_status_banner.set_content("Search running", "Searching and auditing in the background. You can continue using the app.")
        )
        worker.signals.finished.connect(self.search_finished)
        worker.signals.failed.connect(self.search_failed)
        self.thread_pool.start(worker)
        self.navigate("Lead Searches")

    def start_search_market(self, lead_id: int, demo_mode: bool, query_limit: int) -> None:
        if SearchWorkflow.is_running(self.session_factory):
            self.search_market.run_failed("Another search owns the database lease; wait before starting Search Market.")
            return
        worker = FunctionWorker(
            SearchMarketService(self.config, self.session_factory).run_for_lead,
            lead_id, demo_mode=demo_mode, query_limit=query_limit,
        )
        worker.signals.finished.connect(self._search_market_finished)
        worker.signals.failed.connect(self._search_market_failed)
        self.thread_pool.start(worker)

    def _search_market_finished(self, result: object) -> None:
        if isinstance(result, int):
            self.search_market.run_finished(result)
            Toast.show_message(self, f"Search Market run {result} finished; review its query evidence.")
        else:
            self.search_market.run_failed("Search Market returned no run identity; review the local log.")

    def _search_market_failed(self, trace: str) -> None:
        log.error("Search Market failed\n%s", trace)
        self.search_market.run_failed("Search Market stopped; review the local log. Completed query probes remain preserved.")
        QMessageBox.critical(self, "Search Market stopped", "The run stopped; completed query evidence remains preserved.")

    def search_finished(self, result: object) -> None:
        search_id = result if isinstance(result, int) else None
        with self.session_factory() as session:
            search = session.get(LeadSearch, search_id) if search_id is not None else None
        if search is None:
            message = f"Search ID {result} finished, but its run record could not be loaded."
            tone = "warning"
        else:
            message = (
                f"Search ID {search.id}: {search.lifecycle_state}. "
                f"{search.succeeded_count} succeeded, {search.failed_count} failed, "
                f"{search.skipped_count} skipped; {search.new_count} new and "
                f"{search.rediscovered_count} rediscovered."
            )
            tone = "warning" if search.lifecycle_state != "Completed" else "success"
        self.search_status_banner.set_content("Search finished", message)
        self.search_status_banner.setProperty("bannerTone", tone)
        self.refresh_pages()
        Toast.show_message(self, message)

    def search_failed(self, trace: str) -> None:
        log.error("Search failed\n%s", trace)
        if "SearchAlreadyRunningError" in trace:
            message = "A search is already running for this database; no second run was started."
        else:
            message = (
                "The run stopped. Any successfully checkpointed leads remain available, and the Run History records "
                "whether the outcome was Failed or Partial. Details were written to the local log."
            )
        self.search_status_banner.set_content("Search stopped", message)
        self.search_status_banner.setProperty("bannerTone", "danger")
        QMessageBox.critical(self, "Search stopped", message)

    def open_lead(self, lead_id: int) -> None:
        LeadDetailDialog(self.config, self.session_factory, lead_id, self).exec()
        self.refresh_pages()

    def add_warm_opportunity(self) -> None:
        dialog = OpportunityWorkflowDialog(self.session_factory, parent=self)
        dialog.exec()
        if dialog.lead_id is not None:
            workspace = LeadDetailDialog(self.config, self.session_factory, dialog.lead_id, self)
            workspace.open_workflow_destination(dialog.destination)
            workspace.exec()
        self.refresh_pages()

    def generate_all_reports(self) -> None:
        with self.session_factory() as session:
            service = ReportService(self.config)
            paths = [service.generate_report(session, lead, self.report_kind.currentText()) for lead in list_leads(session)]
        self.show_generated(paths, "reports")

    def generate_top_mockups(self) -> None:
        with self.session_factory() as session:
            paths = [MockupService(self.config).generate_mockup(lead) for lead in list_leads(session)[:5]]
        self.show_generated(paths, "mockups")

    def generate_all_comparisons(self) -> None:
        with self.session_factory() as session:
            paths = [ComparisonService(self.config).generate_comparison(session, lead, ai_mode="prompt") for lead in list_leads(session)]
        self.show_generated(paths, "comparisons")

    def generate_all_proposals(self) -> None:
        with self.session_factory() as session:
            paths = [ProposalService(self.config).generate_proposal(session, lead) for lead in list_leads(session)]
        self.show_generated(paths, "proposal drafts")

    def export_top_sites(self) -> None:
        with self.session_factory() as session:
            paths = [StaticSiteService(self.config).export_site(lead, session=session) for lead in list_leads(session)[:5]]
        self.show_generated(paths, "site concepts")

    def export_top_packages(self) -> None:
        with self.session_factory() as session:
            paths = [LeadPackageService(self.config).export_package(session, lead, ai_mode="prompt") for lead in list_leads(session)[:5]]
        self.show_generated(paths, "lead packages")

    def export_csv(self) -> None:
        with self.session_factory() as session:
            path = ExportService().export_leads_csv(session, Path(self.config.output_dir) / "exports" / "leads.csv")
        self.show_generated([path], "CSV export")

    def show_generated(self, paths: list[Path], label: str) -> None:
        self.report_status.setText(f"Generated {len(paths)} {label}." if paths else "No leads were available.")
        if paths:
            self.report_status.setToolTip("\n".join(str(path) for path in paths))
            Toast.show_message(self, f"Generated {len(paths)} {label}.")

    def add_suppression(self) -> None:
        value = self.suppression_value.text().strip()
        if not value:
            return
        with self.session_factory() as session:
            from local_presence_miner.database.repositories import add_suppression

            add_suppression(session, value, "manual suppression entry")
            session.commit()
        self.suppression_status.setText(f"Added suppression entry: {value}")
        self.suppression_value.clear()
        self.refresh_pages()
        Toast.show_message(self, "Suppression entry added.", "warning")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.config = AppConfig.load()
            self.setup.config = self.config
            self.setup.refresh()
            Toast.show_message(self, "Settings saved and active.")

    def export_diagnostics(self) -> None:
        folder = self.config.output_dir / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"LocalPresenceMiner-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        summary = {
            "app_version": __version__,
            "database_path": str(self.config.database_path),
            "output_dir": str(self.config.output_dir),
            "google_key_present": bool(self.config.google_maps_api_key),
            "pagespeed_key_present": bool(self.config.pagespeed_api_key),
            "audit_concurrency": self.config.audit_concurrency,
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps(summary, indent=2))
            if self.config.log_path.exists():
                archive.write(self.config.log_path, "app.log")
        Toast.show_message(self, "Redacted diagnostics exported.")

    def refresh_pages(self) -> None:
        refreshable = [
            self.setup,
            self.dashboard,
            self.pipeline,
            self.leads,
            self.review,
            self.outreach,
            self.pricing,
            self.industry_intelligence,
            self.run_history,
            self.activity,
        ]
        for widget in refreshable:
            widget.refresh()
