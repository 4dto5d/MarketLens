from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from local_presence_miner.database.repositories import dumps, invalidate_approved_outreach_for_proof, log_activity
from local_presence_miner.database.schema import (
    AppSetting,
    Lead,
    OfferHistory,
    OutreachApprovalHistory,
    OutreachDraft,
    SellerProfile,
    SellerProject,
    SellerProof,
)
from local_presence_miner.domain.niche_taxonomy import niche_relation, resolve_niche
from local_presence_miner.domain.offer_registry import resolve_offer
from local_presence_miner.services.proof_dependency_service import parse_dependencies, proof_fingerprint
from local_presence_miner.time_utils import utc_now

PROOF_TYPES = [
    "Paid Project",
    "Unpaid Project",
    "Local-Business Website Project",
    "Audit Project",
    "Google Presence Project",
    "AI / Software System",
    "Automation Workflow",
    "Data-Processing Pipeline",
    "Portfolio Example",
    "Portfolio Concept",
    "Testimonial",
    "Measurable Outcome",
    "Niche-Specific Project",
    "Case Study",
    "Before / After",
    "Relevant Employment Experience",
    "Certification",
    "Other",
]
PROOF_STATUSES = [
    "Unclassified",
    "Completed",
    "Completed + Verified",
    "Completed + Testimonial",
    "Completed + Measurable Result",
    "In Progress",
    "Prototype",
    "Concept Only",
]
PROJECT_RECORD_TYPES = {
    "Paid Project",
    "Unpaid Project",
    "Local-Business Website Project",
    "Audit Project",
    "Google Presence Project",
    "Niche-Specific Project",
    "AI / Software System",
    "Automation Workflow",
    "Data-Processing Pipeline",
}
COMPLETED_PROJECT_STATUSES = {"Completed", "Completed + Verified", "Completed + Testimonial", "Completed + Measurable Result"}
SELLER_IDENTITY_TYPES = ["Individual / Freelancer", "Registered Business", "Brand Name"]
SELLER_LOCATION_MODES = ["Not configured", "Local", "Regional", "Remote", "Currently traveling", "Remote-first service"]
OFFER_STATUSES = ["Draft", "Presented", "Negotiating", "Accepted", "Rejected", "Won", "Lost", "Withdrawn", "No Response"]
LOST_REASONS = [
    "Too expensive",
    "Budget unavailable",
    "No response",
    "Chose competitor",
    "DIY",
    "Timing",
    "Not decision maker",
    "Scope mismatch",
    "Trust / proof issue",
    "No perceived need",
    "Unknown",
    "Other",
]
SEMANTIC_REVISION_KEY = "seller_semantic_revision"


def current_seller_semantic_revision(session: Session) -> int:
    setting = session.get(AppSetting, SEMANTIC_REVISION_KEY)
    if setting is None:
        return 0
    try:
        return int(setting.value)
    except ValueError:
        return 0


def mark_seller_semantics_changed(session: Session, reason: str) -> int:
    revision = current_seller_semantic_revision(session) + 1
    setting = session.get(AppSetting, SEMANTIC_REVISION_KEY)
    if setting is None:
        session.add(AppSetting(key=SEMANTIC_REVISION_KEY, value=str(revision)))
    else:
        setting.value = str(revision)
    log_activity(session, "seller_semantics_changed", f"Revision {revision}: {reason}")
    return revision


def invalidate_approved_commercial_drafts(
    session: Session,
    reason: str,
    *,
    lead_ids: set[int] | None = None,
    text_values: tuple[str, ...] = (),
) -> int:
    """Revoke only drafts already proven stale by structured plan comparison.

    ``text_values`` remains a compatibility parameter for older callers; text
    containment and draft kind are not commercial materiality authorities.
    Mutation seams call ``recompute_commercial_candidates`` before this helper.
    """
    del text_values
    revoked = 0
    drafts = session.scalars(select(OutreachDraft).where(OutreachDraft.approved.is_(True)))
    for draft in drafts:
        if lead_ids is not None and draft.lead_id not in lead_ids:
            continue
        if draft.commercial_dependency_state != "current":
            from local_presence_miner.database.repositories import revoke_outreach_approval

            revoked += int(revoke_outreach_approval(session, draft, reason))
    return revoked


