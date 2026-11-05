# Codex Handoff — v0.1.11 Integrity & State Hardening

Use the attached v0.1.11 source ZIP as the only baseline. Do not revert to the earlier v0.1.10 staged-enrichment source.

The source already contains the forensic integrity fixes. Your job is Windows/Qt verification, defect repair if verification exposes a real issue, and release packaging — not redesigning the product logic.

## Preserve these behaviors

1. Guided Call starts neutral; no fake `Interested in evidence` state at startup.
2. Practice Call cannot persist CRM interactions, suppress a lead, or leak state into Live Call.
3. Back restores the full prior conversation-state snapshot.
4. DNC/suppression uses exact typed identities, never arbitrary substring matching.
5. Add/edit/delete interaction changes regenerate adaptive Smart Offer and unapproved scripts.
6. Lead Detail, Call Mode, reports/proposals and outreach all use the canonical adaptive planner.
7. Nearby-business/comparison wording requires Competitors Reviewed verification.
8. Evidence changes invalidate dependent verification flags and revoke affected approved drafts.
9. Failed rich Google refresh preserves last-known-good evidence and marks it stale; stale data is Hold/research-first.
10. Target radius is genuinely enforced by coordinate center + distance post-filter.
11. Release identity is 0.1.11 and migration creates `.backup-before-v0111` before Google/rich-refresh schema changes.
12. Competitor relevance is separate from competitor strength; weak matches are not forced.

## Required Windows acceptance tests

### Call integrity
- Open Guided Call: state is neutral.
- Practice: click several branches, attempt Record Outcome/DNC; no DB write and no suppression.
- Switch Practice -> Live; state/path reset to neutral.
- Live: choose `Booked out -> Better-fit jobs`, then Back, choose a different interpretation; no Better-fit state survives.
- Record real interaction, edit it, then delete it; Smart Offer and drafts must follow the remaining current history each time.

### Suppression
- Create `Smith Roofing` and `Goldsmith HVAC`.
- Suppress Smith Roofing by exact business identity.
- Smith is blocked; Goldsmith remains contactable.
- Exact discovered email/phone/domain suppression still blocks the matching lead.

### Verification
- Draft text `I compared your public site against 3 nearby businesses.` must require `Competitors Reviewed`.
- Verify competitors, replace one competitor, confirm competitor/outreach verification is reset and affected approved drafts are unapproved.
- Verify website/audit, change the website URL, confirm dependent verification resets.

### Google refresh
- Seed a lead with rich Google values.
- Simulate a transient rich-detail failure.
- Old website/phone/rating/review/hour/photo values remain intact.
- `google_rich_data_stale = true`, refresh error is recorded, qualification is Hold/research-first.
- Later successful refresh updates values and clears stale/error state.

### Radius
- Use mocked center + places at 9 and 11 miles for a 10-mile search.
- 9-mile candidate survives; 11-mile candidate is excluded.
- Verify ZIP center is used when Target ZIP is populated.
- UI radius must not exceed 30 miles per single search.

### Migration/version
- Start from a real 0.1.10 DB copy.
- Confirm `.backup-before-v0111` exists before mutation.
- Existing leads/interactions/pricing/verification data survive.
- Missing Google assessments are backfilled conservatively.
- No fabricated zero/missing evidence for old leads without rich fields.
- `__version__`, pyproject, FileVersion and ProductVersion = 0.1.11.

### General
- Ruff clean.
- Full pytest clean.
- 1366x768 and 1920x1080 UI smoke.
- PyInstaller release build and clean-extracted EXE startup.
- No secrets, runtime DBs, logs or user data in source/release ZIP.

## Important remaining P1

Do not claim full resumable batch-job support yet. Per-lead durable checkpoints are present, but explicit Resume Run / Retry Failed Only / safe cancel UI is still future work unless you choose to implement and fully test it as a separate scoped change.
