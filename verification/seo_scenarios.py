"""Synthetic A–L examples and causal counterfactuals; no live sources or ROI.

Run from the chosen tree: python verification/seo_scenarios.py
For the exact parent, invoke this script with --parent-tree /path/to/baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path


def fixtures(now: datetime) -> dict:
    data = {
        "schema_version": 1, "subject": {"place_id": "synthetic-case", "website": "https://prospect.example",
                                         "geography": "Austin TX", "canonical_niche_id": "plumber"},
        "observed_at": now.isoformat(),
        "source": {"provider": "manual_serp", "report": "synthetic-acceptance-example", "database": "manual", "geography": "Austin TX",
                   "geo_resolution": "local", "status": "complete", "reference": "synthetic:example", "demo": False},
        "queries": [{"query": "emergency plumber Austin TX", "service": "emergency plumbing", "service_state": "confirmed",
                     "service_refs": ["owner:confirmed-service:fixture"], "intent": "local_commercial", "intent_basis": "Synthetic service-request SERP",
                     "volume": 10, "difficulty": 20, "organic_rank": 12, "maps_rank": 2,
                     "organic_window": 50, "maps_window": 20, "organic_complete": True, "maps_complete": True,
                     "page_url": "https://prospect.example/emergency", "serp_features": [], "refs": ["synthetic:query:fixture"],
                     "competitors": [{"url": "https://other-local.example/emergency", "channel": "organic", "position": 3,
                                      "kind": "local_business", "authority": 20, "referring_domains": 10}]}],
        "pages": [{"url": "https://prospect.example/emergency", "title": "Home", "h1": ["Welcome"], "meta_description": "",
                   "canonical": "", "robots": [], "status_code": 200, "indexability": "allowed", "word_count": 450,
                   "internal_links": [], "schema_types": ["Service"], "schema_errors": [], "services": ["emergency plumbing"],
                   "service_refs": ["https://prospect.example/emergency#Service"]}],
    }
    names = {
        "A": "Strong site, organic #2 but weak Maps",
        "B": "Weak service-page sample but dominant measured organic and Maps",
        "C": "Large informational volume",
        "D": "Low-volume high-intent local service",
        "E": "Strong opportunity, entrenched competitors",
        "F": "Organic #12, weak existing targeting",
        "G": "Validated local demand but no sampled service page",
        "H": "Indexing restriction on otherwise relevant page",
        "I": "Low public reputation before traffic growth",
        "J": "Apparently generic site, already dominant search",
        "K": "Same service, different city and entrenched competitive set",
        "L": "Same visibility as F but technically blocked, not targeting weak",
    }
    cases = {key: {"name": name, "payload": deepcopy(data), "website_checks": {}, "rating": 4.8} for key, name in names.items()}
    cases["A"]["payload"]["queries"][0].update(organic_rank=2, maps_rank=12)
    cases["A"]["payload"]["pages"][0].update(title="Emergency Plumbing Austin", h1=["Emergency Plumbing"], meta_description="Emergency plumbing service")
    cases["B"]["payload"]["queries"][0].update(organic_rank=1, maps_rank=1)
    cases["B"]["website_checks"] = {"service_pages": False, "sitewide_service_depth": False}
    cases["C"]["payload"]["queries"][0].update(query="how to fix a burst pipe", intent="informational", volume=100000)
    cases["D"]["payload"]["queries"][0]["volume"] = 1
    cases["E"]["payload"]["prospect_authority"] = 10
    cases["E"]["payload"]["queries"][0]["competitors"][0]["authority"] = 90
    cases["G"]["payload"]["pages"] = []
    cases["H"]["payload"]["pages"][0].update(indexability="blocked", robots=["noindex"])
    cases["I"]["rating"] = 2.8
    cases["J"]["payload"]["queries"][0].update(organic_rank=2, maps_rank=2)
    cases["K"]["payload"]["subject"]["geography"] = "Tampa FL"
    cases["K"]["payload"]["source"]["geography"] = "Tampa FL"
    cases["K"]["payload"]["queries"][0]["query"] = "emergency plumber Tampa FL"
    cases["K"]["payload"]["queries"][0]["serp_features"] = ["local_services_ads"]
    cases["K"]["payload"]["queries"][0]["competitors"][0].update(url="https://national.example/emergency", kind="national_brand")
    cases["L"]["payload"]["pages"][0].update(indexability="blocked", robots=["googlebot: noindex"])
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-tree", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.parent_tree or Path(__file__).resolve().parents[1]))
    from local_presence_miner.domain.intervention_assessment import InterventionEvidence, assess_interventions

    now = datetime.now(UTC)
    cases = fixtures(now)
    output = {}
    healthy = {"https": True, "viewport": True, "tap_to_call": True, "contact_form": False, "sitewide_contact_path": True,
               "clear_primary_cta": True, "indexable_sample": True, "service_pages": True, "trust_signals": True}
    for key, case in cases.items():
        evidence = {"website_url": "https://prospect.example", "website_state": "observed", "website_checks": {**healthy, **case["website_checks"]},
                    "website_refs": ("website_audit:synthetic",), "google_current": True, "has_hours": True, "photo_count": 12,
                    "rating": case["rating"], "review_count": 100, "google_refs": ("google_places:synthetic",)}
        if not args.parent_tree:
            from local_presence_miner.domain.seo_intelligence import analyze_seo

            report = analyze_seo(case["payload"], now=now)
            report["snapshot_sha256"] = "synthetic-source-checkpoint-not-live"
            for opportunity in report["opportunities"]:
                opportunity["evidence_refs"].append("seo_snapshot:synthetic:fixture")
            evidence["seo_research"] = report
        assessment = assess_interventions(InterventionEvidence(**evidence))
        output[key] = {"name": case["name"], "evidence": case["payload"], "assessment": assessment.to_dict()}
        if not args.parent_tree:
            output[key]["search_research"] = report
    if not args.parent_tree:
        counterfactuals = {}
        for label in ("remove_local_demand", "remove_service_confirmation", "improve_rank", "strengthen_competitors",
                      "repair_indexability", "change_intent", "repair_reputation"):
            original = "H" if label == "repair_indexability" else "I" if label == "repair_reputation" else "F"
            changed = deepcopy(cases[original])
            query = changed["payload"]["queries"][0]
            if label == "remove_local_demand":
                query["volume"] = None
            elif label == "remove_service_confirmation":
                query.update(service_state="unknown", service_refs=[])
            elif label == "improve_rank":
                query["organic_rank"] = 2
            elif label == "strengthen_competitors":
                changed["payload"]["prospect_authority"] = 10
                query["competitors"][0]["authority"] = 90
            elif label == "repair_indexability":
                changed["payload"]["pages"][0].update(indexability="allowed", robots=[])
            elif label == "change_intent":
                query.update(intent="informational", query="how to fix a burst pipe")
            else:
                changed["rating"] = 4.8
            report = analyze_seo(changed["payload"], now=now)
            report["snapshot_sha256"] = "synthetic-source-checkpoint-not-live"
            for op in report["opportunities"]:
                op["evidence_refs"].append("seo_snapshot:synthetic:counterfactual")
            assessment = assess_interventions(InterventionEvidence(
                website_url="https://prospect.example", website_state="observed", website_checks=healthy,
                website_refs=("website_audit:synthetic",), google_current=True, has_hours=True, photo_count=12,
                rating=changed["rating"], review_count=100, google_refs=("google_places:synthetic",), seo_research=report,
            ))
            counterfactuals[label] = {"original_case": original, "changed_evidence": changed["payload"], "assessment": assessment.to_dict(),
                                      "search_research": report}
        output["counterfactuals"] = counterfactuals
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