def get_or_create_seller_profile(session: Session) -> SellerProfile:
    profile = session.scalar(select(SellerProfile).order_by(SellerProfile.id).limit(1))
    if profile is None:
        profile = SellerProfile()
        session.add(profile)
        session.flush()
    return profile


def save_seller_profile(
    session: Session,
    *,
    display_name: str,
    business_name: str,
    experience_start_date: str = "",
    identity_type: str | None = None,
    location_mode: str | None = None,
    location_label: str | None = None,
    service_area: str | None = None,
    notes: str = "",
) -> SellerProfile:
    if identity_type is not None and identity_type not in SELLER_IDENTITY_TYPES:
        raise ValueError("Select a valid seller identity type.")
    if location_mode is not None and location_mode not in SELLER_LOCATION_MODES:
        raise ValueError("Select a valid seller location mode.")
    profile = get_or_create_seller_profile(session)
    before_public = (
        profile.display_name,
        profile.business_name,
        profile.experience_start_date,
        profile.identity_type,
        profile.location_mode,
        profile.location_label,
        profile.service_area,
    )
    profile.display_name = display_name.strip()
    profile.business_name = business_name.strip()
    profile.experience_start_date = canonical_date(experience_start_date) or None
    if identity_type is not None:
        profile.identity_type = identity_type
    if location_mode is not None:
        profile.location_mode = location_mode
    if location_label is not None:
        profile.location_label = location_label.strip()
    if service_area is not None:
        profile.service_area = service_area.strip()
    profile.notes = notes.strip()
    profile.updated_at = utc_now()
    after_public = (
        profile.display_name,
        profile.business_name,
        profile.experience_start_date,
        profile.identity_type,
        profile.location_mode,
        profile.location_label,
        profile.service_area,
    )
    if before_public != after_public:
        mark_seller_semantics_changed(session, "Seller Profile public identity/location changed")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, "Seller Profile public identity/location changed")
    log_activity(session, "seller_profile_updated", "Updated private seller pricing profile")
    return profile


def list_seller_proof(session: Session, seller_profile_id: int | None = None) -> list[SellerProof]:
    query = select(SellerProof).order_by(SellerProof.completion_date.desc(), SellerProof.id.desc())
    if seller_profile_id is not None:
        query = query.where(SellerProof.seller_profile_id == seller_profile_id)
    return list(session.execute(query).scalars())


def list_seller_projects(
    session: Session,
    seller_profile_id: int | None = None,
    *,
    include_inactive: bool = False,
) -> list[SellerProject]:
    query = select(SellerProject).order_by(SellerProject.completion_date.desc(), SellerProject.id.desc())
    if seller_profile_id is not None:
        query = query.where(SellerProject.seller_profile_id == seller_profile_id)
    if not include_inactive:
        query = query.where(SellerProject.active.is_(True))
    return list(session.scalars(query))


