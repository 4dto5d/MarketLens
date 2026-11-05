"""Offline CSV provenance, corruption and local rank contract checks."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from local_presence_miner.domain.seo_intelligence import analyze_seo
from local_presence_miner.services.semrush_import import import_semrush_csv

NOW = datetime(2026, 10, 2, 18, tzinfo=UTC)
CSV = "Keyword,Search Volume,Keyword Difficulty,Position\nemergency plumber Austin,20,40,1\n"


def arguments():
    return {
        "subject": {"place_id": "target", "website": "https://target.example", "geography": "Austin TX", "canonical_niche_id": "plumber"},
        "metadata": {"observed_at": NOW.isoformat(), "provider": "semrush", "report": "offline keyword report", "database": "us",
                     "geography": "US", "geo_resolution": "country", "status": "complete", "reference": "file:semrush-20261002.csv", "demo": False},
        "local_ranks": {"emergency plumber Austin": {"geography": "Austin TX", "observed_at": NOW.isoformat(), "reference": "manual-serp:Austin:20261002",
                         "service": "emergency plumbing", "service_state": "confirmed", "service_refs": ["owner:services"], "intent": "local_commercial",
                         "intent_basis": "Local purchase intent", "organic_rank": 12, "organic_window": 20, "organic_complete": True,
                         "maps_rank": None, "maps_window": 3, "maps_complete": False, "page_url": "https://target.example/emergency", "refs": []}},
    }


def test_offline_csv_keeps_country_volume_and_does_not_relabel_export_position():
    args = arguments()
    before = deepcopy(args)
    imported = import_semrush_csv(CSV, **args)
    q = imported["queries"][0]
    assert q["organic_rank"] == 12
    assert q["volume"] == 20
    assert q["volume_geo_resolution"] == "country"
    assert q["volume_geography"] == "US"
    assert q["volume_reference"] == "file:semrush-20261002.csv"
    assert imported["source"]["geo_resolution"] == "local"
    assert imported["source"]["geography"] == "Austin TX"
    assert "manual-serp:Austin:20261002" in q["refs"]
    assert args == before
    report = analyze_seo(imported, now=NOW)
    assert report["opportunities"][0]["decision"] == "insufficient_evidence"
    assert any("not live Semrush" in item for item in report["limitations"])


@pytest.mark.parametrize("volume,expected", [("", None), ("N/A", None), ("0", 0), ('"1,200"', 1200), ("12.5", 12.5)])
def test_csv_zero_unknown_and_numeric_provenance(volume, expected):
    imported = import_semrush_csv(f"Keyword,Volume\nemergency plumber Austin,{volume}\n", **arguments())
    assert imported["queries"][0]["volume"] == expected


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "1,2", "20k", "=SUM(1)"])
def test_csv_corrupt_volume_not_coerced_to_zero(value):
    with pytest.raises(ValueError):
        import_semrush_csv(f'Keyword,Volume\nemergency plumber Austin,"{value}"\n', **arguments())


@pytest.mark.parametrize("csv_text", ["", "Keyword,Volume\n", "Keyword,Volume,Volume\nemergency plumber Austin,10,20\n",
                                    "Keyword,Search Volume,Volume\nemergency plumber Austin,10,20\n", "Not Keyword,Volume\nfoo,10\n",
                                    "Keyword,Volume\nemergency plumber Austin,20,unexpected\n",
                                    "Keyword,Volume\nemergency plumber Austin,20\nemergency plumber Austin,90\n"])
def test_malformed_empty_ambiguous_duplicate_or_conflicting_csv_rejected(csv_text):
    with pytest.raises(ValueError):
        import_semrush_csv(csv_text, **arguments())


@pytest.mark.parametrize("local_change", [{"geography": "Dallas TX"}, {"observed_at": (NOW - timedelta(days=1)).isoformat()},
                                         {"reference": ""}, {"organic_window": None, "maps_window": None},
                                         {"organic_complete": "true"}, {"organic_rank": True}, {"action": "force_sale"}])
def test_local_observation_requires_matching_scope_timestamp_and_structure(local_change):
    args = arguments()
    args["local_ranks"]["emergency plumber Austin"].update(local_change)
    with pytest.raises(ValueError):
        import_semrush_csv(CSV, **args)


def test_missing_local_ranks_and_unmatched_extra_ranks_rejected():
    args = arguments()
    args["local_ranks"] = {}
    with pytest.raises(ValueError):
        import_semrush_csv(CSV, **args)
    args = arguments()
    args["local_ranks"]["other query"] = deepcopy(args["local_ranks"]["emergency plumber Austin"])
    with pytest.raises(ValueError):
        import_semrush_csv(CSV, **args)


@pytest.mark.parametrize("metadata_change", [{"geo_resolution": "local"}, {"provider": "invented_live_api"}, {"reference": ""},
                                            {"geography": ""}, {"observed_at": "2026-10-02"}, {"demo": "false"}])
def test_metadata_must_be_explicit_and_well_formed(metadata_change):
    args = arguments()
    args["metadata"].update(metadata_change)
    with pytest.raises(ValueError):
        import_semrush_csv(CSV, **args)


def test_bom_tab_export_and_nested_metadata_supported_without_inventing_report():
    args = arguments()
    original_source = {key: value for key, value in args["metadata"].items() if key != "observed_at"}
    args["metadata"] = {"observed_at": NOW.isoformat(), "source": original_source}
    imported = import_semrush_csv("\ufeffKeyword\tVolume\tKD\nemergency plumber Austin\t20\t40\n", **args)
    assert imported["source"]["report"] == "offline keyword report"


def test_future_import_is_recordable_but_not_recommendable():
    args = arguments()
    future = (NOW + timedelta(seconds=1)).isoformat()
    args["metadata"]["observed_at"] = future
    args["local_ranks"]["emergency plumber Austin"]["observed_at"] = future
    imported = import_semrush_csv(CSV, **args)
    assert analyze_seo(imported, now=NOW)["state"] == "future"
