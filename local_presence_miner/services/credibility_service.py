from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.pricing_repository import list_seller_projects, list_seller_proof
from local_presence_miner.database.schema import SellerProfile, SellerProject, SellerProof
from local_presence_miner.domain.niche_taxonomy import niche_relation
from local_presence_miner.services.proof_dependency_service import (
    USAGE_CASE_STUDY,
    USAGE_CLIENT_NAME,
    USAGE_PUBLIC_URL,
    USAGE_REFERENCE,
    USAGE_TESTIMONIAL,
    make_proof_dependency,
    proof_allows_external_use,
)
from local_presence_miner.services.seller_proof_service import artifact_is_active, prohibited_claims, project_is_completed, proof_is_completed, safe_claims


@dataclass(frozen=True)
class RankedProof:
    proof: SellerProof
    score: int
    relevance: str
    safe_label: str


@dataclass(frozen=True)
class ProofAttachments:
    send: tuple[str, ...]
    optional: tuple[str, ...]
    do_not_send: tuple[str, ...]


@dataclass(frozen=True)
class CredibilityProfile:
    why_you: tuple[str, ...]
    do_not_claim: tuple[str, ...]
    ranked_proof: tuple[RankedProof, ...]
    attachments: ProofAttachments
    experience_quick: str
    experience_normal: str
    experience_detailed: str
    identity_response: str
    company_response: str
    location_response: str
    ai_response: str
    trust_response: str
    email_context: str
    proposal_points: tuple[str, ...]
    email_proof_dependencies: tuple[dict[str, Any], ...]
    attachment_proof_dependencies: tuple[dict[str, Any], ...]
    reference_options: tuple[str, ...]
    completed_client_projects: int
    same_niche_completed_client_projects: int


