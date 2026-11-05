# Local Presence Miner v0.1.10 — Adaptive Sales Copilot + Deep Audit

FILE_STUB: 2026-08-27__local-presence-miner__v01.10-adaptive-sales-copilot-deep-audit-v1

This source builds directly on the clean v0.1.9 Qualification + Adaptive Outreach release.

## Implemented in this patch

- Persistent conversation state on contact interactions:
  - contact name/role
  - decision-maker status
  - business goal
  - capacity status
  - buyer questions
  - commitments
  - exact branch path
  - next action
- Conversation-state aggregator so the current Smart Offer and scripts can reuse what the prospect actually said.
- Canonical side-effect-free Smart Offer planner used across Lead Detail/script regeneration/report/proposal paths.
- Follow-up emails can address a known contact name and carry forward a stated business goal/buyer questions.
- Full Guided Call architecture upgrade:
  - Practice Call vs Live Call
  - Quick / Normal / Detailed reply lengths
  - breadcrumb + Back
  - response filtering
  - rescue controls
  - one-click Do Not Contact in Live mode
  - structured call-path capture into outcome recording
  - Hold/Reject live-call blocking (practice remains available)
- Expanded call-tree coverage:
  - gatekeepers / wrong decision maker
  - existing provider diagnosis
  - credibility / proof questions
  - price / value / budget / competing quote
  - send-information diagnosis
  - timing / busy / booked-out
  - website repair vs rebuild
  - domain ownership
  - hosting/recurring costs
  - SEO/migration risk
  - self-editing
  - timeline
  - AI-use questions
- Resumable/checkpointed public contact discovery with per-lead complete/failed state and Sales Priority ordering.
- Preflight service for database/output writeability, Google Places key, PageSpeed status, rendered Edge availability, sender identity, and audit concurrency.
- Safe Live Test option: real data, max 5 businesses, no automatic mockups.
- Profit-aware business category picker: Top Opportunities, Strong Opportunities, then full catalog, with an explanation of the heuristic.
- Bounded multi-page website audit (up to 5 high-value pages) covering contact path, service depth, trust proof, title/indexability/canonical sample, and image-alt coverage with page-level evidence.
- v0.1.9-aware lead package manifest fields: Sales Priority, qualification class/confidence, qualification snapshot, Smart Offer, and contact-discovery state.
- Report/proposal templates now display the Smart Offer rather than presenting the legacy Starting Offer as the main recommendation.
- v0.1.10 migration backup target: `.backup-before-v0110`.

## Local verification performed here

- `python -m compileall -q local_presence_miner tests` passed.
- Non-UI regression suite: **58 passed, 1 skipped**.
- PySide6 is not installed in this environment, so Qt/UI runtime tests cannot be executed here.
- Ruff is not installed in this environment.

## Deliberately still manual

No automatic cold email sending, contact-form submission, SMS, dialing, robocalling, or AI voice was added.

## Windows verification still required

See `CODEX_HANDOFF_V0110.md`.
