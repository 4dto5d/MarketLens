# Changelog

## Unreleased — query-scoped SEO intelligence

- Add immutable, exact-subject SEO checkpoints and separate organic/Maps research, query-aware competitors, conservative clusters, local-demand provenance and qualitative capturability.
- Retain bounded per-page targeting/indexability/header-robots/schema/service facts without changing legacy audit checks or safe crawl behavior.
- Add fail-closed offline Semrush CSV/JSON imports, lead-level research/history UI and CLI; live Semrush access remains unavailable without API units.
- Integrate eligible narrow targeting repair into existing Smart Offer; preserve no-sale, validation, human stickiness, historical text and independent pricing. Uncovered catalog scopes remain unpriced rather than forcing a rebuild.
- Add checked additive SQLite backup/migration, append-only/FK guards and comparison integrity; assessment semantics advance to 2. See `docs/seo-intelligence.md`.

## Unreleased — evidence-bound Smart Offer assessment

- Separate legacy triage from a qualitative intervention assessment with current evidence, alternatives, hypotheses, metrics, falsifiers and explicit unknowns.
- Support validation, insufficient-evidence and no-sale outcomes without fabricated paid scope or pricing; preserve human-selected canonical history and approval/text safeguards.
- Remove GrowthScore-based service-cost/ask inflation and comparison selection; label catalog cost bands as non-ROI estimates.
- Align Smart Offer, Guided Call, outreach, owner reports and proposals with the same selected scope; version commercial semantics to 3 without a schema migration.
- Keep Search Market's frozen-evidence contract and canonical Offer IDs unchanged. See `docs/smart-offer-intervention-assessment.md`.

## v0.1.16 — Search Visibility Evidence

- Added a separate Search Market intelligence surface: deterministic taxonomy-derived query universe/clusters, bounded multi-query acquisition, fresh complete-window coverage, repeated-capture Top 3 Search Competitors, and fact/interpretation-separated query gaps.
- Kept every Search Market query and retry as separately inspectable immutable visibility evidence; Search Market does not propagate into commercial state.
- Added an additive, backed-up Search Market schema migration that leaves historical visibility probes unlinked/UNKNOWN.
- Added an append-only, query-scoped visibility probe and observation ledger without changing canonical Lead or Search Run membership semantics.
- Preserved every ordered Places discovery response, including duplicates, missing-coordinate results, and results outside the requested radius, before shortlist enrichment.
- Kept provider-response position separate from the retained in-radius position and continued to label both as collected Places proxies rather than exact Maps or Map Pack ranks.
- Tagged demo observations so they cannot be mistaken for live evidence and left all legacy positions conservatively unconverted.
- Added a backed-up, additive, idempotent migration with integrity and foreign-key checks.
- Added visibility evidence summaries and an observation drill-down to Run History.
- Tightened owner-facing position wording to describe only the specific collected Places result batch.
- Corrected post-audit evidence semantics: unaudited linked websites remain unknown; stale rich Google fields and stale competitor snapshots cannot add current strength or gap points.
- Separated acquisition-attempt identity from comparable query context, versioned the capture strategy, and added a fail-closed structured absence-claim gate.
- Disabled four Search Criteria controls that are not implemented as filters; Deep Prospecting is labeled as enrichment breadth, not richer per-business fields.

## v0.1.15 — Guided Call Integrity

- Preserved factual conversation state when current commercial guidance is refreshed, while keeping stale guidance blocked at use boundaries.
- Enforced fresh website evidence and separate owner-spoken/owner-copied permissions at the actual reply boundary.
- Added distinct channel-neutral Other openings and blocked stale/internal/root reply copying.
- Removed unsupported comparison/finding language, ambiguous DNC inference, and neutral-question skepticism inference.
- Added stable Guided Call tree, node, strategy, response-version, snapshot, fingerprint, rescue, and ordered usage identity.
- Distinguished displayed, copied, and explicitly marked-used replies; copying alone is not recorded as actual use.
- Required explicit truthful interaction outcomes and retained No answer only as an operator-selected value.
- Added a conservative, non-inventive v0.1.15 B2 migration and backup boundary for existing B1 databases.
- Made tested-tree identity deterministic, excluded generated verification output, and included byte counts in manifest rows.

