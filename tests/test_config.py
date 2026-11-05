from __future__ import annotations

import json
import os

import pytest

from local_presence_miner.config import DPAPI_PREFIX, AppConfig, save_settings


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI test")
def test_api_keys_round_trip_without_plaintext_on_windows(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LPM_APP_DATA_DIR", str(tmp_path))
    save_settings(
        tmp_path,
        {
            "google_maps_api_key": "google-secret-value",
            "pagespeed_api_key": "pagespeed-secret-value",
        },
    )

    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "google-secret-value" not in raw["google_maps_api_key"]
    assert "pagespeed-secret-value" not in raw["pagespeed_api_key"]
    assert raw["google_maps_api_key"].startswith(DPAPI_PREFIX)

    config = AppConfig.load()
    assert config.google_maps_api_key == "google-secret-value"
    assert config.pagespeed_api_key == "pagespeed-secret-value"