class CredibilityService:
    """Build truthful seller-credibility support from the private proof ledger."""

    def build(self, session: Session, niche: str = "") -> CredibilityProfile:
        profile = session.scalar(select(SellerProfile).order_by(SellerProfile.id).limit(1))
        all_projects = {item.id: item for item in list_seller_projects(session, include_inactive=True)}
        proofs = [item for item in list_seller_proof(session) if artifact_is_active(item) and _proof_project_is_current(item, all_projects)]
        ranked = tuple(sorted((self._rank(item, niche) for item in proofs), key=lambda item: (item.score, item.proof.id or 0), reverse=True))
        completed_projects = [item for item in all_projects.values() if project_is_completed(item)]
        completed_project_ids = {item.id for item in completed_projects}
        completed_client = [item for item in proofs if proof_is_completed(item) and item.client_work and item.project_id in completed_project_ids]
        same_niche_projects = [item for item in completed_projects if _niche_match(item.niche, niche) == "same"]
        same_niche_client = [item for item in completed_client if _niche_match(item.niche, niche) == "same"]
        completed_software = [item for item in proofs if proof_is_completed(item) and item.software_ai_project]
        why_you = self._why_you(ranked, completed_client, completed_software)
        do_not_claim = tuple(
            dict.fromkeys(
                [
                    *[claim for item in proofs for claim in prohibited_claims(item)],
                    "Revenue, ranking, lead-volume, or conversion improvements without verified outcome evidence",
                    "Agency size, years of experience, clients, references, or niche expertise not recorded in Seller Proof",
                    "A prototype, concept, or in-progress project as completed client work",
                ]
            )
        )
        attachments, attachment_proofs = self._attachments(ranked)
        external_client = [item for item in completed_client if _externally_shareable(item)]
        external_same_niche = [item for item in same_niche_client if _externally_shareable(item)]
        external_software = [item for item in completed_software if _externally_shareable(item)]
        quick, normal, detailed = self._experience_responses(
            ranked,
            external_client,
            external_same_niche,
            len(completed_projects),
            len(same_niche_projects),
        )
        identity, company, location = self._seller_identity(profile)
        ai_response = self._ai_response(external_software)
        trust = (
            "You shouldn't have to take my word for it. I can show you exactly what I found, which public evidence I used, "
            "and what I'd change before you decide whether anything is worth doing."
        )
        email_context, email_proofs = self._email_context(ranked, external_same_niche, external_client)
        proposal_items = [
            item for item in ranked if item.score >= 65 and proof_is_completed(item.proof) and item.proof.verified and _externally_shareable(item.proof)
        ][:2]
        proposal_points = tuple(_external_label(item.proof) for item in proposal_items)
        reference_options = tuple(
            _external_label(item.proof)
            for item in ranked
            if proof_is_completed(item.proof) and proof_allows_external_use(item.proof, USAGE_REFERENCE)
        )[:2]
        return CredibilityProfile(
            why_you=why_you,
            do_not_claim=do_not_claim,
            ranked_proof=ranked,
            attachments=attachments,
            experience_quick=quick,
            experience_normal=normal,
            experience_detailed=detailed,
            identity_response=identity,
            company_response=company,
            location_response=location,
            ai_response=ai_response,
            trust_response=trust,
            email_context=email_context,
            proposal_points=proposal_points,
            email_proof_dependencies=tuple(
                make_proof_dependency(
                    proof,
                    _preferred_external_usages(proof),
                    project=all_projects.get(proof.project_id) if proof.project_id is not None else None,
                )
                for proof in email_proofs
            ),
            attachment_proof_dependencies=tuple(
                make_proof_dependency(
                    proof,
                    {USAGE_PUBLIC_URL},
                    project=all_projects.get(proof.project_id) if proof.project_id is not None else None,
                )
                for proof in attachment_proofs
            ),
            reference_options=reference_options,
            completed_client_projects=len(completed_projects),
            same_niche_completed_client_projects=len(same_niche_projects),
        )

    def _rank(self, proof: SellerProof, niche: str) -> RankedProof:
        status = str(proof.status or "Unclassified")
        match = _niche_match(proof.niche, niche)
        if proof_is_completed(proof) and proof.client_work and match == "same":
            score, relevance = 100, "Same-niche completed client work"
        elif proof_is_completed(proof) and proof.client_work and match == "similar":
            score, relevance = 90, "Similar-niche completed client work"
        elif proof_is_completed(proof) and proof.client_work:
            score, relevance = 80, "Completed local-business client work"
        elif proof_is_completed(proof) and proof.software_ai_project and "local presence miner" in proof.title.casefold():
            score, relevance = 70, "Recorded Local Presence Miner system proof"
        elif proof_is_completed(proof) and proof.software_ai_project:
            score, relevance = 60, "Completed AI/software/automation work"
        elif proof_is_completed(proof):
            score, relevance = 50, "Completed adjacent proof"
        elif status == "In Progress":
            score, relevance = 25, "In progress; not completed"
        elif status == "Prototype":
            score, relevance = 20, "Working prototype; not client completion"
        elif status == "Concept Only":
            score, relevance = 10, "Concept only"
        else:
            score, relevance = 5, "Unclassified evidence"
        score += 5 if proof.verified else 0
        score += 3 if proof.testimonial_available and proof.verified else 0
        score += 3 if proof.measurable_result_available and proof.verified else 0
        return RankedProof(proof, score, relevance, _safe_label(proof))

    @staticmethod
    def _why_you(
        ranked: tuple[RankedProof, ...], completed_client: list[SellerProof], completed_software: list[SellerProof]
    ) -> tuple[str, ...]:
        lines: list[str] = []
        strongest = next((item for item in ranked if proof_is_completed(item.proof)), None)
        if strongest:
            label = (
                _external_label(strongest.proof) if _externally_shareable(strongest.proof)
                else f"internal record #{strongest.proof.id}; no external disclosure permitted"
            )
            lines.append(f"Strongest relevant proof: {label}")
        else:
            lines.append("Strongest relevant proof: no completed proof is recorded yet")
        system = next((item for item in completed_software if "local presence miner" in item.title.casefold()), None)
        if system:
            lines.append(f"System proof: internal record #{system.id}; use only the separately permitted disclosures")
        elif completed_software:
            lines.append(f"Technical proof: internal record #{completed_software[0].id}; use only the separately permitted disclosures")
        lines.append(f"Current client proof: {len(completed_client)} completed client project(s) recorded")
        return tuple(lines)

    @staticmethod
    def _experience_responses(
        ranked: tuple[RankedProof, ...],
        completed_client: list[SellerProof],
        same_niche: list[SellerProof],
        completed_project_count: int,
        same_niche_project_count: int,
    ) -> tuple[str, str, str]:
        if same_niche:
            example = _external_label(same_niche[0])
            quick = f"I have {same_niche_project_count} completed relevant client project(s) recorded, including {example}."
            support = []
            if any(proof_allows_external_use(item, USAGE_TESTIMONIAL) for item in same_niche):
                support.append("a verified testimonial")
            if any(item.measurable_result_available and proof_allows_external_use(item, USAGE_CASE_STUDY) for item in same_niche):
                support.append("a verified measurable result")
            normal = quick + (" I can also share " + " and ".join(support) + "." if support else " I can show the recorded example.")
            return quick, normal, normal + " I’ll keep any claims limited to what the proof record actually supports."
        if completed_client:
            quick = f"I have {completed_project_count} completed client project(s) recorded, though none are marked as the same niche."
            normal = quick + " I’d rather show the closest real example and this prospect-specific comparison than pretend it is identical experience."
            return quick, normal, normal + " Any testimonial or outcome is mentioned only when it is separately verified."
        developmental = next(
            (item for item in ranked if item.proof.status in {"In Progress", "Prototype", "Concept Only"} and _externally_shareable(item.proof)),
            None,
        )
        if developmental:
            label = _external_label(developmental.proof)
            if developmental.proof.status == "In Progress":
                phrase = f"I’m building {label}; it is still in progress, not completed client work."
            elif developmental.proof.status == "Prototype":
                phrase = f"I have a working prototype, {label}; it is not completed client work."
            else:
                phrase = f"I have a concept, {label}; it is not a completed project."
            return phrase, phrase + " I’d rather show you the actual comparison and let the work speak for itself.", phrase
        normal = (
            "I'm newer on the client-service side, so I'm not going to pretend I have a large niche portfolio. "
            "I'd rather show you the actual comparison and let the evidence and proposed work speak for themselves."
        )
        return "I'm newer on the client-service side, and I won't pretend otherwise.", normal, normal

    @staticmethod
    def _seller_identity(profile: SellerProfile | None) -> tuple[str, str, str]:
        if profile is None:
            return (
                "I analyze public website and Google presence evidence for local businesses and turn it into a focused improvement plan.",
                "I operate independently; no company identity is configured in Seller Profile.",
                "I don't want to imply a local office. My location and service model are not configured yet.",
            )
        name = profile.display_name.strip()
        business = profile.business_name.strip()
        identity = "I analyze public website and Google presence evidence for local businesses and turn it into a focused improvement plan."
        if name:
            identity = f"I'm {name}. " + identity
        if profile.identity_type == "Individual / Freelancer" or not business:
            company = f"I operate independently{f' as {name}' if name else ''}."
        else:
            company = f"I work under {business}."
        location = _location_response(profile.location_mode, profile.location_label, profile.service_area)
        return identity, company, location

    @staticmethod
    def _ai_response(completed_software: list[SellerProof]) -> str:
        base = (
            "AI is part of the tooling, but the important part is the system around it: evidence collection, verification, "
            "competitor selection, qualification, human review, and unsupported-claim prevention. I use AI to move faster, not to invent things."
        )
        if completed_software:
            return base + f" I can discuss recorded technical work such as {_external_label(completed_software[0])}."
        return base + " I won't claim an AI portfolio that is not recorded in Seller Proof."

    @staticmethod
    def _email_context(
        ranked: tuple[RankedProof, ...], same_niche: list[SellerProof], completed_client: list[SellerProof]
    ) -> tuple[str, tuple[SellerProof, ...]]:
        if same_niche:
            proof = same_niche[0]
            return f"You asked about my experience, so the most relevant share-approved example is {_external_label(proof)}.", (proof,)
        if completed_client:
            proof = completed_client[0]
            return (
                "You asked about my experience. I do not have share-approved same-niche client work recorded, so I’m sharing the closest "
                f"permitted completed example, {_external_label(proof)}, alongside the prospect-specific comparison rather than overstating it.",
                (proof,),
            )
        relevant = next((item for item in ranked if proof_is_completed(item.proof) and _externally_shareable(item.proof)), None)
        if relevant:
            return (
                f"You asked about my experience, so I’m including the closest share-approved recorded proof: {_external_label(relevant.proof)}.",
                (relevant.proof,),
            )
        return (
            "You asked about my experience, so instead of overstating it or disclosing internal-only proof, I’m sending the actual analysis I referred to.",
            (),
        )

    @staticmethod
    def _attachments(ranked: tuple[RankedProof, ...]) -> tuple[ProofAttachments, tuple[SellerProof, ...]]:
        send: list[str] = []
        sent_proofs: list[SellerProof] = []
        optional: list[str] = []
        do_not_send = ["Private Seller Pricing data", "Internal notes", "Unsupported or unverified results"]
        for item in ranked:
            proof = item.proof
            label = _external_label(proof)
            if proof_is_completed(proof) and item.score >= 60 and proof_allows_external_use(proof, USAGE_PUBLIC_URL):
                send.append(f"{label} — {proof.public_url}")
                sent_proofs.append(proof)
            elif proof_is_completed(proof) and item.score >= 50 and proof_allows_external_use(proof, USAGE_TESTIMONIAL):
                optional.append(label + " — testimonial sharing is permitted; attach the verified artifact manually")
            elif proof_is_completed(proof) and item.score >= 50 and proof_allows_external_use(proof, USAGE_CASE_STUDY):
                optional.append(label + " — obtain/share the verified artifact manually")
            elif proof.internal_only:
                do_not_send.append(f"Proof #{proof.id} — internal only")
            elif proof.status in {"In Progress", "Prototype", "Concept Only", "Unclassified"}:
                do_not_send.append(label + " unless its non-completed status is explicit and relevant")
        return ProofAttachments(tuple(send[:3]), tuple(optional[:3]), tuple(dict.fromkeys(do_not_send))), tuple(sent_proofs[:1])


