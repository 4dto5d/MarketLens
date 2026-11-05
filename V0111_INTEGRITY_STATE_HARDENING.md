# Local Presence Miner v0.1.11 — Integrity & State Hardening

This patch is based on the staged-enrichment v0.1.10/RC source and fixes the high-impact cross-module issues found in the 2026-08-28 forensic audit.

## Fixed

- Guided Call now opens on a neutral root state. It no longer records fake prospect interest before the prospect says anything.
- Practice Call and Live Call are isolated. Switching modes resets state; Practice cannot write a real interaction or DNC action.
- Guided Call Back now restores a deep snapshot of both visible path and structured conversation state.
- Suppression uses typed exact identities instead of substring matching. Lead-local DNC, exact phone, email, domain, Place ID and exact-name identities are supported.
- Manual add/edit/delete interaction paths now use the same adaptive regeneration pipeline so conversation corrections update Smart Offer/scripts.
- Lead Detail now uses the canonical side-effect-free adaptive sales planner instead of rebuilding an older offer independently.
- Competitor claim verification now uses one shared detector and recognizes wording such as nearby businesses, other local businesses, comparison set, and side-by-side comparisons.
- Verification flags are invalidated when the underlying evidence changes. Affected approved drafts are revoked automatically.
- Competitor reruns preserve operator notes/checklists for unchanged Place IDs and invalidate review when competitor identity or salient evidence changes.
- Failed rich Google refreshes preserve last-known-good phone/site/rating/review/hour/photo evidence and mark it stale instead of overwriting it with blanks/zeros.
- Stale Google rich data forces conservative Hold/research-first qualification until refreshed.
- Existing audit/competitor evidence is preserved during transient rich-detail refresh failures.
- Target radius is now enforced: the target city/ZIP is resolved to coordinates, Places search is biased around that center, and results are post-filtered by actual haversine distance.
- Radius is capped at 30 miles per search so it stays within the Places circle-bias limit; wider markets should use multiple nearby searches.
- Single Text Search runs are capped to the provider's documented 60-result ceiling.
- Google call estimates now include the center-resolution request.
- v0.1.11 now has a dedicated `.backup-before-v0111` migration backup and new rich-refresh provenance fields.
- Existing leads missing a Google Presence assessment are backfilled conservatively on v0.1.11 startup without fabricating unavailable evidence.
- Version metadata bumped to 0.1.11 in Python package, pyproject and Windows version resources.
- Competitor matching now separates true relevance from aspirational competitor strength, labels Match Quality, and does not force weak/irrelevant matches.
- Main search now commits each completed lead as a durable checkpoint so a later crash does not discard all earlier completed lead work.

## New regression coverage

Added dedicated tests for:
- exact suppression vs substring collision
- nearby-business verification wording
- failed Google refresh last-known-good preservation
- stale-data Hold behavior
- evidence-change verification invalidation and approval revocation
- manual public identity invalidation
- v0.1.11 backup/schema migration
- v0.1.11 Google assessment backfill
- radius boundary calculations

Updated Google Presence and Windows UI tests for center-resolution call accounting and neutral/live Guided Call behavior.

## Verification in this environment

- Python compileall: passed.
- Dedicated forensic-fix tests: 8/8 passed.
- Google Presence tests: 13/13 passed.
- Competitor matching + qualification regression checks passed.
- Broader non-PySide suite available here: 83 passed, 1 skipped.
- Actual old v0.1.10 source-created SQLite database -> patched v0.1.11 migration: passed; data preserved and `.backup-before-v0111` created.

## Still requires Codex/Windows verification

This environment does not have PySide6 or Ruff. Codex should run:
- Ruff
- complete pytest including all PySide6 UI tests
- Guided Call Practice/Live state isolation smoke test
- Guided Call Back rollback smoke test
- DNC suppression smoke test
- interaction edit/delete adaptive regeneration smoke test
- real Windows migration test from an actual user v0.1.10 DB copy
- Google Places radius request/mock test; real Safe Live Test remains blocked until billing activation
- PyInstaller clean build
- FileVersion/ProductVersion exactly 0.1.11
- clean-extracted EXE startup at 1366x768 and 1920x1080

## Not fully implemented in this patch

The full persisted batch-job engine with explicit `Resume Run`, `Retry Failed Only`, and safe cancel controls is still a P1 follow-up. This patch does add per-lead durable commits so completed leads survive a crash.