def save_seller_project(
    session: Session,
    *,
    project_type: str,
    title: str,
    status: str = "Unclassified",
    niche: str = "",
    client_name: str = "",
    project_value: int | None = None,
    completion_date: str = "",
    client_work: bool = False,
    software_ai_project: bool = False,
    provenance: str = "",
    notes: str = "",
    counting_state: str = "incomplete",
    verified: bool = False,
    project_id: int | None = None,
) -> SellerProject:
    if project_type not in PROOF_TYPES:
        raise ValueError("Select a valid project type.")
    if status not in PROOF_STATUSES:
        raise ValueError("Select a valid project status.")
    if not title.strip():
        raise ValueError("Project title is required.")
    if project_value is not None and project_value < 0:
        raise ValueError("Project value cannot be negative.")
    if counting_state not in {"confirmed", "incomplete", "invalidated", "legacy_unresolved"}:
        raise ValueError("Select a valid project counting state.")
    if counting_state == "confirmed" and (status not in COMPLETED_PROJECT_STATUSES or not client_work):
        raise ValueError("A confirmed project must be completed actual client work.")
    profile = get_or_create_seller_profile(session)
    project = session.get(SellerProject, project_id) if project_id else None
    if project_id is not None and project is None:
        raise ValueError("Seller Project no longer exists.")
    if project is not None and project.seller_profile_id != profile.id:
        raise ValueError("Seller Project belongs to another seller profile.")
    before = None if project is None else (
        project.project_type,
        project.title,
        project.status,
        project.niche,
        project.client_name,
        project.project_value,
        project.completion_date,
        project.client_work,
        project.software_ai_project,
        project.provenance,
        project.counting_state,
        project.verified,
        project.active,
    )
    if project is None:
        project = SellerProject(seller_profile_id=profile.id, title=title.strip())
        session.add(project)
    niche_resolution = resolve_niche(niche)
    project.project_type = project_type
    project.title = title.strip()
    project.status = status
    project.niche = niche.strip()
    project.canonical_niche_id = niche_resolution.canonical_id if niche_resolution.resolved else ""
    project.niche_match_rule = niche_resolution.match_rule
    project.client_name = client_name.strip() or None
    project.project_value = project_value
    project.completion_date = canonical_date(completion_date) or None
    project.client_work = bool(client_work)
    project.software_ai_project = bool(software_ai_project)
    project.provenance = provenance.strip()
    project.counting_state = counting_state
    project.verified = bool(verified)
    project.invalidated_at = None
    project.invalidation_reason = ""
    project.active = counting_state != "invalidated"
    project.notes = notes.strip()
    project.project_revision = int(project.project_revision or 0) + (1 if before is not None else 0)
    project.updated_at = utc_now()
    session.flush()
    after = (
        project.project_type,
        project.title,
        project.status,
        project.niche,
        project.client_name,
        project.project_value,
        project.completion_date,
        project.client_work,
        project.software_ai_project,
        project.provenance,
        project.counting_state,
        project.verified,
        project.active,
    )
    if before != after:
        mark_seller_semantics_changed(session, f"Seller Project #{project.id} changed")
        linked_ids = list(session.scalars(select(SellerProof.id).where(SellerProof.project_id == project.id)))
        for proof_id in linked_ids:
            invalidate_approved_outreach_for_proof(session, proof_id, f"Seller Project #{project.id} changed")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, f"Seller Project #{project.id} changed")
    log_activity(session, "seller_project_saved", f"Saved private seller project #{project.id}")
    return project


def deactivate_seller_project(session: Session, project_id: int) -> None:
    """Soft-invalidate a project so artifacts and approval-time evidence remain auditable."""
    project = session.get(SellerProject, project_id)
    if project is None or project.counting_state == "invalidated":
        return
    from local_presence_miner.services.proof_dependency_service import project_dependency_ids

    project.active = False
    project.counting_state = "invalidated"
    project.invalidated_at = utc_now()
    project.invalidation_reason = "Operator invalidated project"
    project.project_revision = int(project.project_revision or 0) + 1
    project.updated_at = utc_now()
    for proof_id in project_dependency_ids(session, project_id):
        invalidate_approved_outreach_for_proof(session, proof_id, f"Seller Project #{project_id} was invalidated")
    mark_seller_semantics_changed(session, f"Seller Project #{project_id} invalidated")
    from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

    recompute_commercial_candidates(session, f"Seller Project #{project_id} invalidated")
    log_activity(session, "seller_project_invalidated", f"Invalidated private seller project #{project_id}")


def _proof_id_high_water(session: Session, minimum: int = 0) -> AppSetting:
    """Retain proof identity after deletion; SQLite's default rowid can be reused."""
    setting = session.get(AppSetting, "seller_proof_id_high_water")
    largest = max(int(session.scalar(select(func.max(SellerProof.id))) or 0), minimum)
    if setting is None:
        for model in (OutreachDraft, OutreachApprovalHistory):
            for value in session.scalars(select(model.proof_dependencies_json)):
                for dependency in parse_dependencies(value):
                    proof_id = dependency.get("proof_id")
                    if isinstance(proof_id, int):
                        largest = max(largest, proof_id)
        setting = AppSetting(key="seller_proof_id_high_water", value=str(largest))
        session.add(setting)
    else:
        try:
            largest = max(largest, int(setting.value))
        except ValueError as exc:
            raise ValueError("Proof ID history is malformed; creation/deletion requires review.") from exc
        setting.value = str(largest)
    session.flush()
    return setting