## v01.13a — State & Workflow Correction

- Identified the corrected release unambiguously as MarketLens Local v0.1.13a; Windows uses numeric FileVersion/ProductVersion 0.1.13.1 and records the human identity as a special build.
- Pinned the Windows runtime to the clean-package-verified PySide6 6.7.3 release after newer 6.10.3 and 6.11.2 wheels reproduced a pre-existing packaged `QtGui` loader failure; no application or business logic changed.
- Replaced process-local search authority with an atomically claimed, database-backed lease containing unique owner/job identity, PID, Search Run ID, heartbeat, and expiry.
- Reconciled orphaned `Running` searches after lease expiry as `Interrupted / Partial` or `Interrupted / Failed`, based only on durable membership results.
- Rejected missing/blank Google Place IDs as candidate-local failures before canonical Lead creation, while continuing later candidates.
- Added real separate-process contention/death tests, malformed-candidate continuation coverage, and an idempotent `.backup-before-v0113a` migration safeguard.

## v01.13 — State & Workflow Hardening

- Separated canonical Lead state from per-run discovery membership while preserving legacy compatibility fields.
- Preserved CRM status, suppression, and operator notes across rediscovery; machine notes now have a separate field.
- Added an atomically claimed database-backed Search Workflow lease with unique owner/job identity, PID, heartbeat, and expiry, so separately launched MarketLens instances cannot run overlapping searches against one SQLite database; conflict-safe lead upserts remain as defense in depth.
- Added truthful Search Run lifecycle states, counters, timestamps, candidate provenance, and human-readable errors.
- Startup and pre-run recovery now reconcile orphaned `Running` rows after abrupt process death as `Interrupted / Partial` or `Interrupted / Failed`, without touching a run protected by a current database lease.
- Candidates missing a canonical Google Place ID are recorded as failed memberships and skipped; later candidates continue. Other ordinary candidate failures retain durable per-lead checkpoints, while systemic database failures stop as Partial/Failed.
- Added current viability to approval/copy/export gating, with immutable approval history and no silent reapproval.
- Added readable, stable, collision-resistant lead artifact paths across reports, prompts, proposals, sites, and packages.
- Streamed and capped decoded public HTTP/CSS responses without weakening the v0.1.12 SSRF protections.
- Added an idempotent, WAL-safe `.backup-before-v0113` migration, conservative legacy-note provenance, and membership reconstruction.
- Kept real Google Places Safe Live Test pending billing activation; Demo Mode and mocked fixtures remain the tested fallback.

## v01.11 — Credibility Engine + Integrity-Hardened Adaptive Sales Copilot

- Added a structured Credibility & Proof ledger with explicit Completed, Completed + Verified, Completed + Testimonial, Completed + Measurable Result, In Progress, Prototype, Concept Only, and Unclassified states.
- Added client-work, software/AI-project, testimonial, measurable-result, before/after, provenance, safe-claim, and prohibited-claim fields without silently promoting legacy proof.
- Added seller identity type, truthful local/regional/remote service wording, location label, and service-area configuration.
- Added prospect-specific proof relevance ranking and a compact WHY YOU card with explicit claims to avoid.
- Expanded Guided Call's skeptical first 60–90 seconds with Identity, Legitimacy, Relevance, Permission, Evidence, Discovery, Offer, Price, Objection, and Next Action support.
- Added deep branches for identity/company/location, experience, trust, examples, references, legitimacy, access/payment boundaries, differentiation, and AI skepticism.
- Limited the default call cockpit to five likely early responses while preserving Search all, Other, I don't know what they mean, and low-risk rescue actions.
- Added structured credibility conversation memory and proof-aware follow-up, interested-reply, report-delivery, proposal, and report framing.
- Added a safe proof-attachment recommender that separates Send, Optional, and Do Not Send artifacts.
- Proof additions/edits/deletions now regenerate dynamic call guidance and unapproved drafts; existing human-approved outbound remains immutable unless an evidence-integrity rule explicitly revokes approval.
- Added a dedicated `.backup-before-v0111-credibility` migration safeguard for already integrity-hardened v0.1.11 databases.
- Added 15 focused credibility/integrity tests; the complete Windows suite now contains 126 passing tests before packaging.
- Listener Mode, live transcription, intent detection, and outcome learning remain reserved for v0.2.x; v0.1.11 is Extra High deterministic decision support, not Ultra learning.

