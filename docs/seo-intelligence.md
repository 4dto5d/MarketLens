# Query-scoped SEO intelligence (unreleased)

This layer records evidence; it does not acquire paid Semrush data, scrape Google, send outreach, or guarantee better rankings. It supplements the existing intervention assessment, not Qualification. Organic, Maps and Places response-window coverage are separate concepts.

## Sources and authority

- Observed: recorded query/channel ranks and result windows, independently supplied competitor rows and external keyword estimates, current fetched page HTML/header facts, current Google public facts, referenced owner economics.
- Derived: visibility bands within measured windows, channel-specific competitor sets, overlap-aware service/intent clusters, possible sampled page overlap, source freshness/binding, historical comparable-position changes.
- Heuristic: query-intent safeguards, limited alias clustering, page targeting and qualitative capturability barriers. These are inspectable policies, not calibrated ranking probabilities or measured revenue.
- LLM: none is authoritative for these observations or numeric metrics.
- Missing: searcher-level proximity grids, complete index inclusion, live demand validation when API access fails, attributable conversions, genuine incrementality and ranking causality.

Google describes local ranking as relevance, distance and prominence; a single city/window cannot establish city-wide dominance. Accurate listing facts can help relevance, but a claimed ranking cause must not be inferred from one correlation. [Google local ranking guidance](https://support.google.com/business/answer/7091?hl=en).

Schema parsing checks valid JSON-LD and stated entities, not Google's complete rich-result eligibility or ranking impact. Correct markup does not guarantee rich-result display. [Google structured data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies).

## UI and offline workflow

Open a lead's **SEO Intelligence** tab. Export a research template populated from the existing controlled Query Universe. All generated queries start as hypotheses: intent/service/volume/ranks are UNKNOWN and source state is partial. Fill only source-backed fields and original capture times, then import JSON. No network request is made by import. The current research export is a projection for inspection, not the raw import format. Historical raw checkpoints and observation comparison are available through the service.

Optional command-line workflow uses the same boundary:

```powershell
python -m local_presence_miner.services.seo_research_cli --database C:\path\marketlens.sqlite3 --lead 1 template --output research.json
python -m local_presence_miner.services.seo_research_cli --database C:\path\marketlens.sqlite3 --lead 1 import-json --input research.json
python -m local_presence_miner.services.seo_research_cli --database C:\path\marketlens.sqlite3 --lead 1 show
python -m local_presence_miner.services.seo_research_cli --database C:\path\marketlens.sqlite3 --lead 1 import-semrush-csv --input keywords.csv --metadata metadata.json
```

The CLI requires an existing application database and persisted lead, not a newly invented dataset. API keys are not part of the import contract. CSV metadata contains `metadata` (original `observed_at` plus `source`), `local_ranks` keyed by exact CSV keyword, and optional `pages`. Semrush CSV country/database volume remains country volume, never allocated to a city. CSV Position is not relabeled as local rank. Local ranks need separate query/geography/window/reference evidence; the adapter requires consistent original observation times, rather than refreshing old metrics by import. Heterogeneous capture periods require separate checkpoints, not artificial redating. Only declared CSV headers are interpreted; no formula execution occurs.

Live Semrush discovery returned `no_api_units` during this implementation. Offline fixture tests do not establish live Semrush integration success. [Semrush keyword report contract](https://developer.semrush.com/api/v3/seo/keyword-reports/).

## Version-1 import contract

`schema_version=1`; subject `{place_id, website, geography, canonical_niche_id}` must exactly match the current lead context. Geography is the existing space-joined city/state (`Austin TX`). Source includes provider (`manual_serp` or `semrush`), report, database, geography, geographic resolution (`local`/`country`), status (`complete`/`partial`/`failed`), original observed timestamp, reference and demo flag. Queries retain service confirmation and references, intent and evidence basis, nullable volume/difficulty, organic and Maps ranks/windows/completeness separately, observed landing URL, channel-specific competitor rows and observed SERP features. All observed metrics remain supplied-source claims, not internally manufactured estimates.

Null is UNKNOWN; zero reported volume is a recorded zero estimate, not proof nobody searches. Invalid numeric strings, booleans used as numbers, non-finite values, duplicate/conflicting queries, unsupported fields and wrong-site landing/page URLs are rejected. All objects are bounded. Source/page/owner timestamps are retained, not refreshed on read. Latest failed/partial/demo/future/stale/mismatched checkpoint fails closed without reverting to an older success.

Current page facts may be attached from a fresh matching website audit: URL, title, H1s, metadata, canonical, robots/meta/header directives, status, indexability, word count, internal links, schema types/errors, confirmed service statements and references. The original audit timestamp and fingerprint remain attached. Existing audit booleans and maximum eight-page safe crawl stay unchanged. Bounded samples cannot prove missing pages, orphaning or cannibalization throughout a site. Possible overlap and schema problems call for validation, not automatic merges or SEO upsells.

### Loading-page eligibility correction

Response interpretation version **3** treats complete loading/status compositions (for example, `Loading... Please wait while the site loads.`) as uncertain. It does not keyword-filter business prose or services such as loading-dock repairs. Static branding and Service JSON-LD do not prove that the intended visible page has loaded.

Imported facts whose populated H1s describe only a loading/response shell remain uncertain even when the title is a business brand and word count is positive. The title remains a fallback shell indicator when H1s are absent. Genuine service headings and normal business facts remain useful. Existing import fields/schema and observation payloads are unchanged; no new inferred facts are stored. A projection cannot use a saved normal classification to override current loading-shell counterevidence.

Assessment semantics increment **6 to 7**, so existing commercial approval requires fresh evaluation. Earlier response versions are read conservatively from their original facts; historical text, source references, timestamps and original classification records are not rewritten. An uncertain page cannot independently support ordinary paid CTA/content/SEO scope. Separately supported listing-hours work can still survive. This is a bounded deterministic safeguard, not universal shell detection or verification of rendered content.

The initial L01 correction advanced response interpretation **3 to 4** and assessment semantics **7 to 8**. Independent composition replay found remaining false positives: branding-only captures, generic headings beside loading status, and static descriptive metadata rescuing imported shells. That interpretation is superseded below; its original stored output is not rewritten.

The final L01 correction advances response interpretation **4 to 5** and assessment semantics **8 to 9**. Fetched classification requires descriptive visible content outside headings and link/button labels; branding, schema, canonical metadata and static descriptions cannot supply that proof. Complete status compositions remain uncertain even beside a descriptive service heading or contact button. Genuine concise service prose, missing/branded H1s, and normal loading/maintenance/account language remain usable without a length threshold.

Structured imports do not contain body text or response proof. Branding, structural greetings/navigation, meta descriptions, schema and count do not establish descriptive support. A descriptive reported visible H1 can support bounded structured analysis when transport/content count is consistent; count can veto a heading-only record but never proves omitted body content. This is not certification of rendering or of omitted prose: a record with unreported contradictory body text cannot be reconstructed, and insufficient facts require recapture. No import field, schema, taxonomy or canonical Offer ID changes are introduced.

A matching version-5 normal capture can resolve insufficient structured facts through the existing versioned response proof, now issued only after descriptive capture content is supported. It cannot override explicit shell/non-normal evidence or invalid transport/count. Version-4 normal captures are not recertified to version 5 from static metadata alone. Raw payloads, prior classifications, source references and timestamps remain unchanged; approvals depending on assessment version 8 require reevaluation through the existing commercial dependency mechanism. Independently supported listing-hours corrections and narrow eligible SEO remain available. No database migration is required.

Economics accepts referenced, timestamped, service-specific owner/source reports only. Currency/customer/job values, margins and conversion probabilities are not estimated. Missing or stale economics remains UNKNOWN. Nonpositive recorded service margin calls for unit-economics validation before SEO spend, not a fabricated revenue forecast.

The L01 progress correction advances response interpretation **5 to 6** and assessment semantics **9 to 10**. Loading/progress compositions (percentages, resource counts, initialization and status messages) do not establish representative content. An active status clause with unfamiliar residual wording needs independently descriptive business prose; the failure to match a known status phrase is not itself proof. Genuine concise prose remains usable, including prose about loading equipment, maintenance and account management. A page that contains both status text and an actual descriptive business clause can still support bounded analysis.

New normal captures retain `content_proof` containing the normalized visible body text used by the classifier, outside branding/headings/controls. The current-capture exception rechecks this text; a normal label, reason and version alone cannot supply missing proof. Lossy imports still cannot submit response proof or invent omitted content. Old version-5 classifications stay historical and cannot use version-6 proof; their original facts can support bounded analysis only under the current structured-fact rules. Raw observations, timestamps/source references and human wording are not rewritten. Assessment-version dependencies invalidate superseded commercial approvals. No schema migration is required. The deterministic language rules are bounded capture checks, not a universal business-content or rendered-site certification.

## Decisions and downstream behavior

Service, intent, demand locality, current measured visibility, relevant landing-page facts and competitive/SERP barriers jointly determine qualitative advice. Overlapping aliases are not independent demand; member volumes are never added. Unknown competitors or material barriers require validation. High-volume informational/branded/unrelated queries do not justify SEO sales. Already-dominant measured windows support no SEO sale; that does not prohibit an independently evidenced contact repair or operational intervention.

An eligible near-breakthrough organic page with an observed targeting defect can map to **Conversion Tune-Up**, only its existing `local SEO title/meta/H1 fixes` deliverable. A missing service page, technical/indexability repair, Maps diagnosis or consolidation hypothesis remains a specific unpriced validation when no bounded matching catalog scope is established. Never substitute a full rebuild. Existing contact/operational precedence and human-confirmed offer/quote stickiness remain authoritative. Research alternatives cannot become proposal scope or owner-copy assertions on their own. Internal reports show the research projection separately; owner reports render the established selected commercial scope.

## Persistence and migration

Additive `seo_research_snapshots` table; no historical data backfill. Source JSON/hash, schema, source columns and exact frozen binding are checked on every current/historical read. Binding includes existing niche/query versions, target ZIP/radius and exact subject identity. SQLite migration takes a checked non-overwriting backup before creating the table. Idempotent triggers enforce append-only rows and protect referenced lead deletion/rekey even on legacy connections with global FKs off, including `INSERT OR REPLACE`. Normal ORM updates/deletes are also refused. No destructive table rebuild or new niche/Offer taxonomy.

Assessment semantics increment from 1 to 2; existing stored commercial snapshots are not rewritten. Fresh-use dependency checks detect changed semantic inputs/expired material evidence and revoke approval while retaining historical used/spoken/human text. Acquiring a valid checkpoint and commercial invalidation are one caller transaction; commercial refresh errors produce a review warning and safe staleness, not a false source acquisition failure.

History comparison requires consistent subject/schema/method/geography, complete compatible windows, valid hashes and nonfuture observations. Past expired observations remain usable as historical measurements, not current advice. Rank changes and competitor movements are descriptive, never causal lift or ROI. Predictions still need an owner-authorized intervention log and actual inquiry/conversion measurement for genuine outcome validation.