def save_seller_proof(
    session: Session,
    *,
    proof_type: str,
    title: str,
    status: str | None = None,
    niche: str = "",
    description: str = "",
    client_name: str = "",
    project_value: int | None = None,
    completion_date: str = "",
    public_url: str = "",
    verified: bool | None = None,
    client_work: bool | None = None,
    software_ai_project: bool | None = None,
    testimonial_available: bool | None = None,
    measurable_result_available: bool | None = None,
    before_after_available: bool | None = None,
    provenance: str | None = None,
    safe_claims: list[str] | None = None,
    prohibited_claims: list[str] | None = None,
    internal_only: bool | None = None,
    share_client_name: bool | None = None,
    share_public_url: bool | None = None,
    share_testimonial: bool | None = None,
    share_case_study: bool | None = None,
    share_reference: bool | None = None,
    notes: str = "",
    proof_id: int | None = None,
    project_id: int | None = None,
) -> SellerProof:
    if proof_type not in PROOF_TYPES:
        raise ValueError("Select a valid proof type.")
    if not title.strip():
        raise ValueError("Proof title is required.")
    if project_value is not None and project_value < 0:
        raise ValueError("Project value cannot be negative.")
    profile = get_or_create_seller_profile(session)
    proof = session.get(SellerProof, proof_id) if proof_id else None
    if proof_id is not None and proof is None:
        raise ValueError("Seller Proof record no longer exists.")
    if proof is not None and proof.seller_profile_id != profile.id:
        raise ValueError("Proof record belongs to another seller profile.")
    previous_fingerprint = proof_fingerprint(proof) if proof is not None else ""
    project = None
    effective_project_id = project_id
    if proof is not None and project_id is None:
        effective_project_id = proof.project_id
    if effective_project_id:
        project = session.get(SellerProject, effective_project_id)
        if project is None or project.seller_profile_id != profile.id or not project.active:
            raise ValueError("Select an active Seller Project owned by this profile.")
    effective_status = status or (proof.status if proof is not None else "Unclassified")
    if effective_status not in PROOF_STATUSES:
        raise ValueError("Select a valid proof status.")
    effective_verified = bool(verified) if verified is not None else bool(proof.verified if proof is not None else False)
    effective_client_work = bool(client_work) if client_work is not None else bool(proof.client_work if proof is not None else False)
    effective_software = (
        bool(software_ai_project) if software_ai_project is not None else bool(proof.software_ai_project if proof is not None else False)
    )
    effective_testimonial = (
        bool(testimonial_available)
        if testimonial_available is not None
        else bool(proof.testimonial_available if proof is not None else False)
    )
    effective_result = (
        bool(measurable_result_available)
        if measurable_result_available is not None
        else bool(proof.measurable_result_available if proof is not None else False)
    )
    effective_before_after = (
        bool(before_after_available)
        if before_after_available is not None
        else bool(proof.before_after_available if proof is not None else False)
    )
    if effective_status in {"Prototype", "Concept Only"} and effective_client_work:
        raise ValueError("A prototype or concept cannot be recorded as completed client work.")
    if effective_status == "Completed + Verified":
        effective_verified = True
    if effective_status == "Completed + Testimonial":
        effective_testimonial = True
    if effective_status == "Completed + Measurable Result":
        effective_result = True
    if project is None and proof is None and proof_type in PROJECT_RECORD_TYPES and effective_status in COMPLETED_PROJECT_STATUSES and effective_client_work:
        project_niche = resolve_niche(niche)
        project = SellerProject(
            seller_profile_id=profile.id,
            project_type=proof_type,
            title=title.strip(),
            status=effective_status,
            niche=niche.strip(),
            canonical_niche_id=project_niche.canonical_id if project_niche.resolved else "",
            niche_match_rule=project_niche.match_rule,
            client_name=client_name.strip() or None,
            project_value=project_value,
            completion_date=canonical_date(completion_date) or None,
            client_work=True,
            software_ai_project=effective_software,
            provenance="Explicit project record created with its first project artifact",
            grouping_state="explicit",
            counting_state="confirmed",
            verified=effective_verified,
            active=True,
        )
        session.add(project)
        session.flush()
    if proof is None:
        identity = _proof_id_high_water(session)
        next_id = int(identity.value) + 1
        identity.value = str(next_id)
        proof = SellerProof(id=next_id, seller_profile_id=profile.id, proof_type=proof_type, title=title.strip())
        session.add(proof)
    proof.proof_type = proof_type
    proof.project_id = project.id if project is not None else None
    proof.grouping_state = "explicit" if project is not None else (proof.grouping_state if proof_id else "unresolved")
    proof.title = title.strip()
    proof.status = effective_status
    proof.niche = niche.strip()
    niche_resolution = resolve_niche(proof.niche or (project.niche if project is not None else ""))
    proof.canonical_niche_id = niche_resolution.canonical_id if niche_resolution.resolved else ""
    proof.niche_match_rule = niche_resolution.match_rule
    proof.description = description.strip()
    proof.client_name = client_name.strip() or None
    proof.project_value = project_value
    proof.completion_date = canonical_date(completion_date) or None
    proof.public_url = public_url.strip() or None
    proof.verified = effective_verified
    proof.client_work = effective_client_work
    proof.software_ai_project = effective_software
    proof.testimonial_available = effective_testimonial
    proof.measurable_result_available = effective_result
    proof.before_after_available = effective_before_after
    if provenance is not None:
        proof.provenance = provenance.strip()
    if safe_claims is not None:
        proof.safe_claims_json = dumps([item.strip() for item in safe_claims if item.strip()])
    if prohibited_claims is not None:
        proof.prohibited_claims_json = dumps([item.strip() for item in prohibited_claims if item.strip()])
    proof.internal_only = bool(internal_only) if internal_only is not None else bool(proof.internal_only if proof_id else True)
    proof.share_client_name = (
        bool(share_client_name) if share_client_name is not None else bool(proof.share_client_name if proof_id else False)
    )
    proof.share_public_url = bool(share_public_url) if share_public_url is not None else bool(proof.share_public_url if proof_id else False)
    proof.share_testimonial = (
        bool(share_testimonial) if share_testimonial is not None else bool(proof.share_testimonial if proof_id else False)
    )
    proof.share_case_study = (
        bool(share_case_study) if share_case_study is not None else bool(proof.share_case_study if proof_id else False)
    )
    proof.share_reference = bool(share_reference) if share_reference is not None else bool(proof.share_reference if proof_id else False)
    if proof.internal_only:
        proof.share_client_name = False
        proof.share_public_url = False
        proof.share_testimonial = False
        proof.share_case_study = False
        proof.share_reference = False
    proof.notes = notes.strip()
    if str(proof.artifact_state or "active") != "active":
        raise ValueError("Withdrawn or deleted proof artifacts cannot be edited; create a new artifact instead.")
    proof.artifact_revision = int(proof.artifact_revision or 0) + (1 if previous_fingerprint else 0)
    proof.updated_at = utc_now()
    session.flush()
    current_fingerprint = proof_fingerprint(proof)
    if previous_fingerprint and previous_fingerprint != current_fingerprint:
        invalidate_approved_outreach_for_proof(session, int(proof.id), f"Seller Proof #{proof.id} changed")
    if not previous_fingerprint or previous_fingerprint != current_fingerprint:
        mark_seller_semantics_changed(session, f"Seller Proof #{proof.id} changed")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, f"Seller Proof #{proof.id} changed")
    log_activity(session, "seller_proof_saved", f"Saved private seller proof #{proof.id}")
    return proof


