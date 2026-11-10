# Guided opportunity workflow and Pass 5A–5C integration

November 4, 2026. Research-to-software mapping, not commercial validation.

## What exists and what this sprint connects

| Research input | Existing software seam | Bounded connection in this sprint | Still separate / not implemented |
| --- | --- | --- | --- |
| 5A: worthwhile business, evidence, competing explanations | Search Workflow, Qualification, website/Google/SEO evidence, intervention candidates and falsifiers | Guided Opportunity records discovery route, dated source/reference, actual observation, competing explanations and owner question | No automatic niche rank import, no buyer-budget or demand inference, no change to Qualification |
| 5B: service, deliverables, economics and delivery | Canonical offer registry, CurrentOfferContext, Seller Pricing, Sales Evidence and Delivery Packet | Candidate scope; acquisition route; delivery, research/sales, travel and learning/revision/support hours; hourly planning value; direct costs; platform assumptions and alternatives | No automatic conversion of research prices to quotes; no cost-driven canonical switch; no new canonical IDs; no payment or migration execution |
| 5C: owner confirmation, objections, decision, next action and outcome | ContactInteractionDialog, conversation assertions, owner strategy, Guided Call, CRM, commercial disposition, follow-up permission | Links from the same worksheet to those existing screens; explicit owner-reported attribution; saved next action | Worksheet attribution is not an owner-strategy assertion or scope approval. Record actual conversations through Record Contact. No fictional objections/outcomes imported |

Sources inspected: the supplied `marketlens-gpt-6-pro-high-audit_20261104_1719.md`, particularly lines 22550–22614 (three lanes and research gates), 21969–21984 (O01–O16 comparison), and 22815–22865 (revised sensitivities and assumptions); current `offer_registry.py`, `intervention_assessment.py`, owner strategy, delivery review and contact interaction implementations. The source report's conflicting niche rankings remain conflicting research inputs.

## Three discovery routes

1. **Publicly observable problem:** record the exact dated page/listing observation and reference. Reproduce it in the existing evidence workflow before making a diagnosis.
2. **Public clue requiring owner confirmation:** record the clue and other explanations. Ask whether it matters or is intentional/already handled. A clue is not confirmed lost revenue.
3. **Private problem reported in conversation:** retain attribution and actual words or identified paraphrase. Do not imply the app discovered an internal problem by crawling a website.

The route is operator-selected, not an automatic qualification or contact-eligibility override. Owner-reported need does not prove platform feasibility, buyer authority, willingness to pay or scope acceptance.

## All 16 modeled services mapped to supported capabilities

This table is a planning map. A nearby catalog family is not permission to select it or proof the full research scope is implemented. Actual evidence and the existing intervention/approval gates still determine canonical scope.

