from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import SellerProject, SellerProof

USAGE_CLIENT_NAME = "client_name"
USAGE_PUBLIC_URL = "public_url"
USAGE_TESTIMONIAL = "testimonial"
USAGE_CASE_STUDY = "case_study"
USAGE_REFERENCE = "reference"

PERMISSION_FIELDS = {
    USAGE_CLIENT_NAME: "share_client_name",
    USAGE_PUBLIC_URL: "share_public_url",
    USAGE_TESTIMONIAL: "share_testimonial",
    USAGE_CASE_STUDY: "share_case_study",
    USAGE_REFERENCE: "share_reference",
}


@dataclass(frozen=True)
class ProofDependencyAssessment:
    valid: bool
    reasons: tuple[str, ...]


def proof_snapshot(proof: SellerProof) -> dict[str, Any]:
    """Approval-time evidence survives later edits or deletion of the source row."""
    return {
        "id": proof.id,
        "project_id": proof.project_id,
        "grouping_state": proof.grouping_state,
        "proof_type": proof.proof_type,
        "title": proof.title,
        "status": proof.status,
        "niche": proof.niche,
        "description": proof.description,
        "client_name": proof.client_name,
        "completion_date": proof.completion_date,
        "public_url": proof.public_url,
        "verified": bool(proof.verified),
        "client_work": bool(proof.client_work),
        "software_ai_project": bool(proof.software_ai_project),
        "testimonial_available": bool(proof.testimonial_available),
        "measurable_result_available": bool(proof.measurable_result_available),
        "before_after_available": bool(proof.before_after_available),
        "provenance": proof.provenance,
        "safe_claims_json": _canonical_json_value(proof.safe_claims_json, []),
        "prohibited_claims_json": _canonical_json_value(proof.prohibited_claims_json, []),
        "internal_only": bool(proof.internal_only),
        "share_client_name": bool(proof.share_client_name),
        "share_public_url": bool(proof.share_public_url),
        "share_testimonial": bool(proof.share_testimonial),
        "share_case_study": bool(proof.share_case_study),
        "share_reference": bool(proof.share_reference),
        "artifact_state": str(getattr(proof, "artifact_state", "active") or "active"),
        "artifact_revision": int(getattr(proof, "artifact_revision", 1) or 1),
        "withdrawn_or_deleted_at": _iso(getattr(proof, "withdrawn_or_deleted_at", None)),
        "withdrawal_or_deletion_reason": str(getattr(proof, "withdrawal_or_deletion_reason", "") or ""),
    }
