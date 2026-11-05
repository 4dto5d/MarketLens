from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__", ".build-venv", ".venv", "venv", "build", "dist", "out"}
GENERATED_FILE_NAMES = {
    "CHATFIX_SOURCE_MANIFEST.json",
    "GITHUB_SOURCE_BUNDLE_README.md",
    "GITHUB_SOURCE_FILE_MANIFEST.json",
}
MATRIX = {
    "Windows build uses the clean-package-verified PySide6 runtime": [
        "test_windows_build_uses_verified_pyside_runtime_version"
    ],
    "Canonical application, CLI, and visible desktop identity is v0.1.16": [
        "test_canonical_and_package_versions_are_v0115",
        "test_cli_version_reports_corrected_identity",
        "test_main_window_and_sidebar_report_corrected_identity",
    ],
    "Windows and release-facing metadata distinguish the corrected build": [
        "test_windows_metadata_distinguishes_corrected_executable",
        "test_release_documentation_uses_corrected_human_identity",
        "test_windows_fixed_and_string_versions_are_current_v0115",
    ],
    "Rediscovery preserves CRM status, suppression, operator notes, and both run memberships": [
        "test_rediscovery_preserves_crm_state_and_operator_notes"
    ],
    "One search per database is enforced across threads and separate processes": [
        "test_single_flight_blocks_second_service_run_for_same_database",
        "test_single_flight_blocks_a_separate_process_and_preserves_its_running_state",
    ],
    "Abrupt process death releases the lock and stale Running rows recover truthfully": [
        "test_abrupt_process_death_releases_lock_and_startup_recovers_run",
        "test_startup_reconciles_orphaned_running_search",
    ],
    "Concurrent unique-place insert resolves to one canonical lead": [
        "test_concurrent_unique_place_upsert_is_conflict_safe"
    ],
    "Candidate-local failure continues with honest membership counters": [
        "test_candidate_failure_continues_and_records_honest_counters",
        "test_missing_candidate_place_id_is_failed_locally_and_later_candidate_continues",
    ],
    "Systemic database failure stops and records Partial state": [
        "test_systemic_database_failure_stops_run_and_marks_partial"
    ],
    "Current viability revokes exact approval history and never reapproves silently": [
        "test_current_viability_revokes_exact_approval_and_never_reapproves"
    ],
    "Qualification Reject preserves revoked copy through automatic asset refresh": [
        "test_qualification_reject_preserves_revoked_copy_during_asset_refresh"
    ],
    "Harmless lead evidence update preserves valid approval": [
        "test_harmless_evidence_update_preserves_valid_approval"
    ],
    "Lead artifact names are stable and collision resistant": [
        "test_artifact_slug_is_stable_and_collision_resistant"
    ],
    "Colliding readable lead names produce isolated packages without contamination": [
        "test_colliding_readable_names_export_isolated_lead_packages"
    ],
    "Remote fixture and decoded-stream responses are capped": [
        "test_safe_request_caps_fixture_transport_response",
        "test_pinned_transport_caps_streamed_decoded_body",
    ],
    "v0.1.13 backup, conservative notes, and legacy membership migration are idempotent": [
        "test_v0113_migration_backup_membership_and_notes_are_idempotent"
    ],
    "v0.1.13a lease-table migration creates an immutable v0.1.13 backup": [
        "test_v0113a_lease_migration_creates_non_overwriting_backup"
    ],
    "Supporting proof deleted revokes approval and retains tombstone": ["test_supporting_proof_deletion_revokes_and_preserves_dependency_history"],
    "Supporting proof downgrade or material change revokes approval": ["test_supporting_proof_material_change_revokes_exact_approval"],
    "Unrelated proof change preserves valid exact approval": [
        "test_new_unrelated_proof_regenerates_unapproved_but_preserves_approved_draft",
        "test_truly_unrelated_proof_change_does_not_stale_commercial_plan",
    ],
    "Historical approval with unknown dependencies moves to Needs Review": ["test_legacy_approved_unknown_dependencies_migrate_once_without_body_loss"],
    "Manual edits cannot reuse stale dependencies": ["test_manual_edit_requires_fresh_explicit_dependency_review_and_reapproval"],
    "Deleted proof is not silently replaced": ["test_deleted_proof_is_not_silently_replaced"],
    "Malformed or unknown dependency metadata fails closed": ["test_malformed_or_unknown_dependency_metadata_blocks_approval"],
    "New proof defaults do not create client experience": ["test_new_proof_defaults_do_not_create_client_experience"],
    "Unknown permission and public URL alone deny external use": ["test_verified_public_url_alone_remains_internal_and_never_emitted"],
    "Name, URL, testimonial, case-study, and reference permissions are independent": [
        "test_disclosure_permissions_are_independent_and_internal_only_overrides"
    ],
    "Client-name permission cannot disclose another claim type": ["test_client_name_permission_does_not_quote_unpermitted_claim_or_url"],
    "All approval entry paths reject placeholders/status bypass": ["test_unresolved_sender_is_blocked_at_all_approval_entry_points"],
    "Missing sender/compliance values block approval": ["test_missing_sender_compliance_blocks_valid_body"],
    "Valid sender is allowed and exact suppression remains absolute": ["test_valid_sender_approves_and_exact_suppression_still_blocks"],
    "Batch export rechecks canonical approval and explains skips": ["test_batch_export_rechecks_current_sender_and_explains_skip"],
    "Neutral voicemail fallback is not approval-ready without identity": ["test_voicemail_uses_neutral_fallback_and_requires_configured_identity"],
    "Ordinary public destination and public redirect are allowed": ["test_ordinary_public_redirect_and_website_audit_remain_enabled"],
    "Direct private/special/unsupported destinations are rejected before contact": [
        "test_private_special_and_unsupported_destinations_rejected_before_transport"
    ],
    "Private, mixed, and empty DNS resolutions are rejected": ["test_hostname_private_mixed_or_empty_dns_rejected_before_contact"],
    "Public redirect to private is rejected before private hop for GET and HEAD": ["test_public_redirect_to_private_blocked_before_next_hop"],
    "DNS pinning preserves TLS identity and disables redirects/retries": ["test_dns_pinning_preserves_tls_identity_and_disables_automatic_redirects"],
    "Rendered browser cannot bypass policy": ["test_rendered_browser_operation_is_explicitly_skipped_without_network"],
    "PageSpeed validates target and does not follow API redirect": ["test_pagespeed_blocks_private_input_and_api_redirects_before_contact"],
    "Google fixed endpoints reject arbitrary host and redirects": ["test_google_api_requests_cannot_follow_redirect_or_use_arbitrary_endpoint"],
    "Stylesheet redirect to private is rejected before private hop": ["test_stylesheet_redirect_private_is_blocked_before_fetch_and_email_is_withheld"],
    "GUI approval buttons use canonical validator and remote URL action is copy-only": [
        "test_gui_approval_buttons_share_validator_and_url_copy_does_not_navigate"
    ],
    "v0.1.12 backup includes committed WAL and is not overwritten": ["test_migration_backup_captures_committed_wal_and_is_not_overwritten"],
    "Per-lead durable commit continues after candidate-local failure": [
        "test_completed_search_continues_after_candidate_local_failure"
    ],
    "Stale Google values are preserved but excluded from current scoring": [
        "test_failed_rich_refresh_preserves_last_known_good_google_data",
        "test_stale_rich_review_values_do_not_change_current_scores",
    ],
    "Competitor relevance is not competitor website strength": ["test_competitor_relevance_is_not_used_as_website_strength"],
    "Interaction correction regenerates current adaptive assets": ["test_interaction_correction_regenerates_adaptive_draft_from_current_memory"],
    "Practice/Live isolation and Back rollback remain intact": [
        "test_guided_call_back_restores_structured_state",
        "test_practice_call_cannot_record_or_leak_into_live",
    ],
    "Canonical Smart Offer remains shared across surfaces": ["test_extra_high_plan_combines_qualification_evidence_offer_and_live_pricing"],
    "Review count is not a hard qualification minimum": ["test_low_review_business_is_viable_and_service_area_is_not_penalized_as_missing_address"],
    "Guided Call replies retain stable identity and distinguish display, copy, and actual use": [
        "test_b2_call_tree_has_stable_authored_unique_identity",
        "test_b2_display_copy_and_actual_use_are_distinct_and_persisted",
        "test_b2_guided_call_capture_rejects_tampering_and_noncontiguous_sequence",
    ],
    "Meaningful interactions require an explicitly confirmed truthful outcome": [
        "test_b2_blank_outcome_cannot_persist_from_repository_or_dialog"
    ],
    "Tested-tree identity excludes generated output and records byte counts": [
        "test_b2_tested_tree_manifest_is_deterministic_and_excludes_generated_output"
    ],
}