def _safe_label(proof: SellerProof) -> str:
    claims = safe_claims(proof)
    if claims:
        return claims[0]
    return f"{proof.title} ({proof.status})"


def _externally_shareable(proof: SellerProof) -> bool:
    return any(proof_allows_external_use(proof, usage) for usage in _preferred_external_usages(proof))


def _preferred_external_usages(proof: SellerProof) -> tuple[str, ...]:
    return tuple(
        usage
        for usage in (USAGE_CLIENT_NAME, USAGE_PUBLIC_URL, USAGE_TESTIMONIAL, USAGE_CASE_STUDY, USAGE_REFERENCE)
        if proof_allows_external_use(proof, usage)
    )


def _external_label(proof: SellerProof) -> str:
    if proof_allows_external_use(proof, USAGE_CLIENT_NAME):
        # Naming permission is not permission to quote arbitrary safe-claim text,
        # testimonials, results, titles, or case-study material.
        return f"recorded work for {proof.client_name} ({proof.status})"
    niche = proof.niche.strip()
    if proof_allows_external_use(proof, USAGE_TESTIMONIAL):
        return f"a verified testimonial{f' from a {niche} project' if niche else ''}"
    if proof_allows_external_use(proof, USAGE_CASE_STUDY):
        return f"a verified case study or before-and-after{f' for {niche}' if niche else ''}"
    if proof_allows_external_use(proof, USAGE_PUBLIC_URL):
        return f"a verified public project example{f' for {niche}' if niche else ''}"
    if proof_allows_external_use(proof, USAGE_REFERENCE):
        return f"an approved client reference{f' from {niche}' if niche else ''}"
    return "an internal-only proof item"