def delete_seller_proof(session: Session, proof_id: int) -> None:
    proof = session.get(SellerProof, proof_id)
    if proof and proof.artifact_state == "active":
        _proof_id_high_water(session, proof_id)
        invalidate_approved_outreach_for_proof(session, proof_id, f"Seller Proof #{proof_id} was deleted")
        proof.artifact_state = "deleted_tombstone"
        proof.withdrawn_or_deleted_at = utc_now()
        proof.withdrawal_or_deletion_reason = "Operator deleted proof artifact"
        proof.internal_only = True
        proof.share_client_name = False
        proof.share_public_url = False
        proof.share_testimonial = False
        proof.share_case_study = False
        proof.share_reference = False
        proof.artifact_revision = int(proof.artifact_revision or 0) + 1
        proof.updated_at = utc_now()
        mark_seller_semantics_changed(session, f"Seller Proof #{proof_id} deleted")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, f"Seller Proof #{proof_id} deleted")
        log_activity(session, "seller_proof_deleted", f"Tombstoned private seller proof #{proof_id}")


def list_offer_history(session: Session, seller_profile_id: int | None = None) -> list[OfferHistory]:
    query = select(OfferHistory).order_by(OfferHistory.offer_date.desc(), OfferHistory.id.desc())
    if seller_profile_id is not None:
        query = query.where(OfferHistory.seller_profile_id == seller_profile_id)
    return list(session.execute(query).scalars())