- Integrity hardening: isolated Practice/Live call state, neutral Guided Call startup, full Back-state rollback, exact typed suppression identities, adaptive regeneration after interaction edits/deletes, canonical Smart Offer planning across surfaces, stronger competitor-claim verification, evidence-change verification invalidation, last-known-good Google preservation, enforced radius filtering, and a dedicated v0.1.11 migration backup/backfill.
- Added separate public Google Presence Strength and Opportunity scores with Low / Moderate / Strong evidence confidence.
- Persisted observable target and competitor Google fields, conservative unknowns, human-readable provenance, and derived-vs-source-backed status.
- Added cost-aware staged Google Places retrieval: cheap discovery fields now feed a deterministic Preliminary Candidate Score before any rich Place Details calls.
- Added configurable Google Data Depth modes: Economy enriches up to 8 shortlisted candidates, Balanced up to 20, and Deep Prospecting up to 40. Safe Live Test still caps discovery at five and enriches all five.
- Added a pre-run upper-bound API-call estimate showing Text Search and Place Details request counts separately.
- Fixed a large-batch correctness defect where unrequested discovery-stage website, rating, review, phone, hours, and photo fields could be interpreted as observed missing values. Unrequested values now remain Unknown and unshortlisted candidates do not enter deep qualification.
- Shortlisting now uses only discovery-mask evidence: operating status, category/type relevance, location/service-area evidence, collected result position, conservative chain filtering, and category opportunity weighting.
- If rich details fail for a shortlisted candidate, the lead remains Hold / Research-first, keeps its rich fields Unknown, and does not receive automatic adaptive sales assets.
- Review text and price fields remain excluded by default.
- Added public competitor comparisons for rating, review volume, linked website, hours, and other supported fields without claiming exact Maps ranking or private profile access.
- Integrated Google Presence Opportunity into Qualification Intelligence while preserving review count as a nonlinear signal rather than a hard minimum.
- Added evidence-selected Smart Offer modes: Website-only, Google Presence-only, Website + Google Presence, and Research-first.
- Fed Google evidence into cold/follow-up email language, call guidance, reports, proposals, and Lead Detail.
- Added four offline Demo Mode scenarios and deterministic mocked Places fixtures for strong/weak cross-surface combinations.
- Added additive v0.1.10 database compatibility for Google assessments and public snapshots.
- Replaced remaining `datetime.utcnow()` calls with timezone-aware UTC timestamps.
- Added regression coverage for non-enriched unknowns, non-positional shortlisting, depth caps, API-call estimates, Safe Live Test behavior, and the New Search controls.
- The real five-business Google Places Safe Live Test remains pending external Google Cloud billing activation; it was not removed, weakened, or represented as passed.

## v01.09 — Qualification Intelligence

- Added Sales Priority (0–100) separately from Growth Score.
- Added qualification classes: Reject, Hold, Qualified, High Priority, Demo Priority.
- Added Low / Moderate / Strong qualification confidence plus positive signals, disconfirmers, unknowns, and next action.
- Review count is a nonlinear activity signal, not a hard minimum. Small but healthy local businesses can rank highly when the rest of the evidence is strong.
- Qualification incorporates opportunity, public business activity, competitor disadvantage, contactability, commercial-potential proxy, and evidence quality.
- Added automatic v0.1.8 database backup before qualification columns are added.
- Existing leads with no qualification snapshot are recalculated on startup/preflight.
- Lead list, dashboard, review queue, top mockup selection, and outreach batch ordering now prefer Sales Priority.
- Added Extra High Adaptive Outreach Intelligence driven by the shared qualification, evidence, competitor, and seller-pricing context.
- Added a lead-specific Smart Offer with targeted scope, Easy-Close / Recommended / Stretch amounts, rationale, boundaries, and human checks.
- Added interested, price, existing-provider, and not-now email reply scripts alongside the existing cold-email sequence.
- Expanded Guided Call into recursive if/then branches for budget, value, competing quotes, timing, approval, capacity, fit, intake, and guarantee objections.
- Regenerates the Smart Offer and unapproved human-review drafts after contact discovery, manual competitor review, or offer-field changes.
- Blocks Do Not Contact / Opted Out leads across planning, approval, and export; Hold / Reject qualification snapshots stay in needs-review exports.
- Hardened public-contact discovery against hidden DOM/CSS emails, including bounded same-origin stylesheet review and fail-closed external CSS behavior.
- Preserves a manually selected contact route across public-contact refreshes and honors the full configured batch request delay.
- This is not Ultra outcome learning: contact outcomes remain structured local evidence for a future adaptive-learning release.