def proof_fingerprint(proof: SellerProof) -> str:
    encoded = json.dumps(proof_snapshot(proof), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_snapshot(project: SellerProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "project_revision": int(getattr(project, "project_revision", 1) or 1),
        "counting_state": str(getattr(project, "counting_state", "legacy_unresolved") or "legacy_unresolved"),
        "status": str(project.status or "Unclassified"),
        "client_work": bool(project.client_work),
        "active": bool(project.active),
        "invalidated_at": _iso(getattr(project, "invalidated_at", None)),
        "canonical_niche_id": str(getattr(project, "canonical_niche_id", "") or ""),
    }


def project_fingerprint(project: SellerProject) -> str:
    encoded = json.dumps(project_snapshot(project), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_proof_dependency(
    proof: SellerProof,
    usages: set[str] | tuple[str, ...] | list[str],
    *,
    project: SellerProject | None = None,
) -> dict[str, Any]:
    dependency = {
        "dependency_version": 2,
        "proof_id": int(proof.id),
        "fingerprint": proof_fingerprint(proof),
        "usages": sorted(set(usages)),
        "proof_snapshot": proof_snapshot(proof),
        "claim_evidence_fingerprint": hashlib.sha256(
            json.dumps(_canonical_json_value(proof.safe_claims_json, []), sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    if project is not None:
        dependency["project_id"] = int(project.id)
        dependency["project_fingerprint"] = project_fingerprint(project)
        dependency["project_snapshot"] = project_snapshot(project)
    return dependency


def body_fingerprint(subject: str, body: str) -> str:
    return hashlib.sha256(json.dumps([subject, body], ensure_ascii=False).encode("utf-8")).hexdigest()


def dependency_set_fingerprint(dependencies: list[dict[str, Any]]) -> str:
    if not dependencies:
        return ""
    encoded = json.dumps(dependencies, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_dependencies(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def assess_dependencies(session: Session, dependencies: list[dict[str, Any]]) -> ProofDependencyAssessment:
    reasons: list[str] = []
    for dependency in dependencies:
        proof_id = dependency.get("proof_id")
        if not isinstance(proof_id, int):
            reasons.append("A proof dependency is malformed.")
            continue
        proof = session.get(SellerProof, proof_id)
        if proof is None:
            reasons.append(f"Seller Proof #{proof_id} was deleted.")
            continue
        dependency_version = int(dependency.get("dependency_version", 1) or 1)
        current_fingerprint = proof_fingerprint(proof) if dependency_version >= 2 else _legacy_proof_fingerprint(proof)
        if dependency.get("fingerprint") != current_fingerprint:
            reasons.append(f"Seller Proof #{proof_id} changed after this draft was generated.")
            continue
        expected = make_proof_dependency(proof, []) if dependency_version >= 2 else _legacy_proof_dependency(proof)
        if (dependency.get("proof_snapshot") != expected["proof_snapshot"]
                or dependency.get("claim_evidence_fingerprint") != expected["claim_evidence_fingerprint"]):
            reasons.append(f"Seller Proof #{proof_id} has missing or inconsistent historical evidence.")
            continue
        usages = dependency.get("usages")
        if not isinstance(usages, list) or not usages or any(not isinstance(usage, str) for usage in usages):
            reasons.append(f"Seller Proof #{proof_id} has malformed disclosure requirements.")
            continue
        for usage in usages:
            if not proof_allows_external_use(proof, str(usage)):
                reasons.append(f"Seller Proof #{proof_id} no longer permits {str(usage).replace('_', ' ')} sharing.")
        project_id = dependency.get("project_id")
        if project_id is not None:
            if not isinstance(project_id, int):
                reasons.append(f"Seller Proof #{proof_id} has malformed project dependency metadata.")
                continue
            project = session.get(SellerProject, project_id)
            if project is None:
                reasons.append(f"Seller Project #{project_id} no longer exists.")
                continue
            if proof.project_id != project_id or dependency.get("project_fingerprint") != project_fingerprint(project):
                reasons.append(f"Seller Project #{project_id} changed after this draft was generated.")
                continue
            if dependency.get("project_snapshot") != project_snapshot(project):
                reasons.append(f"Seller Project #{project_id} has missing or inconsistent historical evidence.")
                continue
            if str(project.counting_state or "legacy_unresolved") == "invalidated" or not project.active:
                reasons.append(f"Seller Project #{project_id} is no longer valid for current use.")
    return ProofDependencyAssessment(not reasons, tuple(dict.fromkeys(reasons)))


def proof_allows_external_use(proof: SellerProof, usage: str) -> bool:
    if str(getattr(proof, "artifact_state", "active") or "active") != "active":
        return False
    if proof.internal_only:
        return False
    permission_field = PERMISSION_FIELDS.get(usage)
    if not permission_field or not bool(getattr(proof, permission_field, False)):
        return False
    if usage == USAGE_PUBLIC_URL:
        return bool(proof.public_url and proof.verified)
    if usage == USAGE_TESTIMONIAL:
        return bool(proof.testimonial_available and proof.verified)
    if usage == USAGE_CASE_STUDY:
        return bool((proof.before_after_available or proof.proof_type == "Case Study") and proof.verified)
    if usage == USAGE_REFERENCE:
        return bool(proof.client_work and proof.verified)
    if usage == USAGE_CLIENT_NAME:
        return bool(proof.client_name and proof.verified)
    return False


def _canonical_json_value(value: str, default: object) -> object:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def project_dependency_ids(session: Session, project_id: int) -> tuple[int, ...]:
    return tuple(session.scalars(select(SellerProof.id).where(SellerProof.project_id == project_id)))


def _legacy_proof_dependency(proof: SellerProof) -> dict[str, Any]:
    snapshot = _legacy_proof_snapshot(proof)
    return {
        "proof_id": int(proof.id),
        "fingerprint": _legacy_proof_fingerprint(proof),
        "proof_snapshot": snapshot,
        "claim_evidence_fingerprint": hashlib.sha256(
            json.dumps(_canonical_json_value(proof.safe_claims_json, []), sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _legacy_proof_snapshot(proof: SellerProof) -> dict[str, Any]:
    snapshot = proof_snapshot(proof)
    for key in ("artifact_state", "artifact_revision", "withdrawn_or_deleted_at", "withdrawal_or_deletion_reason"):
        snapshot.pop(key, None)
    return snapshot


def _legacy_proof_fingerprint(proof: SellerProof) -> str:
    encoded = json.dumps(_legacy_proof_snapshot(proof), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None else ""
