from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "LocalPresenceMiner"
SECRET_SETTING_KEYS = {"google_maps_api_key", "pagespeed_api_key"}
DPAPI_PREFIX = "dpapi:"


def default_app_data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / f".{APP_NAME}"


@dataclass(frozen=True)
class SenderInfo:
    name: str = ""
    business_name: str = ""
    reply_email: str = ""
    phone: str = ""
    postal_address: str = ""
    opt_out_line: str = "If you do not want more messages from me, reply opt out and I will not contact you again."


@dataclass(frozen=True)
class AppConfig:
    app_data_dir: Path
    database_path: Path
    log_path: Path
    output_dir: Path
    google_maps_api_key: str = ""
    pagespeed_api_key: str = ""
    default_radius_meters: int = 12000
    request_timeout_seconds: int = 12
    request_delay_seconds: float = 0.5
    audit_concurrency: int = 4
    sender: SenderInfo = SenderInfo()

    @classmethod
    def load(cls) -> AppConfig:
        load_dotenv()
        app_data_dir = Path(os.getenv("LPM_APP_DATA_DIR", default_app_data_dir())).expanduser()
        app_data_dir.mkdir(parents=True, exist_ok=True)
        for child in ["logs", "reports", "mockups", "screenshots", "exports"]:
            (app_data_dir / child).mkdir(parents=True, exist_ok=True)

        settings = _load_settings(app_data_dir / "settings.json")
        sender = SenderInfo(
            name=_setting(settings, "sender_name", "LPM_SENDER_NAME"),
            business_name=_setting(settings, "sender_business", "LPM_SENDER_BUSINESS"),
            reply_email=_setting(settings, "reply_email", "LPM_REPLY_EMAIL"),
            phone=_setting(settings, "sender_phone", "LPM_SENDER_PHONE"),
            postal_address=_setting(settings, "postal_address", "LPM_POSTAL_ADDRESS"),
            opt_out_line=_setting(settings, "opt_out_line", "LPM_OPT_OUT_LINE", SenderInfo().opt_out_line),
        )

        return cls(
            app_data_dir=app_data_dir,
            database_path=Path(settings.get("database_path", app_data_dir / "local_presence_miner.sqlite3")),
            log_path=app_data_dir / "logs" / "app.log",
            output_dir=Path(settings.get("output_dir", app_data_dir)),
            google_maps_api_key=_setting(settings, "google_maps_api_key", "GOOGLE_MAPS_API_KEY"),
            pagespeed_api_key=_setting(settings, "pagespeed_api_key", "PAGESPEED_API_KEY"),
            default_radius_meters=int(_setting(settings, "default_radius_meters", "LPM_DEFAULT_RADIUS_METERS", "12000")),
            request_timeout_seconds=int(_setting(settings, "request_timeout_seconds", "LPM_REQUEST_TIMEOUT_SECONDS", "12")),
            request_delay_seconds=float(_setting(settings, "request_delay_seconds", "LPM_REQUEST_DELAY_SECONDS", "0.5")),
            audit_concurrency=int(_setting(settings, "audit_concurrency", "LPM_AUDIT_CONCURRENCY", "4")),
            sender=sender,
        )


def _load_settings(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_settings(app_data_dir: Path, values: dict[str, str]) -> None:
    path = app_data_dir / "settings.json"
    existing = _load_settings(path)
    protected_values = dict(values)
    for key in SECRET_SETTING_KEYS:
        if key in protected_values:
            value = protected_values[key]
            protected_values[key] = protect_secret(value) if value else ""
    existing.update(protected_values)
    safe = {k: v for k, v in existing.items() if v is not None}
    path.write_text(json.dumps(safe, indent=2), encoding="utf-8")


def operator_hourly_rate() -> int:
    """The operator's walk-away hourly rate (settings.json, then LPM_OPERATOR_HOURLY_RATE, default 35).

    Read without creating directories so pricing can be computed anywhere.
    """
    from local_presence_miner.domain.seller_economics import DEFAULT_OPERATOR_RATE, clamp_operator_rate

    app_data_dir = Path(os.getenv("LPM_APP_DATA_DIR", default_app_data_dir())).expanduser()
    settings = _load_settings(app_data_dir / "settings.json")
    return clamp_operator_rate(_setting(settings, "operator_hourly_rate", "LPM_OPERATOR_HOURLY_RATE", str(DEFAULT_OPERATOR_RATE)))


def _setting(settings: dict[str, str], key: str, env_name: str, default: str = "") -> str:
    value = settings.get(key)
    if value not in (None, ""):
        text = str(value)
        return unprotect_secret(text) if key in SECRET_SETTING_KEYS else text
    return os.getenv(env_name, default)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def protect_secret(value: str) -> str:
    if not value or value.startswith(DPAPI_PREFIX):
        return value
    if os.name != "nt":
        return value
    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows could not encrypt the API key.")
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        _local_free(target.pbData)


def unprotect_secret(value: str) -> str:
    if not value.startswith(DPAPI_PREFIX):
        return value
    if os.name != "nt":
        return ""
    encrypted = base64.b64decode(value[len(DPAPI_PREFIX) :])
    buffer = ctypes.create_string_buffer(encrypted)
    source = _DataBlob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows could not decrypt the saved API key for this user.")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        _local_free(target.pbData)


def _local_free(pointer: ctypes.POINTER(ctypes.c_byte)) -> None:
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL
    local_free(ctypes.cast(pointer, wintypes.HLOCAL))