def save_offer_history(
    session: Session,
    *,
    offer_date: str,
    business_name: str,
    niche: str,
    package_name: str,
    scope_summary: str,
    initial_ask: int,
    status: str,
    lead_id: int | None = None,
    city: str = "",
    recommended_ask_at_offer: int | None = None,
    final_ask: int | None = None,
    closed_amount: int | None = None,
    currency: str = "USD",
    lost_reason: str = "",
    notes: str = "",
    growth_score_at_offer: int | None = None,
    project_value_low_at_offer: int | None = None,
    project_value_high_at_offer: int | None = None,
    seller_confidence_at_offer: str = "",
    proof_snapshot: dict[str, Any] | None = None,
    offer_id: int | None = None,
    canonical_offer_id: str = "",
    historical_record: bool = False,
) -> OfferHistory:
    if status not in OFFER_STATUSES:
        raise ValueError("Select a valid offer status.")
    if lost_reason and lost_reason not in LOST_REASONS:
        raise ValueError("Select a valid lost reason.")
    if not business_name.strip():
        raise ValueError("Business name is required.")
    canonical_offer_date = canonical_date(offer_date)
    if not canonical_offer_date:
        raise ValueError("Offer date is required.")
    amounts = [value for value in [initial_ask, recommended_ask_at_offer, final_ask, closed_amount] if value is not None]
    if initial_ask <= 0 or any(value < 0 for value in amounts):
        raise ValueError("Offer amounts must be positive dollar values.")
    if status == "Won" and not closed_amount:
        raise ValueError("A won offer requires the actual closed amount.")
    profile = get_or_create_seller_profile(session)
    offer = session.get(OfferHistory, offer_id) if offer_id else None
    if offer_id is not None and offer is None:
        raise ValueError("Offer record no longer exists.")
    if offer is not None and lead_id is None:
        lead_id = offer.lead_id
    if type(historical_record) is not bool:
        raise ValueError("Historical recording must be an explicit decision.")
    resolution = resolve_offer(package_name, canonical_offer_id or None)
    label_resolution = resolve_offer(package_name)
    if (canonical_offer_id and label_resolution.offer_id is not None
            and label_resolution.offer_id != resolution.offer_id):
        raise ValueError("Package label and canonical Offer ID disagree.")
    resolved_id = resolution.offer_id.value if resolution.offer_id else ""
    _validate_payable_offer_change(
        session, offer, lead_id=lead_id, offer_date=canonical_offer_date, canonical_id=resolved_id,
        scope=scope_summary.strip(), amount=closed_amount or final_ask or initial_ask, status=status,
        historical_record=historical_record, notes=notes,
    )
    is_new = offer is None
    before_semantic = None if offer is None else (
        offer.lead_id,
        offer.offer_date,
        offer.niche,
        offer.package_name,
        offer.canonical_offer_id,
        offer.scope_summary,
        offer.initial_ask,
        offer.recommended_ask_at_offer,
        offer.final_ask,
        offer.closed_amount,
        offer.status,
        offer.lost_reason,
        offer.growth_score_at_offer,
        offer.project_value_low_at_offer,
        offer.project_value_high_at_offer,
    )
    if offer is None:
        offer = OfferHistory(
            seller_profile_id=profile.id,
            offer_date=canonical_offer_date,
            business_name=business_name.strip(),
            initial_ask=initial_ask,
        )
        session.add(offer)
    elif offer.seller_profile_id != profile.id:
        raise ValueError("Offer record belongs to another seller profile.")
    offer.lead_id = lead_id
    offer.offer_date = canonical_offer_date
    offer.business_name = business_name.strip()
    offer.niche = niche.strip()
    niche_resolution = resolve_niche(offer.niche)
    offer.canonical_niche_id = niche_resolution.canonical_id if niche_resolution.resolved else ""
    offer.niche_match_rule = niche_resolution.match_rule
    offer.city = city.strip() or None
    offer.package_name = package_name.strip()
    offer_resolution = resolution
    offer.canonical_offer_id = offer_resolution.offer_id.value if offer_resolution.offer_id else ""
    offer.offer_resolution_state = offer_resolution.status
    offer.scope_summary = scope_summary.strip()
    offer.initial_ask = initial_ask
    offer.recommended_ask_at_offer = recommended_ask_at_offer
    offer.final_ask = final_ask
    offer.closed_amount = closed_amount
    offer.currency = currency.strip().upper() or "USD"
    offer.status = status
    offer.lost_reason = lost_reason or None
    offer.notes = notes.strip()
    offer.growth_score_at_offer = growth_score_at_offer
    offer.project_value_low_at_offer = project_value_low_at_offer
    offer.project_value_high_at_offer = project_value_high_at_offer
    offer.seller_confidence_at_offer = seller_confidence_at_offer or None
    if is_new:
        offer.proof_snapshot_json = dumps(proof_snapshot or {})
    offer.updated_at = utc_now()
    session.flush()
    after_semantic = (
        offer.lead_id,
        offer.offer_date,
        offer.niche,
        offer.package_name,
        offer.canonical_offer_id,
        offer.scope_summary,
        offer.initial_ask,
        offer.recommended_ask_at_offer,
        offer.final_ask,
        offer.closed_amount,
        offer.status,
        offer.lost_reason,
        offer.growth_score_at_offer,
        offer.project_value_low_at_offer,
        offer.project_value_high_at_offer,
    )
    if before_semantic != after_semantic:
        mark_seller_semantics_changed(session, f"Offer History #{offer.id} changed")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, f"Offer History #{offer.id} changed")
    log_activity(session, "offer_history_saved", f"Saved private offer record #{offer.id}; historical_record={historical_record}", lead_id)
    return offer