## v01.08 — Operator Experience

- Added competitor-grounded, evidence-safe AI website-builder prompts with platform-neutral, Lovable, and Canva Website variants; live site exports and lead packages now carry the actual prompt files instead of only a generic one-line instruction.
- Rebuilt the Windows workspace around daily lead-review and sales actions with a responsive light UI, grouped navigation, clearer empty states, compact tables, status badges, and action-oriented dashboards.
- Added a Lead Detail pre-contact cockpit with verified lead context, grounded opening angle, seller-calibrated pricing, proof, and direct call/email/contact actions.
- Added an audit evidence workspace with revenue-leak cards, desktop/mobile evidence links, and per-finding manual review states.
- Added a side-by-side competitor matrix, selection rationale, screenshots when locally available, manual relevance confirmation, and manual competitor replacement.
- Added structured manual contact-outcome capture: outcome, response signals, objection, notes, follow-up, and linked draft. These records are a future-learning foundation; v01.08 does not make adaptive predictions from them.
- Reworked Seller Pricing Intelligence around separate Project Value, recommended ask, real offer outcomes, proof inventory, comparable-deal analysis, and private local data boundaries.

## v01.07 — Seller Pricing Intelligence

- Separated prospect-side Project Value from the seller-specific Easy-Close, Recommended, and Stretch asks.
- Added persistent private Seller Profile, Proof & Experience, and Offer History records with structured outcomes and lost reasons.
- Added niche-, scope-, value-, and recency-aware comparable-offer analysis that does not treat no-response losses as price evidence.
- Added transparent proof confidence, starter/core/expanded scope options, negotiation metrics, and small-sample suppression.
- Added a private Pricing Intelligence workspace with overview, offer history, proof inventory, comparable deals, performance, and CSV export.
- Integrated grounded pricing language into Owner Mode and call drafts, with non-pressure objection responses and verified-proof matching.
- Added explicit Record as Presented Offer and manual override workflows while preserving the original recommendation and immutable evidence snapshot.
- Separated customer-selected proposal pricing from private internal analytics and prevented draft, approved, and internal proposals from overwriting each other.
- Added a pre-v01.07 database backup and comprehensive regression coverage for persistence, recency, privacy, migration, and pricing integrity.

## v01.06 — Integrity & Release

- Fixed contact-summary corruption when older interactions are edited or the newest interaction is deleted.
- Canonicalized interaction timestamps and follow-up dates, and added a pre-v01.06 database backup before normalization.
- Exposed optional outreach-draft links in Contact History and enforced lead ownership for those links.
- Added minimum verification requirements for outreach approval and direct Approved-to-Contact status changes.
- Automatically revokes affected draft approvals when required verification is later unchecked or a lead is suppressed.
- Embedded available desktop/mobile evidence screenshots into internal HTML reports without exposing local file paths.
- Hardened rendered Edge audits with bounded stabilization, partial/timed-out/navigation-failed states, and evidence snippets.
- Made a missing PageSpeed key an explicit configuration-required state; failures do not abort lead search.
- Added inline Pipeline follow-up scheduling, clearer Review Queue states, and HTML export for Industry Intelligence.
- Added regression coverage for integrity, gating, migration, evidence portability, and release-version consistency.

## v01.05 — Verification & Workflow

