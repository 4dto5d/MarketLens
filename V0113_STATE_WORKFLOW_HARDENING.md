# MarketLens Local v0.1.13a — State & Workflow Hardening Correction

> Freeze status: this document ships with the final v0.1.13a correction. Application/CLI identity is 0.1.13a and Windows numeric FileVersion/ProductVersion is 0.1.13.1. The identity freeze adds no database migration or product-logic change.

This release implements the seven fixes assigned to v0.1.13. It does not claim to resolve the separately deferred pricing, niche-taxonomy, evidence-fusion, call-tree, rendered-browser, or outcome-learning work.

## Canonical state model

`Lead` is the durable CRM entity keyed by its public place identity. `SearchRunLead` is the per-search membership/provenance record. Rediscovery can refresh public/machine evidence, Growth Score, Google Presence, Qualification Intelligence, and generated unapproved sales assets. It does not overwrite CRM status, suppression, operator notes, or the Lead's original legacy `search_id` compatibility pointer.

Each membership records candidate identity/name, discovery order and collected position, score context, new/rediscovered/legacy provenance, processing state, error summary, and discovery/processing timestamps. A membership can exist without a Lead ID when the candidate fails before a canonical Lead can safely be persisted.

## Search lifecycle

| State | Meaning |
| --- | --- |
| Running | The service-boundary single-flight slot is active and work is in progress. |
| Completed | Every candidate completed and no artifact warning was recorded. |
| Completed With Errors | The run remained operational, but at least one candidate or requested mockup failed. Successful candidates remain usable. |
| Partial | A systemic/job-wide failure stopped the run after at least one candidate checkpoint succeeded. |
| Failed | A systemic/job-wide failure stopped the run before any candidate succeeded. |
| Interrupted / Partial | The former process ended without finalizing the run, its database lease expired, and at least one candidate was checkpointed successfully. |
| Interrupted / Failed | The former process ended without finalizing the run, its database lease expired, and no candidate succeeded. |
| Legacy / Unknown | An incomplete pre-v0.1.13 run cannot be classified more precisely without inventing history. |

Counters are derived from memberships: total candidates, processed, succeeded, failed, skipped, new, and rediscovered. Pending memberships remain visibly unprocessed after a systemic stop.

Only one Search Workflow may target a database at a time across threads and separately launched processes. The service owns this rule; the desktop check is only an early friendly message. The workflow atomically claims a singleton SQLite lease with a unique owner/job ID, PID, acquisition time, heartbeat time, expiry, and attached Search Run ID. A background heartbeat renews ownership during long network/audit work. Clean completion deletes only the current owner's lease. SQLite `ON CONFLICT DO NOTHING` remains defense in depth for place-ID insert races without rolling back the per-lead transaction.

Startup and every newly acquired workflow reconcile orphaned `Running` rows only when they are not the run attached to a current unexpired database lease. Run creation and lease attachment commit in one SQLite transaction, so a second application cannot observe a committed active run without its ownership link. Recovery re-derives counters from memberships, retains Pending memberships, records an explicit interruption reason, and assigns `Interrupted / Partial` or `Interrupted / Failed` based on durable checkpoints.

## Failure boundary

An unexpected problem limited to a candidate—such as one audit/enrichment/qualification exception—is recorded on that membership. A missing/blank Google Place ID is rejected before canonical Lead creation, using the already-staged fallback membership identity to record `Missing canonical Google Place ID`; processing then continues. The transaction for other candidate-local failures rolls back, processing continues, and the final state is `Completed With Errors`. SQLAlchemy/database failures are treated as systemic, stop later processing, and result in `Partial` or `Failed`. Each successful candidate is committed before the next one starts.

## Outreach readiness

The same canonical validator is used for repository approval, UI copy, and outreach-ready export. In addition to the v0.1.12 sender, placeholder, verification, suppression, and Seller Proof rules, current readiness rejects:

- suppression, Opted Out, or Do Not Contact;
- a current public business status of `CLOSED_PERMANENTLY`;
- a nonempty Qualification snapshot currently classified Hold or Reject.

When readiness becomes invalid, each approved draft is copied exactly into approval history and unapproved with the reason. The draft body is not rewritten. If viability later improves, the draft remains unapproved until the operator reviews and approves it again.

## Artifact identity

Every per-lead artifact path begins with a readable business-name slug and a short SHA-256 identity derived from place ID (with persisted Lead ID as a fallback). This applies to reports, mockups, comparisons and competitor prompts, proposals, AI builder prompt bundles, static-site folders, package manifests, and lead-package ZIPs. Repeated generation for one lead is stable; distinct same-name/long-name leads do not collide. Legacy output is retained.

## Public response limits and SSRF invariants

Ordinary HTML responses are limited to 5 MiB and same-origin stylesheets to 1 MiB. The pinned transport requests an unbuffered response, streams 64 KiB chunks, enables urllib3 content decoding, and rejects the response as soon as the decoded total crosses the limit. A Content-Length check is only an early rejection; the decoded streamed count is authoritative.

The v0.1.12 protections remain: only public HTTP/HTTPS; no embedded credentials; local/special-use names and non-public/mixed DNS answers blocked before contact; numeric-IP pinning with TLS hostname verification; automatic redirects disabled; each redirect validated before contact; bounded redirect count; rendered-browser fetching still security-skipped.

## Migration and rollback

Before v0.1.13 columns/table changes, startup creates `local_presence_miner.sqlite3.backup-before-v0113` once when an older Lead/Search schema is detected. It uses SQLite's backup API so committed WAL content is included, writes through a temporary file, and never overwrites an existing backup.

Migration is additive and idempotent. Existing `Lead.search_id` links become `SearchRunLead` rows labelled `legacy_unknown`; the migration does not guess new-versus-rediscovered. Existing completed searches become `Completed`; older incomplete searches become `Legacy / Unknown`. Legacy `notes` is retained and copied only into an empty `operator_notes` field with `legacy_unknown` provenance. Existing operator notes are never replaced.

Rollback: close v0.1.13, preserve the current database separately, copy the non-overwritten `.backup-before-v0113` back to a new working database path, and open that copy only with the immutable v0.1.12 application artifact.

## Manual work and cold outreach

The operator must still configure real sender/compliance details; classify and permission Seller Proof; enter real offer outcomes; verify identity, operating status, contacts, audit/competitor claims, scope, price, and exact wording; choose the contact route; send email/forms and place calls manually; and record real outcomes/follow-ups. Suppression and opt-outs must be honored immediately.

No automatic sending, form submission, SMS blasting, calling, robocalling, AI voice, hidden-email harvesting, or unsupported enrichment was added. The real Google Places Safe Live Test remains pending external billing activation.

## Verification map

Focused evidence is in `tests/test_v0113_state_workflow.py`: rediscovery/status/note preservation, membership provenance, in-process and real cross-process lease contention, live-run protection during a second startup, heartbeat renewal, abrupt-process lease expiry and recovery, both interrupted terminal states, missing-Place-ID continuation, concurrent conflict-safe upsert, controlled candidate continuation, systemic stop, viability revocation/history/no-reapproval, artifact collision resistance, fixture and decoded-stream response caps, and idempotent migration/backup. The complete suite re-runs v0.1.12 SSRF, Seller Proof, approval/copy/export, Guided Call, builder-prompt, database, UI, and legacy migration regressions.
