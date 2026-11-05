# Codex handoff — Local Presence Miner v0.1.10

Use this source ZIP as the ONLY baseline. Do not go back to v0.1.9 and do not recreate the Sales Copilot from scratch.

## Goal

Finish Windows/Qt verification and release packaging for **v0.1.10 — Adaptive Sales Copilot + Deep Audit** while preserving the source changes already present.

## First: inspect, do not rewrite

Read:
- `V0110_ADAPTIVE_SALES_COPILOT_NOTES.md`
- `2026-08-26__local-presence-miner__v01.09-call-email-tree-audit-v1.md` if supplied separately
- current source for `conversation_state_service.py`, `call_guide_service.py`, `guided_call_dialog.py`, `contact_interaction_dialog.py`, `website_auditor.py`, and `preflight_service.py`

## Required Windows verification / fixes

1. Install/use the project Windows environment and run Ruff over the whole repo. Fix lint only; do not flatten behavior.
2. Run the full pytest suite including all PySide6 tests. Update only tests that legitimately assert the old 0.1.9 version/behavior.
3. Verify migration from a real v0.1.9 database:
   - all existing data preserved
   - `.backup-before-v0110` created exactly once before new fields
   - conversation-state and contact-discovery checkpoint fields present
4. Exercise Guided Call at 1366×768 and 1920×1080:
   - Practice vs Live
   - Hold/Reject cannot enter Live mode
   - Quick/Normal/Detailed
   - breadcrumb
   - Back
   - response filtering
   - nested branches
   - rescue controls
   - Record Outcome prefilled with branch path/state
   - one-click DNC suppresses the lead and blocks outreach
5. Confirm recording a contact interaction with business goal/buyer questions and saving it regenerates Smart Offer + outreach drafts from that conversation state.
6. Verify the following real call branches are usable and not clipped:
   - gatekeeper / wrong person
   - provider
   - credibility
   - price / too expensive
   - send info
   - busy / booked out
   - no rebuild / existing-site repair
   - ownership / hosting / SEO / timeline / AI
7. Run a live Safe Test Search with max 5 businesses:
   - Preflight executes before Google work
   - max_results cannot exceed 5 in safe mode
   - no automatic mockups
   - normal live search remains unchanged when safe mode is off
8. Verify profit-aware category dropdown:
   - Top Opportunities first
   - Strong Opportunities second
   - full catalog remains searchable/selectable
   - explanation text updates
9. Verify deep website audit against at least 3 real sites:
   - homepage + bounded important internal pages
   - never becomes an unbounded crawler
   - page-level evidence persists
   - service/contact/trust sample findings make sense
   - broken/blocked child page does not fail the full audit
10. Verify batch public contact discovery:
   - Sales Priority ordering
   - completed leads skipped on rerun
   - failed leads can retry
   - one failing business does not kill batch
   - configured request delay remains honored
11. Verify Smart Offer consistency:
   - Lead Detail
   - generated scripts
   - report
   - proposal
   - lead package manifest
   all reflect the same current Smart Offer/context.
12. Run Demo Mode and verify no live external requests.
13. Build with PyInstaller and verify clean extraction/startup.
14. Verify Windows FileVersion and ProductVersion are exactly `0.1.10`.
15. Produce:
   - Windows release ZIP
   - clean source ZIP
   - SHA-256 for both
   - concise verification report with exact pass/fail counts.

## Important product constraints

- Growth Score is NOT Sales Priority.
- Review count is weighted evidence, never a hard minimum qualification cutoff.
- Hold/Reject are research-first unless manually overturned.
- Smart Offer is the single offer source of truth.
- Conversation history must influence later recommendations; do not reduce it to notes-only storage.
- Do not invent seller proof, client results, budget, owner identity, revenue loss, ranking gains, or conversion gains.
- Public contact discovery remains conservative and public-only.
- No automatic cold sending, form submission, SMS, dialing, robocalling, or AI voice.
- Keep Apollo/Hunter as future optional adapters; do not make them mandatory for this release.

## Acceptance scenarios

### A. Booked-out roofer
A high-priority roofer says: “We’re booked out. We want better-fit jobs.”
Expected:
- branch path stored
- capacity stored
- business goal stored as better-fit jobs
- Smart Offer moves toward service-fit/intake qualification rather than more-leads language
- next follow-up email carries that goal forward

### B. Gatekeeper
Reception says owner handles website but is unavailable.
Expected:
- correct gatekeeper response
- owner/decision-maker status can be recorded
- next action can be reach owner/send comparison
- no full pitch forced through receptionist

### C. Buyer question
Prospect asks whether they keep their domain and whether changing the site can hurt SEO.
Expected:
- buyer questions captured
- answer avoids guarantees
- later proposal/email can acknowledge those concerns

### D. DNC
Prospect says “Do not contact me again.”
Expected:
- one-click DNC in Live mode
- lead suppressed
- approved outreach revoked/blocked
- no future outreach-ready export

### E. Safe Live Test
Operator turns on Safe Live Test and requests 100 results / top 3 mockups.
Expected effective run:
- maximum 5 real businesses
- zero automatic mockups
- preflight first

Do not ship if any of A-E fail.