def included_files(root: Path, *, excluded_roots: tuple[Path, ...] = ()) -> list[Path]:
    root = root.resolve()
    resolved_exclusions = tuple(path.resolve() for path in excluded_roots)
    included: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if set(relative.parts) & EXCLUDED_PARTS:
            continue
        resolved = path.resolve()
        if any(resolved == excluded or resolved.is_relative_to(excluded) for excluded in resolved_exclusions):
            continue
        if relative.name in GENERATED_FILE_NAMES or relative.suffix.casefold() == ".log":
            continue
        included.append(path)
    return sorted(included, key=lambda path: path.relative_to(root).as_posix())


def manifest(root: Path, *, excluded_roots: tuple[Path, ...] = ()) -> dict[str, dict[str, int | str]]:
    root = root.resolve()
    return {
        path.relative_to(root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in included_files(root, excluded_roots=excluded_roots)
    }


def manifest_digest(files: dict[str, dict[str, int | str]]) -> str:
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run(command: list[str], cwd: Path) -> dict[str, object]:
    started = datetime.now(UTC)
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {
        "command": command,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
        "output": result.stdout,
    }


def matrix_from_junit(path: Path) -> list[dict[str, object]]:
    cases = []
    for case in ElementTree.parse(path).iter("testcase"):
        name = case.attrib["name"]
        status = "PASS" if not list(case) else "FAIL"
        cases.append((name, status))
    rows = []
    for requirement, expected in MATRIX.items():
        matches = [(actual, status) for actual, status in cases if any(actual == item or actual.startswith(item + "[") for item in expected)]
        result = (
            "PASS"
            if matches
            and all(status == "PASS" for _, status in matches)
            and all(any(actual == item or actual.startswith(item + "[") for actual, _ in matches) for item in expected)
            else "FAIL"
        )
        rows.append({"invariant": requirement, "tests": [actual for actual, _ in matches], "result": result})
    rows.append(
        {"invariant": "One project with several proof artifacts counts once", "tests": [], "result": "DEFERRED PASS 2 per later CYA execution guardrails"}
    )
    return rows


def source_inventory(pattern: re.Pattern[str]) -> list[dict[str, object]]:
    rows = []
    for path in included_files(ROOT):
        if path.suffix != ".py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                rows.append({"file": path.relative_to(ROOT).as_posix(), "line": number, "text": line.strip()})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    initial = manifest(ROOT, excluded_roots=(output,))
    baseline_initial = manifest(args.baseline)
    checks = {
        "baseline_pytest": run([args.python, "-m", "pytest", "-q"], args.baseline),
        "baseline_ruff": run([args.python, "-m", "ruff", "check", "."], args.baseline),
        "baseline_mypy": run(
            [
                args.python,
                "-m",
                "mypy",
                "--cache-dir",
                str(output / "baseline-mypy-cache"),
                "local_presence_miner",
                "app.py",
            ],
            args.baseline,
        ),
        "final_pytest": run([args.python, "-m", "pytest", "-q", f"--junitxml={output / 'FINAL_PYTEST.xml'}"], ROOT),
        "final_ruff": run([args.python, "-m", "ruff", "check", "."], ROOT),
        "final_mypy": run(
            [
                args.python,
                "-m",
                "mypy",
                "--cache-dir",
                str(output / "final-mypy-cache"),
                "local_presence_miner",
                "app.py",
            ],
            ROOT,
        ),
    }
    for name, result in checks.items():
        (output / f"{name.upper()}.txt").write_text(str(result["output"]), encoding="utf-8")
    after = manifest(ROOT, excluded_roots=(output,))
    baseline_after = manifest(args.baseline)
    matrix = matrix_from_junit(output / "FINAL_PYTEST.xml")
    approval = source_inventory(re.compile(r"\.approved\s*=|set_outreach_approval\(|APPROVED_TO_CONTACT"))
    network = source_inventory(re.compile(r"requests\.(?:get|post|request)|safe_request\(|\.goto\(|webbrowser\.open"))
    result = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "checks": checks,
        "tested_tree_unchanged_during_checks": initial == after,
        "baseline_unchanged_during_checks": baseline_initial == baseline_after,
        "tested_tree_manifest": after,
        "tested_tree_sha256": manifest_digest(after),
        "invariant_matrix": matrix,
        "approval_path_inventory": approval,
        "network_path_inventory": network,
    }
    (output / "VERIFICATION_RESULTS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    tested_tree_manifest = {
        "file_count": len(after),
        "aggregate_tree_sha256": manifest_digest(after),
        "files": [{"path": path, **metadata} for path, metadata in after.items()],
    }
    (output / "TESTED_TREE_MANIFEST.json").write_text(
        json.dumps(tested_tree_manifest, indent=2), encoding="utf-8"
    )
    (output / "APPROVAL_PATH_INVENTORY.json").write_text(json.dumps(approval, indent=2), encoding="utf-8")
    (output / "NETWORK_PATH_INVENTORY.json").write_text(json.dumps(network, indent=2), encoding="utf-8")
    baseline_mypy_count = int(re.search(r"Found (\d+) errors?", str(checks["baseline_mypy"]["output"])).group(1))
    final_mypy_count = int(re.search(r"Found (\d+) errors?", str(checks["final_mypy"]["output"])).group(1))
    (output / "MYPY_BASELINE_COMPARISON.md").write_text(
        "# Mypy baseline comparison\n\n"
        f"- Authoritative pre-closure baseline: {baseline_mypy_count} pre-existing errors.\n"
        f"- Final v0.1.16 tree: {final_mypy_count} errors.\n"
        f"- Regression result: {'PASS' if final_mypy_count <= baseline_mypy_count else 'FAIL'}.\n",
        encoding="utf-8",
    )
    md = [
        "# Invariant-to-test matrix",
        "",
        "Machine-derived from the final JUnit report.",
        "",
        "| Invariant | Exact tests exercised | Result |",
        "|---|---|---|",
    ]
    for row in matrix:
        md.append(f"| {row['invariant']} | {'<br>'.join(row['tests']) or 'None by explicit scope decision'} | {row['result']} |")
    (output / "INVARIANT_TO_TEST_MATRIX.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    expected = all(int(checks[name]["exit_code"]) == 0 for name in ("baseline_pytest", "baseline_ruff", "final_pytest", "final_ruff"))
    expected &= int(checks["final_mypy"]["exit_code"]) == 1 and int(checks["baseline_mypy"]["exit_code"]) == 1
    expected &= final_mypy_count <= baseline_mypy_count
    expected &= initial == after and baseline_initial == baseline_after and all(row["result"] != "FAIL" for row in matrix)
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
