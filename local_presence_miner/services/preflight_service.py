from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from local_presence_miner.config import AppConfig
from local_presence_miner.services.rendered_auditor import rendered_audit_availability


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    label: str
    status: str  # pass | warning | fail
    detail: str


@dataclass(frozen=True)
class PreflightResult:
    checks: tuple[PreflightCheck, ...]

    @property
    def blocking(self) -> tuple[PreflightCheck, ...]:
        return tuple(item for item in self.checks if item.status == "fail")

    @property
    def ready(self) -> bool:
        return not self.blocking


class PreflightService:
    def run(self, config: AppConfig, *, live_search: bool = True, rendered_requested: bool = False, pagespeed_requested: bool = False) -> PreflightResult:
        checks: list[PreflightCheck] = []
        checks.append(self._write_check("database", "Database folder", config.database_path.parent))
        checks.append(self._write_check("output", "Output folder", config.output_dir))
        if live_search:
            checks.append(
                PreflightCheck(
                    "google_places",
                    "Google Places",
                    "pass" if bool(config.google_maps_api_key.strip()) else "fail",
                    "API key configured" if config.google_maps_api_key.strip() else "Google Places API key is missing",
                )
            )
        if pagespeed_requested:
            checks.append(
                PreflightCheck(
                    "pagespeed",
                    "PageSpeed",
                    "pass" if bool(config.pagespeed_api_key.strip()) else "warning",
                    "API key configured" if config.pagespeed_api_key.strip() else "No PageSpeed key; disable PageSpeed or add a key",
                )
            )
        if rendered_requested:
            available, reason = rendered_audit_availability()
            checks.append(PreflightCheck("rendered", "Rendered Edge audit", "pass" if available else "fail", reason))
        sender = config.sender
        missing_sender = [
            name for name, value in (("name", sender.name), ("reply email", sender.reply_email), ("postal address", sender.postal_address)) if not value.strip()
        ]
        checks.append(
            PreflightCheck(
                "sender",
                "Sender identity",
                "warning" if missing_sender else "pass",
                "Missing: " + ", ".join(missing_sender) if missing_sender else "Core sender identity is configured",
            )
        )
        concurrency = max(1, int(config.audit_concurrency))
        checks.append(
            PreflightCheck(
                "concurrency",
                "Audit concurrency",
                "pass" if concurrency <= 4 else "warning",
                f"Configured at {concurrency}; 1-4 is the supported conservative range",
            )
        )
        return PreflightResult(tuple(checks))

    @staticmethod
    def _write_check(key: str, label: str, path: Path) -> PreflightCheck:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".lpm-preflight-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return PreflightCheck(key, label, "pass", f"Writable: {path}")
        except OSError as exc:
            return PreflightCheck(key, label, "fail", f"Not writable: {path} ({exc.__class__.__name__})")
