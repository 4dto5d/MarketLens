# Data Model

`seo_research_snapshots` is an additive append-only lead-bound source ledger. It preserves normalized JSON, SHA-256, schema/source/observed columns and frozen business/website/geography/ZIP/radius/registry binding. No data is inferred from legacy ranks or booleans. Checked backups precede installation; SQLite guards protect immutability (including replacement) and referenced lead identity even on FK-off legacy connections. Derived current advice fails closed on metadata/hash/context/freshness mismatch; raw history and compatible expired past observations remain historical, not current commercial authority. See [SEO intelligence](seo-intelligence.md).

SQLite is the source of truth.

Core tables:

- `lead_searches`: search criteria and completion status.
- `search_visibility_probes`: immutable acquisition attempts with separate attempt and comparability fingerprints, capture-strategy version, collection status, source, and result-window limits for a Search Run. Existing v0.1.16 rows remain legacy-context evidence and are not silently upgraded to current claim eligibility.
- `search_market_runs`: prospect Place ID, geography/niche and query-universe version, mode and lifecycle for a bounded multi-query run. Its `lead_searches` parent is a storage/lease anchor only.
- `search_market_queries`: frozen deterministic query identity, cluster/topic, geography, intent, provenance, relevance and generation version. One query may have multiple visibility-probe attempts; historical probes retain a NULL market-query FK.
- `search_visibility_observations`: ordered provider-response evidence, including retained and excluded results; positions are collected Places proxies only.
- `search_run_leads`: the processing membership for shortlisted candidates; kept separate from the complete visibility observation ledger.
- `leads`: public business details, CRM status, targeting fields, scores, offer fields, suppression flag.
- `website_audits`: structured audit checks, metrics, strengths, weaknesses.
- `competitors`: selected local competitors and reasons.
- `outreach_drafts`: editable draft text and approval state.
- `suppression_entries`: values that disable contact approval.
- `activity_log`: durable local activity history.
- `contact_interactions`: permanent inbound/outbound contact timeline with outcomes, notes, linked drafts, and follow-ups.
- `seller_profiles`: the private operator identity and experience start date; no manually invented experience score.
- `seller_proof`: structured private proof inventory with type, niche, verification, completion date, and optional value/URL.
- `offer_history`: private offer snapshots with recommended and actual asks, negotiation/close amounts, outcomes, lost reasons, and at-offer evidence.
- `app_settings`: reserved for future DB-backed settings.

Generated CSV files are exports, not the application database. `offers.csv` and `seller_proof.csv` are private operator exports and are never added to prospect lead packages.

Search Market coverage is a read projection, not a Lead field: present / (present + absent) over fresh complete comparable query windows. UNKNOWN, truncated, stale and prospect-excluded windows are excluded from the denominator. Search Competitors and gaps are derived from retained query observations, never from existing competitor-strength rows or reviews.

`CurrentOfferContext.offer_fusion` is populated only when a complete, live, current Search Market run yields an eligible finding. It carries the original and selected canonical Offer IDs, selection source, sticky reason, ranked candidates with component scores, evidence references, and uncertainty. Only a materially changed canonical choice and its winning evidence enter the current-plan pricing/outreach dependency fingerprint; an advisory alternative or approval lock narration cannot by itself stale an approved draft. The full fusion remains inspectable on the live context. No database migration or new Offer ID is involved. Business-type recommendations expose the shared taxonomy's curated sales-fit prior separately from observed eligible Places query gaps; actual-business candidates require an existing matching Lead and eligible gap evidence. Neither surface claims demand, qualifies a lead, or authorizes contact.

An explicit human offer switch uses the existing `activity_log` (`offer_selected` event) plus the canonical Lead offer fields. When an offer is commercially acted on, the planner recovers the acted-on canonical ID from that event or the relevant offer-history/outreach/contact commercial snapshot, rather than treating a later automatic Lead scoring hint as the human's chosen offer. These are validated against the existing Offer registry; no additional schema is introduced.

Offer semantic compatibility is at `OFFER_REGISTRY_VERSION = 2`. The version now covers both canonical presentation and the bounded, per-offer conversation-framing envelope; it is included in `CurrentOfferContext` and its fingerprint so a version-1 commercial snapshot cannot masquerade as current advice. Prospect-stated goals may reorder and reword only scope already inside the selected canonical product family. Optional empty scope components are excluded before deduplication and pricing; historical owner-authored text remains historical. This is a semantic provenance change, not a database migration or a new Offer ID.
