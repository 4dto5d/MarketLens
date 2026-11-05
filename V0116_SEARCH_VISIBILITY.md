# MarketLens Local v0.1.16 — Search Visibility Evidence

## Contract

Search Visibility is an internal, query-scoped evidence ledger. It records what the supported Google Places Text Search endpoint returned for one exact query context. It does not claim an exact Google Maps or Map Pack rank.

`LeadSearch` remains the workflow run. `SearchRunLead` remains the selected-candidate processing membership. The new `SearchVisibilityProbe` and `SearchVisibilityObservation` records preserve discovery evidence without changing canonical Lead, CRM, qualification, suppression, commercial, or outreach state.

## Position semantics

- `source_position` is the ordered item position in the collected provider response window before local filtering.
- `retained_position` is the compacted position after duplicate, coordinate, and radius checks.
- `disposition` explains whether the result was accepted, duplicated, missing coordinates, or outside the requested radius.
- Demo observations are labeled `demo_fixture` and are never live evidence.
- Failed and partial probes cannot support an absence claim.
- A capped/truncated collection can describe observed results, but cannot prove that an unobserved business was absent beyond the collected window.
- Historical `Lead.search_position` and `SearchRunLead.search_position` values are not backfilled as canonical visibility history.

## Comparability

The context fingerprint includes source, exact normalized query, niche, location, ZIP, resolved center, radius, and requested result limit. Only matching fingerprints are comparable. v0.1.16 displays history and provenance; it does not calculate rank trends or automated alerts.

## Migration

The migration is additive and creates a non-overwriting `.backup-before-v0116` recovery point before adding the two tables. It records a marker only after SQLite integrity and foreign-key checks pass. Existing memberships and positions are preserved, but zero historical visibility observations are inferred.

## Explicitly deferred

- Exact Maps or Map Pack rank claims
- Grid/georank scans
- SERP scraping or private Google Business Profile access
- Scheduled monitoring, alerts, or keyword discovery
- Visibility-driven automatic scoring, qualification, offers, or outreach
- Retrospective visibility-history reconstruction
