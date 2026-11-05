from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from local_presence_miner.database.pricing_repository import list_offer_history, list_seller_proof
from local_presence_miner.database.repositories import lead_google_details_retrieved, list_leads, loads


class ExportService:
    def export_leads_csv(self, session: Session, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for lead in list_leads(session):
            details_retrieved = lead_google_details_retrieved(lead)
            rows.append(
                {
                    "status": lead.status,
                    "priority": lead.priority,
                    "lead_score": lead.lead_score,
                    "business_name": lead.name,
                    "category": lead.category,
                    "phone": lead.phone,
                    "website": lead.website,
                    "google_maps_url": lead.google_maps_url,
                    "yelp_url": lead.yelp_url,
                    "rating": lead.rating if details_retrieved and lead.rating is not None else "",
                    "review_count": lead.review_count if details_retrieved else "",
                    "google_details_retrieved": details_retrieved,
                    "search_position": lead.search_position or "",
                    "recommended_offer": lead.recommended_offer,
                    "target_signals": " | ".join(loads(lead.target_signals_json, [])),
                    "suppressed": lead.suppressed,
                    "next_follow_up_date": lead.next_follow_up_date,
                    "last_contacted_date": lead.last_contacted_date,
                    "notes": lead.operator_notes,
                }
            )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["business_name"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def export_offer_history_csv(self, session: Session, path: Path) -> Path:
        rows = [
            {
                "offer_date": offer.offer_date,
                "business_name": offer.business_name,
                "niche": offer.niche,
                "city": offer.city or "",
                "package_name": offer.package_name,
                "scope_summary": offer.scope_summary,
                "initial_ask": offer.initial_ask,
                "recommended_ask_at_offer": offer.recommended_ask_at_offer or "",
                "final_ask": offer.final_ask or "",
                "closed_amount": offer.closed_amount or "",
                "currency": offer.currency,
                "status": offer.status,
                "lost_reason": offer.lost_reason or "",
                "growth_score_at_offer": offer.growth_score_at_offer or "",
                "project_value_low_at_offer": offer.project_value_low_at_offer or "",
                "project_value_high_at_offer": offer.project_value_high_at_offer or "",
                "seller_confidence_at_offer": offer.seller_confidence_at_offer or "",
                "notes": offer.notes,
            }
            for offer in list_offer_history(session)
        ]
        return write_csv(path, rows, ["business_name"])

    def export_seller_proof_csv(self, session: Session, path: Path) -> Path:
        rows = [
            {
                "proof_type": proof.proof_type,
                "title": proof.title,
                "status": proof.status,
                "niche": proof.niche,
                "description": proof.description,
                "client_name": proof.client_name or "",
                "project_value": proof.project_value or "",
                "completion_date": proof.completion_date or "",
                "public_url": proof.public_url or "",
                "verified": proof.verified,
                "client_work": proof.client_work,
                "software_ai_project": proof.software_ai_project,
                "testimonial_available": proof.testimonial_available,
                "measurable_result_available": proof.measurable_result_available,
                "before_after_available": proof.before_after_available,
                "provenance": proof.provenance,
                "safe_claims_json": proof.safe_claims_json,
                "prohibited_claims_json": proof.prohibited_claims_json,
                "notes": proof.notes,
            }
            for proof in list_seller_proof(session)
        ]
        return write_csv(path, rows, ["title"])


def write_csv(path: Path, rows: list[dict], empty_fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else empty_fields)
        writer.writeheader()
        writer.writerows(rows)
    return path