def _proof_project_is_current(proof: SellerProof, projects: dict[int, SellerProject]) -> bool:
    if proof.project_id is None:
        return True
    project = projects.get(proof.project_id)
    return project is not None and bool(project.active) and str(project.counting_state or "legacy_unresolved") != "invalidated"


def _niche_match(proof_niche: str, prospect_niche: str) -> str:
    return niche_relation(proof_niche, prospect_niche)


def _location_response(mode: str, label: str, service_area: str) -> str:
    location = label.strip()
    area = service_area.strip()
    if mode == "Local":
        if location:
            return f"I'm based in {location} and work locally{f' across {area}' if area else ''}."
        return "I work locally, but my exact location is not configured."
    if mode == "Regional":
        return f"I work regionally{f' across {area}' if area else ''}{f' from {location}' if location else ''}."
    if mode == "Currently traveling":
        return f"I'm currently traveling{f' and normally based in {location}' if location else ''}; the service is remote-capable."
    if mode == "Remote-first service":
        return f"I provide the service remotely{f' from {location}' if location else ''}{f' for businesses in {area}' if area else ''}."
    if mode == "Remote":
        return f"I'm not claiming a local office; I work remotely{f' from {location}' if location else ''}."
    return "I don't want to imply a local office. My location and service model are not configured yet."