- Wired PageSpeed, rendered browser verification, desktop/mobile screenshots, top-N mockups, and bounded audit concurrency to their visible controls.
- Added explicit not-run, unavailable, failed, and successful service states; service failure no longer becomes a zero score or aborts a search.
- Added separate raw-HTML and rendered-browser evidence, screenshot persistence, and Lead Detail access.
- Renamed unsupported Visual Aesthetic scoring to Presentation Readiness and standardized Collected result position wording.
- Added per-lead verification checklists, review progress/filtering, manual competitor approval, and Owner Mode call-verification guidance.
- Added permanent ContactInteraction history with add/edit/delete, follow-up updates, and activity logging.
- Rebuilt Pipeline as a due-first daily workspace with lead opening and quick status actions.
- Expanded Industry Intelligence with denominators, audit metrics, profile distributions, and small-sample suppression.
- Fixed static-site chat closed state and toggle; added Concept status metadata and a production-readiness checklist.
- Added database backup before v01.05 migration, redacted diagnostics export, version metadata, and a Windows app icon.
- Updated the auditor User-Agent dynamically from application version 0.1.5.

## v01.04

- Added an editable Lead & CRM tab for business details, ownership, tags, notes, contact history, outcomes, and follow-up dates.
- Added validated `YYYY-MM-DD` follow-up/contact dates and a one-click **Mark contacted today** action.
- Turned Review Queue into a real filtered queue for New and Needs Review leads.
- Added explicit outreach approval and unapproval controls; editing approved text resets approval.
- Blocked outreach approval for suppressed leads and recorded approval changes in the activity log.
- Made saved Settings active immediately without restarting the app.
- Protected saved Google Maps and PageSpeed API keys with Windows user-scoped encryption.
- Added regression coverage for outreach approval safety and encrypted API-key round trips.
- Added Owner Mode with an evidence-grounded sales brief and explicit unknowns instead of invented business-size or decision-maker claims.
- Added Industry Intelligence that summarizes observed revenue-leak patterns by niche and collected market, with sample-size disclaimers.
- Renamed user-facing audit and scoring language to Business Opportunity Analysis, Growth Score, and Revenue Leaks.

## v01.03

- Added first-run setup, pipeline, and pricing pages to the desktop app.
- Added owner-facing proposal generation.
- Added paid-style static website exports with hero video slot, quote form markup, pricing section, mobile CTA, local schema placeholder, and optional chat bubble UI.
- Added fair pricing tiers for audits, proposals, static sites, conversion sites, review-request systems, human-managed chat, and real AI answer bubbles.
- Added richer competitor evidence columns for notes, website URL, and checklist fields.
- Added CLI flags for `--proposals` and `--site-exports`.
- Added proposal and site export files to lead ZIP packages.
- Updated README with v01.03 usage, pricing, hero-video, and chat/AI add-on guidance.

## v01.02

- Added Windows-only PySide6 desktop scaffold.
- Added SQLite persistence with SQLAlchemy.
- Added offline demo search workflow.
- Added deterministic lead scoring with target signals for no website, weak website, low local position, and review-growth opportunity.
- Added exhaustive small-business category dropdown source.
- Added starting offer builder for website/Google presence packages.
- Added transparent no-track-record outreach approach.
- Added HTML report and mockup generation.
- Added CSV export and suppression enforcement.
- Added Windows run/build PowerShell scripts.
# v0.1.12 — MarketLens Local Pass 1 Integrity & Security Hardening

- Added structured, approval-time Seller Proof dependencies and immutable approval-history snapshots.
- Revokes only approvals dependent on edited/deleted proof; unknown historical approvals move to Needs Review with exact text preserved.
- Added conservative proof defaults and five independent, deny-by-default sharing permissions.
- Centralized approval, copy, and export checks for suppression, verification, sender/compliance fields, placeholders, and proof validity.
- Added DNS-validated, IP-pinned public transport with pre-contact redirect checks for Website Audit and Contact Discovery.
- Added private-target validation before PageSpeed delegation and disabled automatic redirects for fixed Google APIs.
- Security-skipped rendered-browser network auditing and changed prospect URL actions to copy-only pending full subresource interception.
- Preserved WAL content in the idempotent `.backup-before-v0112` migration backup.
- Renamed user-facing product identity to MarketLens Local while retaining data/module compatibility.
- Deferred project/proof-artifact grouping and all Pass 2+ redesign work.
