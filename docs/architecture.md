# Architecture

Local Presence Miner is a Windows desktop app built with PySide6 and a local SQLite database.

## Layers

Query-scoped SEO research supplements (never relabels) the existing Places ledger. `seo_research_service` validates immutable source checkpoints against exact current business, website, market and registry binding; `domain.seo_intelligence` derives inspectable service/intent/channel opportunities. `seo_page_analysis` retains facts from the existing bounded safe HTML sample. The intervention evidence adapter consumes only current eligible research, preserving contact/operational precedence and canonical/human authority. Offline imports and history UI/CLI do not fetch data or send outreach. See [SEO intelligence](seo-intelligence.md) for contracts and limits.

- `domain`: dataclasses, enums, scoring, competitor matching, category catalog.
- `database`: SQLAlchemy schema, migrations, repository helpers.
- `services`: external integrations, auditing, offer generation, outreach, reports, mockups, exports.
- `ui`: PySide6 main window, dialogs, widgets, and background workers.

Network and audit operations run through background workers so the UI remains responsive.

Search acquisition has two durable outputs. The append-only Search Visibility ledger records the query context and every ordered Places discovery response before enrichment. The existing `search_run_leads` workflow then records only candidates selected for processing. This separation prevents discovery evidence from changing CRM, qualification, suppression, or outreach state.

Search Market is a separate read-only intelligence workflow. A `search_market_runs` row owns frozen `search_market_queries` generated from the canonical niche taxonomy. Its `lead_searches` wrapper exists only to reuse the database-wide single-flight lease and the visibility probe FK; it never creates processing memberships or changes Lead/CRM state. Each controlled query issues a discovery-only Places acquisition and appends its own `search_visibility_probes` attempt plus ordered `search_visibility_observations`. A partial run retains its completed query evidence. `search_market_analysis` derives coverage, query gaps, and repeated search-capture competitors without mutating the ledger or commercial decisions. The UI has a separate Search Market summary and Cluster → Query → Probe → Observation drill-down; the older Run History does not flatten these multi-query runs into its single-query list.

Search Market → Smart Offer fusion is a separate read-only projection (`search_offer_intelligence`). It consumes only the latest live run for the exact prospect Place ID and resolved canonical niche. Commercial findings require complete eligible query coverage; demo, partial, stale, future-dated, excluded, and wrong-context attempts remain UNKNOWN to the fusion layer. Local Places windows never establish organic rank, search volume, exact Maps rank, or demand. Findings retain run/query/probe IDs and current corroborating Google Presence or website-audit IDs. `build_current_offer_context` ranks canonical offer candidates before scope and seller pricing are calculated. An unconfirmed offer can be deterministically recomputed; offer history, approved/previously approved outreach, contact interactions, post-approval lifecycle state, or an explicit offer-selection event make the existing ID sticky and surface only an advisory alternative. Generated unapproved drafts and automatic pre-contact statuses are not human confirmation. Explicit acceptance through `accept_advisory_offer` records a validated canonical ID in the existing activity ledger and updates the Lead offer fields through the governed edit seam. The fusion never changes Qualification, contact readiness, Search Market rows, or outreach approval directly.

Future product outcome (not implemented here): website and Google Business Profile improvements should help customers improve discoverability in both Google Maps/local results and organic Google search, with separate longitudinal measurement to determine whether rankings actually improve. Current sampled Places windows are only visibility proxies and cannot prove either ranking gain or its cause.

Manually edited/revalidated outreach drafts also make the offer sticky. Automatic asset regeneration preserves these unapproved human drafts as exact review artifacts rather than replacing their body with a new generated script; generated unapproved drafts remain refreshable.

The existing Smart Offer tab shows a review/select action only when a locked offer has a differently ranked current alternative. Declining leaves all commercial state unchanged; acceptance is an explicit confirmation that calls the validated selection service and recalculates the current scope, pricing, and generated assets. This is a small action inside the existing lead workspace, not a new offer workflow or automatic outreach path.

The supported canonical mappings are deliberately narrow: repeated weak sampled Places coverage plus a separate current public-profile gap can support Google Presence Cleanup; a sampled service-query gap plus a current reachable website audit and service-content signal can support Full Local Authority Site without claiming organic rank; strong sampled Places coverage plus a separate current listing-presentation gap can support Google Presence Cleanup as a presentation intervention, not a visibility rebuild; and strong sampled coverage with a conversion signal can support Conversion Tune-Up. No Search Market finding alone authorizes a claim that Google rankings, customer demand, or revenue would improve.

The app is useful without API keys through demo mode and deterministic local generation.
