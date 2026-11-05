# v0.1.16 Search Market core — implementation boundary

Search Market is a deterministic, AI-OFF-capable evidence and read-model layer. It extends the corrected v0.1.16 Search Visibility ledger; it does not redefine legacy Search Runs, Lead state, qualification, offers, outreach, or Guided Call.

## Evidence and identity

- Canonical niche resolution and a small controlled topic/alias list generate at most 24 local queries per run. Each query records its normalized text, stable SHA-256 identity, niche, topic/cluster, geography, intent, relevance, generation version and exact taxonomy rule. Unknown niches fail rather than triggering free-form expansion.
- A Search Market run freezes those query rows. A `lead_searches` wrapper provides the existing single-flight lease and probe foreign-key owner only. It creates no `search_run_leads` or Lead changes.
- Each query gets an independent Places Text Search discovery acquisition, immutable visibility probe, and ordered observation ledger. Detail enrichment is off for this workflow. An error becomes a failed probe for that query; completed sibling queries remain available. The query FK allows a separate attempt on retry and leaves historical visibility rows NULL/uninferred.
- Source ordinal and retained in-radius position remain separate. Demo rows are labeled and cannot qualify as live. Acquisition attempt ID is distinct from the comparability fingerprint and strategy version.

## Read-model rules

For each frozen query, use only its latest attempt. A query is eligible only if the attempt has the correct live/demo source and status, current acquisition strategy, exact query/linkage, intact observation count, and a timestamp no older than 30 days and not in the future. Truncated, failed, partial, stale, unexecuted or inconsistent attempts are `UNKNOWN`. A provider-returned prospect that was filtered from the retained window is `excluded`, not absent.

Coverage denominator = eligible `present + absent` queries. Numerator = eligible `present`. `UNKNOWN` and `excluded` are reported but excluded from the denominator. Cluster coverage uses the same rule. A business can be a Top Search Competitor only after at least two distinct eligible query captures where the prospect is absent. Sort deterministically by gap-query count, then summed 1–3 taxonomy relevance, top-10 source-ordinal count, total appearances, cluster breadth and stable Place ID. This is an explainable ordering of observed query capture, not a causal Google ranking model. Query-gap output labels each observed fact separately from its bounded interpretation.

Every statement is scoped to the collected Places Text Search windows. Nothing here establishes exact Maps/Local Pack rank, organic rank, search demand, CPC, true market share, or why the provider selected a result.

## Migration and rollback

The additive migration creates `search_market_runs` and `search_market_queries`, adds nullable `market_query_id` to visibility probes, and records a zero-inference marker. It creates one checked SQLite backup before touching an existing pre-Search-Market database, does not overwrite it on rerun, and checks integrity and foreign keys. No existing visibility probe is assigned a market query. A rollback to an older app should begin by preserving the current DB and restoring a reviewed pre-migration backup, not deleting new tables or guessing old evidence semantics.

## Explicitly deferred

Organic SERP provider; Semrush; exact Maps/Local Pack rank; geo-grid scanning; search volume/CPC; scheduled monitoring/alerts; automatic Search Market → Smart Offer or qualification routing; Guided Call integration; visual/photo intelligence; autonomous outcome learning; AI-generated query universe as authoritative truth. Real live Places evidence remains dependent on the user's API/billing readiness and is not simulated by demo fixtures.
