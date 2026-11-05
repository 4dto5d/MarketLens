"""Selected-service geography cannot borrow unrelated service/intent evidence.

All observations and businesses are synthetic; no live search is involved.
"""

from copy import deepcopy

import pytest
from test_seo_research_integration import business, sample_payload
from test_seo_research_integration import storage as storage_fixture

from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
from local_presence_miner.services.owner_strategy_service import append_owner_strategy
from local_presence_miner.services.sales_evidence_service import SalesEvidenceService
from local_presence_miner.services.seo_research_service import append_research, project_seo_research


@pytest.fixture(name="storage")
def setup_storage(tmp_path):
    return storage_fixture.__wrapped__(tmp_path)


def _owner_market(session, lead, *, separate_areas=False):
    search = lead.search
    search.city, search.state_region = "Colorado Springs", "CO"
    lead.target_zip_code = "80903"
    codes = [["80903"], ["80906"]] if separate_areas else [["80903", "80906"]]
    areas = [{"kind": "zip", "country": "US", "state": "CO", "postal_codes": postal_codes,
              "original_wording": "We want work from ZIPs 80903 and 80906"} for postal_codes in codes]
    append_owner_strategy(session, lead, {"schema_version": 1, "constraints": [], "territory_mode": "only",
                                          "target_territories": areas},
                          source_text="We want work from ZIPs 80903 and 80906", owner_confirmed=True)


def _observations(session, lead, *, added_service=None, added_intent="local_commercial", second_kind="zip"):
    value = sample_payload(session, lead)
    value["schema_version"] = 2
    value["source"]["geography"] = "Colorado Springs CO"
    coverage = {"kind": "zip", "country": "US", "state": "CO", "city": "Colorado Springs",
                "postal_codes": ["80903"], "method": "synthetic recorded postal sample",
                "reference": "synthetic:80903", "observed_at": value["observed_at"]}
    value["source"]["coverage"] = coverage
    query = value["queries"][0]
    query.update(query="emergency plumber Colorado Springs", coverage=coverage, volume_coverage=coverage)
    if added_service:
        second = deepcopy(query)
        second_coverage = {**coverage, "postal_codes": ["80906"], "reference": "synthetic:80906"}
        if second_kind == "city":
            second_coverage.pop("postal_codes")
            second_coverage["kind"] = "city"
        elif second_kind == "radius":
            second_coverage.pop("postal_codes")
            second_coverage.update(kind="radius", center={"latitude": 38.785, "longitude": -104.817},
                                   center_postal_code="80906", radius_miles=10,
                                   center_reference="synthetic:recorded-center:80906")
        second.update(service=added_service, query=f"{added_service} Colorado Springs", intent=added_intent,
                      service_refs=["synthetic:owner-confirmed:" + added_service],
                      coverage=second_coverage, volume_coverage=second_coverage, organic_rank=2,
                      page_url="https://local.example/" + added_service.replace(" ", "-"), refs=["synthetic:second-observation"])
        if added_service == query["service"]:
            second["page_url"] = query["page_url"]
        value["queries"].append(second)
        if added_service != query["service"]:
            page = deepcopy(value["pages"][0])
            page.update(url=second["page_url"], canonical=second["page_url"], services=[added_service],
                        service_refs=[second["page_url"] + "#service"])
            value["pages"].append(page)
    return value


def _emergency(report):
    return next(op for op in report["opportunities"] if op["service"] == "emergency plumbing"
                and op["intent"] == "local_commercial" and op["coverage"].get("postal_codes") == ["80903"])


def _sales_packet(session, lead):
    _, pricing, context = build_adaptive_sales_plan_with_context(session, lead, competitors=[])
    packet = SalesEvidenceService().build(session, lead, assessment=context.intervention_assessment,
                                         offer_id=context.offer_id, scope=context.scope).selected_evidence
    assert pricing.price_available
    assert context.scope == ("local SEO title/meta/H1 fixes",)
    assert packet["service"] == "emergency plumbing"
    assert packet["source_coverage"]["postal_codes"] == ["80903"]
    return packet


@pytest.mark.parametrize("service,intent", [("water heater replacement", "local_commercial"),
                                           ("emergency plumbing", "informational")])
def test_unrelated_observation_cannot_clear_selected_service_territory_warning(storage, service, intent):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        _owner_market(session, lead)
        first = append_research(session, lead, _observations(session, lead))
        stored_first = first.payload_json
        before = _emergency(project_seo_research(session, lead))
        assert before["decision"] == "recommended"
        before_warnings = [text for text in before["unknowns"] if "owner-confirmed target areas" in text]
        assert before_warnings

        append_research(session, lead, _observations(session, lead, added_service=service, added_intent=intent))
        after = _emergency(project_seo_research(session, lead))
        assert after["decision"] == "recommended"
        assert all(text in after["unknowns"] for text in before_warnings)
        assert first.payload_json == stored_first
        packet = _sales_packet(session, lead)
        assert packet["territory_coverage"][0]["state"] == "unknown"
        assert packet["territory_coverage"][0]["unobserved_postal_codes"] == ["80906"]
        assert all(text in packet["unknowns"] for text in before_warnings)


def test_same_service_observation_can_close_gap_without_creating_second_zip_sale(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        _owner_market(session, lead)
        append_research(session, lead, _observations(session, lead, added_service="emergency plumbing"))
        report = project_seo_research(session, lead)
        assert {op["decision"] for op in report["opportunities"]} == {"recommended", "no_sale"}
        assert report["territory_coverage"][0]["state"] == "recorded"
        packet = _sales_packet(session, lead)
        assert packet["territory_coverage"][0]["state"] == "recorded"
        assert packet["territory_coverage"][0]["unobserved_postal_codes"] == []
        assert not any("owner-confirmed target areas" in text for text in packet["unknowns"])


@pytest.mark.parametrize("kind", ["city", "radius"])
def test_same_service_city_or_circle_cannot_close_missing_zip_polygon_coverage(storage, kind):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        _owner_market(session, lead)
        append_research(session, lead, _observations(session, lead, added_service="emergency plumbing", second_kind=kind))
        packet = _sales_packet(session, lead)
        assert packet["territory_coverage"][0]["state"] == "unknown"
        assert packet["territory_coverage"][0]["unobserved_postal_codes"] == ["80906"]
        assert any("owner-confirmed target areas" in text for text in packet["unknowns"])


def test_separately_recorded_owner_areas_retain_service_specific_unknown(storage):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        _owner_market(session, lead, separate_areas=True)
        append_research(session, lead, _observations(session, lead, added_service="water heater replacement"))
        packet = _sales_packet(session, lead)
        by_zip = {item["target"]["postal_codes"][0]: item for item in packet["territory_coverage"]}
        assert by_zip["80903"]["state"] == "recorded"
        assert by_zip["80906"]["state"] == "unknown"
        assert by_zip["80906"]["unobserved_postal_codes"] == ["80906"]


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_empty_checkpoint_preserves_owner_territory_unknowns(storage, status):
    _, factory = storage
    with factory() as session:
        lead, _ = business(session)
        _owner_market(session, lead)
        value = _observations(session, lead)
        value["source"]["status"] = status
        value["queries"], value["pages"] = [], []
        append_research(session, lead, value)
        report = project_seo_research(session, lead)
        assert report["state"] == status
        assert report["opportunities"] == []
        assert report["territory_coverage"][0]["state"] == "unknown"
        assert report["territory_coverage"][0]["unobserved_postal_codes"] == ["80903", "80906"]
