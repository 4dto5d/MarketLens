from __future__ import annotations

from local_presence_miner.services.website_auditor import has_outdated_copyright, normalize_url


def test_url_normalization() -> None:
    assert normalize_url("example.com") == "https://example.com"


def test_outdated_copyright_detection() -> None:
    assert has_outdated_copyright("Copyright 2020")
