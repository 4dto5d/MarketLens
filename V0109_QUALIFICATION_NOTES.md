# Local Presence Miner v01.09 — Qualification Intelligence

FILE_STUB: 2026-08-26__local-presence-miner__v01.09-qualification-intelligence-v1

This source patch builds on the v0.1.8 outreach-engine + competitor-grounded builder-prompt baseline and bumps the application version to 0.1.9.

## What changed

- Added Sales Priority (0–100), separate from Growth Score.
- Added qualification classes: Reject, Hold, Qualified, High Priority, Demo Priority.
- Added qualification confidence: Low, Moderate, Strong.
- Stores factor breakdown, positive signals, disconfirmers, unknowns, and a recommended next action.
- Review count is a nonlinear activity signal, never a hard minimum.
- Added prospect-side commercial-potential heuristic without claiming a business can pay.
- Qualification considers:
  - documented online opportunity,
  - public business activity,
  - competitor disadvantage,
  - contactability,
  - commercial-potential proxy,
  - evidence quality,
  - disconfirmers such as likely chain control, weak ratings, inactivity, or an already-strong site.
- Lead list, dashboard, review queue, top mockup selection, CLI ordering, and outreach batch export now prefer Sales Priority.
- Contact discovery and competitor-review changes recalculate qualification.
- Existing leads with no qualification snapshot are recalculated on startup/preflight.
- Added v0.1.8 database backup before v0.1.9 qualification columns are added.
- Outreach batch CSV now includes Sales Priority, qualification class, and qualification confidence.

## Important behavior test

Demo roofing search produced:

- Neighborhood Roof Repair — 12 reviews — Growth 100 — Sales Priority 88 — Demo Priority
- Old Town Roofers Co — 7 reviews — Growth 88 — Sales Priority 66 — High Priority
- Fast Response Roofers — 76 reviews — Growth 24 — Sales Priority 60 — Qualified
- Modern Pro Roofers — 214 reviews — Growth 12 — Sales Priority 44 — Hold

This confirms that review volume helps establish activity but does not overwhelm opportunity, reachability, niche economics, or competitor evidence.

## Tests run in this environment

- Python compileall: passed.
- Non-UI regression suite: 46 passed, 1 skipped.
- Dedicated v0.1.9 qualification tests passed, including:
  - low review count is weighted rather than hard-filtered,
  - a healthy 12-review roofer can rank High/Demo Priority,
  - 0 reviews alone does not force Reject,
  - large review volume does not rescue a low-opportunity prospect,
  - v0.1.9 migration fields and backup are created.
- End-to-end Demo Mode SearchWorkflow qualification run: passed.

## Still needs Windows verification

This Linux environment does not have PySide6 or Ruff installed. Codex/Windows should run:

1. Ruff.
2. Full pytest suite including PySide6/UI tests.
3. Existing v0.1.8 database migration smoke test and confirm `.backup-before-v0109` creation.
4. Lead table/dashboard/review queue visual smoke test at 1366×768 and 1920×1080.
5. Contact discovery then confirm Sales Priority recalculates.
6. Competitor review then confirm Sales Priority recalculates.
7. PyInstaller build and EXE startup/version check for 0.1.9.

## Not included yet

- Apollo integration / decision-maker enrichment.
- Hunter integration.
- Automated email sending or dialing.
- Full competitor-matching v0.1.9 overhaul beyond the existing matcher.
- Adaptive learning from historical outreach outcomes.