| Research service | Closest supported capability | Boundary / disposition |
| --- | --- | --- |
| O01 motel five-page booking bridge | `full_local_authority_site`; narrower contact-path work under `conversion_tune_up` | Page/content planning overlaps. Booking-vendor integration, inventory and five-page delivery are not automatically validated; keep existing booking provider as an alternative |
| O02 spa five-page service/booking site | `full_local_authority_site`; smaller contact-path correction under `conversion_tune_up` | Owner must confirm service names, booking vendor and access. A site recommendation does not authorize booking-system migration |
| O03 gym trial-to-follow-up configuration | `conversion_tune_up` covers public form/CTA portion only | Internal staff routing and native CRM automation are not a supported automatic offer; worksheet candidate until demonstrated |
| O04 salon service/staff booking clarity | Public copy/contact-path subset of `conversion_tune_up` | Native staff/service booking configuration needs owner validation and platform competence; do not promise it from public evidence |
| O05 three-location factual cleanup | Per-business `google_presence_cleanup` and evidenced site correction | No cross-location authorization or bulk platform changes inferred; each location's facts and permissions remain separate |
| O06 sign-shop quote/artwork handoff | Public quote form subset of `conversion_tune_up` | Artwork approval/version workflow is operational work beyond the current catalog; compare existing Printavo/provider/staff process |
| O07 apparel approval/reorder workflow | No complete existing canonical equivalent | Preserve as candidate research; do not relabel it a website tune-up or mint a new ID |
| O08 flooring consultation plus project proof | `conversion_tune_up` for form/proof-section fixes; `full_local_authority_site` for a separately justified build | Verify project rights, authentic evidence and consultation process; no fabricated portfolio |
| O09 tint service/coverage pages | Service-page content in `full_local_authority_site`; narrow SEO fixes in `conversion_tune_up` | A three-page package is not automatically equivalent to the selected scope; technical/warranty claims and geographic evidence need review |
| O10 auto service pages plus local-search repair | Narrow SEO/contact fixes in `conversion_tune_up`; listing facts in `google_presence_cleanup`; service-page build family where justified | Keep website/Maps evidence and provider overlap separate. No ranking improvement guarantee |
| O11 cleaning five-page B2B inquiry site | `full_local_authority_site`; smaller `conversion_tune_up` alternative | Staffing, procurement and the current provider may explain the problem better; page count and deliverability require agreement |
| O12 bodywork nonclinical booking/preparation cleanup | Public copy/contact portion of `conversion_tune_up` | Native booking configuration and private process changes require explicit scope. No clinical/treatment advice |
| O13 production source-linked 120-minute batch | No complete existing canonical equivalent | Private conversation route; evidence/rights/sample permissions first. Do not represent as automatically detected website work |
| O14 educator 30-asset resource library | No complete existing canonical equivalent | Private conversation route; compare existing LMS, staff workflow and access/rights. Candidate planning only |
| O15 cannabis internal administrative documents | No supported customer-ready offer in this pass | Preserve research HOLD; no quote, compliance inference or automatic eligibility |
| O16 ten-URL technical repair | Existing SEO acquisition and bounded `conversion_tune_up` title/meta/H1 subset | Ten-URL technical remediation is not fully represented by the catalog. Validate exact defect, platform competence, rollback and acceptance; rankings/indexing dates are not delivery acceptance tests |

`starter_local_presence_build`, `one_page_conversion_site`, review/monitoring offers and `no_track_record_pilot` remain available under their existing rules. They are not catch-all replacements for unsupported research services.

## First-use path

1. From Dashboard or Leads, choose **Add Warm Opportunity**, or open an existing business and choose **Guided Opportunity**.
2. Record source/date and observation; choose one of the three routes. Save as planning, without inventing unknown evidence.
3. Use **Review source evidence** for public facts and **Record actual owner confirmation** for a real conversation. Capture objections, authority, permission and actual outcomes there.
4. Open **Smart Offer** to inspect the supported canonical recommendation. The worksheet's candidate scope is deliberately separate from accepted scope.
5. Enter actual operator estimates, including acquisition, travel, learning, revisions, support and direct costs. Blank means UNKNOWN; zero requires an explicit zero estimate. The result is a planning cost, not a quote, margin, customer budget or ROI forecast.
6. Open **Evidence / Delivery Review** for current evidence review, access, platform, backup/rollback, definition of done, exact scope/amount and owner approval.
7. Open **Guided Call** for conversation support. Follow existing contact and approval gates.
8. Record the actual next action/follow-up/outcome in the existing contact/CRM screens.

Hypothetical acceptance example only: an owner asks whether Serenity Now can move from UENI to Wix for easier editing. Capture that request as reported, compare permissions/training/keeping UENI against migration, and ask about domain/email/access. Do not claim the site is broken, select a paid rebuild, create a real customer account, contact Jarrod or change either platform.

## Persistence and limits

- Worksheets append versioned `opportunity_worksheet_v1` ActivityLog entries. Earlier entries and timestamps remain intact; an invalid latest entry does not fall back to an older plan.
- Warm intake uses an explicit local `manual:<uuid>` key in the existing required unique `place_id` column, no search membership, and `details_retrieved:false` with `source:manual_intake`. This is not a Google Place ID. No Google observations are fabricated from a typed URL.
- No schema migration, automatic Google matching, canonical ID additions, owner approval or Qualification changes.
- Intake does not deduplicate an independently discovered Google listing. Do not create a second warm record if the business is already present; automatic reconciliation is deferred.
- Candidate scope and economics are planning notes, not new commercial evidence predicates. Mapping and learning still require operator judgment.
- The worksheet links existing tools; it does not yet automatically choose the next action, compute quote floors with commissions/taxes, measure delivery outcomes, or guarantee Maps/web ranking gains.
- This sprint's implementation is subject to the recorded checks and subsequent Sol verification. A code/test pass is not first-customer commercial acceptance or a Windows release.