def _validate_payable_offer_change(
    session: Session, existing: OfferHistory | None, *, lead_id: int | None, offer_date: str,
    canonical_id: str, scope: str, amount: int, status: str, historical_record: bool, notes: str,
) -> None:
    """Guard forward commitments at persistence; preserve unchanged historical rows."""
    if status not in {"Accepted", "Won"}:
        return
    was_payable = existing is not None and existing.status in {"Accepted", "Won"}
    previous = None if existing is None else (
        existing.lead_id, existing.canonical_offer_id, existing.scope_summary,
        existing.closed_amount or existing.final_ask or existing.initial_ask, existing.status,
    )
    if was_payable and previous == (lead_id, canonical_id, scope, amount, status):
        return
    # The historical path cannot convert an existing Draft into a new commitment.
    # Linked history needs a past agreement date and traceable correction notes.
    if historical_record and (existing is None or was_payable):
        if lead_id is None or (offer_date < date.today().isoformat() and notes.strip()
                              and (existing is None or existing.offer_date < date.today().isoformat())):
            return
        raise ValueError("Linked historical agreements require a past date and history notes; new commitments require a delivery packet.")
    lead = session.get(Lead, lead_id) if lead_id is not None else None
    if lead is None:
        raise ValueError("A new payable agreement requires a current business and reviewed delivery packet; record past history explicitly.")
    from local_presence_miner.services.adaptive_sales_asset_service import build_adaptive_sales_plan_with_context
    from local_presence_miner.services.delivery_packet_service import DeliveryPacketService

    _, _, context = build_adaptive_sales_plan_with_context(session, lead)
    packet = DeliveryPacketService().build(session, lead, context=context, selected_price=amount)
    if (not packet["ready_for_payment"] or canonical_id != context.offer_id or scope != "; ".join(context.scope)):
        raise ValueError("Payable agreement requires reviewed evidence and an owner-approved delivery packet "
                         "bound to this exact canonical offer, scope and amount, with technical prerequisites resolved.")


def delete_offer_history(session: Session, offer_id: int) -> None:
    offer = session.get(OfferHistory, offer_id)
    if offer:
        session.delete(offer)
        session.flush()
        mark_seller_semantics_changed(session, f"Offer History #{offer_id} deleted")
        from local_presence_miner.services.commercial_state_service import recompute_commercial_candidates

        recompute_commercial_candidates(session, f"Offer History #{offer_id} was deleted")
        log_activity(session, "offer_history_deleted", f"Deleted private offer record #{offer_id}", offer.lead_id)


def affected_lead_ids_for_offer(session: Session, offer: OfferHistory) -> set[int]:
    """Select leads for which the history row can be a pricing comparable."""
    affected: set[int] = set()
    for lead in session.scalars(select(Lead)):
        same_offer = bool(
            offer.canonical_offer_id
            and lead.recommended_offer_id
            and offer.canonical_offer_id == lead.recommended_offer_id
        )
        same_niche = niche_relation(offer.niche, lead.category) == "same"
        if same_offer or same_niche or offer.lead_id == lead.id:
            affected.add(int(lead.id))
    return affected


def canonical_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD for dates.") from exc
