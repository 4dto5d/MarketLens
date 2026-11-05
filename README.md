# MarketLens Local v0.1.16 — Search Visibility Evidence

MarketLens Local is a Windows 10/11 desktop app for finding small local businesses that look like practical website, Google profile, and review-growth opportunities. Existing module names, CLI commands, environment-variable names, and the `%LOCALAPPDATA%\LocalPresenceMiner` data directory remain compatible with earlier releases.

This package is the **v0.1.16 implementation candidate**. The application and CLI identify as **0.1.16**. Windows uses FileVersion and ProductVersion **0.1.16.0**. It adds query-scoped Search Visibility evidence while preserving the v0.1.15 Guided Call, evidence, contact-eligibility, suppression, and commercial-state boundaries. Existing databases receive additive, backed-up storage; historical `search_position` values are not converted into invented visibility observations.

## Search Visibility evidence

Each new Search Run records a visibility probe containing the exact Places query context and an ordered observation ledger captured before shortlist enrichment. Provider-response position and retained in-radius position are separate. Results rejected for duplicate Place ID, missing coordinates, or falling outside the requested radius remain in the internal evidence ledger with an explicit reason.

Open **Run History** and double-click a run to inspect the ledger. Demo Mode rows are labeled **Demo fixture** and are not live evidence. A complete collection can support the statement that a business was or was not observed within that specific collected result window. It does not establish an exact Google Maps or Map Pack rank, and partial, failed, truncated, legacy, or otherwise incomparable collections remain `UNKNOWN` for absence/trend claims.

## Search Market (bounded v0.1.16 core)

Open **Search Market**, choose an existing prospect with a canonical Place ID and recorded search geography, and run a bounded set of deterministic local-intent queries. Demo fixtures are selected by default and visibly marked; live Places collection requires the normal preflight and API key. Each query has a stable taxonomy-derived identity, service cluster, commercial relevance, generation rule, and its own immutable visibility probe/ordered observations. Query failures do not erase successful captures. No Search Market result updates leads, scores, offers, pricing, outreach, suppression, or Guided Call.

The summary shows tracked, observed, UNKNOWN, and excluded query counts. **Coverage = prospect-present queries / (prospect-present + prospect-absent queries)**, restricted to fresh (30-day), complete, nontruncated, correctly linked and sourced query windows. Failed, partial, stale, truncated, unexecuted, and provider-excluded prospect cases are not counted as absence or in the denominator. Cluster coverage uses the same rule. Top Search Competitors require repeat appearance on eligible queries where the prospect was absent; the ordering is deterministic and its query observations are inspectable. Gap rows separate the captured fact from a bounded interpretation. Double-click a run for Cluster → Query → Probe → Observation drill-down.

These are **Google Places Text Search collected-window proxies**, not exact Maps/Local Pack rank, organic SERP rank, search demand, or market share. See `V0116_SEARCH_MARKET_SCOPE.md` for data flow, caveats, and explicit deferred features.

## v0.1.13a: what changed

This release hardens seven workflow boundaries without redesigning the product:

1. A lead is now one canonical CRM record, while each discovery is retained as a separate Search Run membership. Rediscovery refreshes machine evidence but preserves CRM status, suppression, operator notes, and the lead's original compatibility pointer.
2. Search is single-flight at the service boundary and across separately launched application processes. A second GUI, CLI, or internal call targeting the same database is rejected before it creates another run.
3. Current lead viability is part of the canonical approval gate. A permanently closed, suppressed, Hold, or Reject lead cannot remain outreach-ready; prior approved text and revocation history are retained, and restored eligibility never silently reapproves it.
4. Search Runs record `Running`, `Completed`, `Completed With Errors`, `Partial`, `Failed`, `Interrupted / Partial`, or `Interrupted / Failed`, with candidate, processed, success, failure, skip, new, and rediscovered counts plus timestamps and error summaries. Startup safely reconciles a stale `Running` row only when no process owns that database's search lock.
5. A candidate without a canonical Google Place ID is recorded as a failed membership without creating a Lead; later candidates continue. Other ordinary audit/qualification failures likewise remain local. Database/systemic failures still stop the run and are reported honestly.
6. Every generated report, comparison, proposal, mockup, website prompt, site export, manifest, and lead package uses a readable name plus stable lead identity, so same-name and long-name leads cannot overwrite one another.
7. Public HTTP responses are streamed and capped after decompression. This adds a memory/download boundary while retaining the v0.1.12 DNS validation, IP pinning, redirect validation, scheme restrictions, and private-network blocks.

See `V0113_STATE_WORKFLOW_HARDENING.md` for state definitions, migration/rollback details, and requirement-to-test evidence. The unchanged v0.1.12 proof-permission and SSRF model remains documented in `V0112_PASS1_INTEGRITY.md`.

## v0.1.13a usage examples

### Rediscover a market without losing CRM work

Run **Peoria, IL → Roofers** in Demo Mode, qualify a lead, enter an operator note, and later run the same search again. The Lead remains the same CRM record; the two Search Runs each retain their own membership. Public facts, machine-generated opportunity signals, Google Presence, and Qualification Intelligence refresh. Your `Qualified`, `Contacted`, `Replied`, `Meeting Scheduled`, `Won`, `Lost`, `Opted Out`, or `Do Not Contact` state and operator-authored note do not get replaced by search logic.

Open **Lead Searches → Run History** to see whether the run completed cleanly, completed with candidate-level errors, or stopped partially. A `Completed With Errors` run is usable: review its failed-count and error summary rather than rerunning blindly.

### Start a search while another is running

MarketLens Local will show **Search already running** and will not create a second Search Run for the same database. This remains true if two separate MarketLens processes are launched. The first workflow atomically claims a singleton row in that SQLite database with a unique owner/job ID, process ID, acquisition timestamp, attached Search Run ID, renewable heartbeat, and bounded expiry. The same guard applies to CLI or internal service calls, so bypassing the button cannot create overlapping workflows.

### Re-review outreach after viability changes

If current Google evidence reports a business permanently closed, Qualification Intelligence moves it to Hold/Reject, or suppression/DNC becomes active, the app revokes approved outreach. The exact prior body stays in approval history. If later evidence shows the business is operational again, regenerate or review the draft and approve it manually; eligibility restoration is not permission to contact.

### Understand a partial run

Suppose four candidates are found, the first succeeds, the second hits a database-wide failure, and processing stops. Run History reports `Partial`, `4 candidates`, `1 processed`, and `1 succeeded`; the remaining candidates are still Pending rather than falsely labelled successful or failed. A normal website/audit error—or a malformed candidate with no Google Place ID—is recorded on only that membership, later candidates continue, and the run ends `Completed With Errors`.

If Windows terminates MarketLens while a run is active, clean lease deletion cannot occur and its heartbeat stops. After the bounded lease expires, the next startup derives the saved counters from memberships and closes the stale row as `Interrupted / Partial` when work was checkpointed or `Interrupted / Failed` when none succeeded. Pending memberships remain Pending; recovery does not invent results. A current unexpired lease protects its attached `Running` row from another application's startup reconciliation.

### Generate artifacts for same-name businesses

Two businesses called **ABC Roofing** receive different stable identity suffixes. Re-generating the same lead reuses its own paths, while the other lead's report, prompt bundle, proposal, static site, and ZIP remain untouched. Old pre-v0.1.13 artifacts are not deleted.

### Manual entries and cold outreach still required

- Enter your real sender name, business name, reply email, phone, postal address, and opt-out text in **Settings**.
- Enter and classify real Seller Profile, Seller Proof, testimonial/reference permissions, offer outcomes, prices, and actual close amounts in **Pricing Intelligence**. The app cannot infer your experience or permission to share proof.
- Manually verify business identity, current operating status, website/audit findings, relevant competitors, public contact route, material claims, offer scope, price, and the exact draft before approval.
- Choose the recipient and route yourself. Send email/contact-form outreach in your own tool, place calls yourself, select Guided Call branches based on what was actually said, and record the real outcome/follow-up.
- Honor opt-outs and Do Not Contact immediately. MarketLens Local never auto-sends email, submits forms, calls, texts, robocalls, scrapes hidden email, or reapproves outreach.
- Google Cloud billing activation and the real five-business Safe Live Test remain manual and externally blocked in this build; Demo Mode and mocked Places fixtures are the tested fallback.

## v0.1.12 integrity foundation

This release is the five-fix Pass 1 only:

1. Approved outreach now carries an immutable Seller Proof dependency snapshot. Editing, deleting, or materially changing supporting proof revokes only the affected approval and retains the exact approved body and revocation reason in history.
2. New Seller Proof starts `Unclassified`, unverified, non-client-work, internal-only, and with every sharing permission off.
3. Client-name, public-URL, testimonial, case-study/before-after, and reference permissions are independent and explicit. A URL, verification flag, or prior use never implies permission.
4. The canonical approval gate requires complete sender/compliance information, no unresolved placeholders, current lead verification, no suppression, and valid proof dependencies. Copy and batch export re-check the same gate.
5. Prospect-controlled web fetching validates every destination and redirect before contact and pins the connection to the validated public IP. Private/special-use targets are blocked. Rendered-browser fetching is temporarily skipped because browser subresources cannot yet be guarded and pinned reliably; ordinary Website Audit and Contact Discovery remain enabled.

Project/proof-artifact grouping, canonical Offer IDs, shared niche taxonomy, Seller Pricing redesign/history propagation, and the remaining scoring/search/contact/call-richness findings are explicitly deferred. See `KNOWN_DEFERRED_ISSUES.md`.

## v0.1.12 integrity usage examples

### Add Seller Proof safely

Open **Pricing Intelligence → Seller Proof & Experience → Add Proof**. Enter only what you can support. A newly saved record remains private and does not increase completed-client experience until you deliberately set a completed status and **This is actual client work**. External use requires **Verified**, turning off **Internal only**, and selecting each exact disclosure permission needed.

Example: to mention a completed roofing client by name but not share its URL or testimonial, record the client name, mark the evidence verified and client work, turn off internal-only, enable only **Client name sharing**, and leave all other sharing boxes off. MarketLens Local can say a permitted generic phrase such as “recorded work for ABC Roofing”; it may not quote the proof title, result, URL, testimonial, or case study.

### Review, edit, and approve an email

1. Configure sender name, business name, reply email, phone, postal address, and opt-out line in **Settings**.
2. Open a lead, complete the required verification checklist, and generate or refresh outreach.
3. If you edit the subject or body, check the exact Seller Proof records used and confirm that you reviewed this exact text. The edit remains unapproved.
4. Review the final text and click **Approve Draft**. Approval is blocked if a sender value is missing, a placeholder such as `[Your name]` remains, the lead is suppressed, verification is stale, or proof/permission state changed.
5. Copy the approved draft and send it manually using your own email service. MarketLens Local never sends automatically.

If supporting proof later changes or is deleted, the lead moves to **Needs Review**, the draft is unapproved, and its former exact approved body remains in approval history. Re-open the draft, select the current evidence explicitly, revalidate the exact text, and approve again. The app does not silently substitute similar proof.

### Cold call and voicemail

Guided Call remains an operator script and decision-support tool. You place the call yourself, choose the branch matching what the prospect actually says, and record the outcome manually. Voicemail falls back to the neutral phrase “a website analyst” when sender identity is absent, but it is not approval-ready until sender identity is configured. Practice Mode does not write live call outcomes.

### Website Audit and Contact Discovery

Use **Website Audit** or **Refresh Public Contacts** for an ordinary public `http` or `https` business site. Redirects are checked before following them. Localhost, private IPs, special-use names, embedded credentials, unsafe schemes, mixed public/private DNS answers, and public URLs that redirect to private destinations fail closed without contacting the blocked hop.

The **Copy Website URL** and **Copy Google Maps URL** actions copy rather than automatically launch remote URLs. If you choose to visit one in an external browser, that is an independent manual action outside the app's pinned transport. Rendered screenshots are marked `security_unavailable` in this version; raw multi-page audit remains available.

### Google Safe Live Test

The real Google Places Safe Live Test is retained but was not run for this release because billing activation requires an externally blocked refundable prepayment. Demo Mode and mocked Places fixtures cover development and automated verification. When billing is available, configure the API key in Settings and run the existing five-business Safe Live Test; do not interpret the current pending state as a live-API pass.

### Manual actions still required

- Classify, verify, and grant every Seller Proof disclosure permission.
- Confirm business identity, website/audit claims, competitors when mentioned, phone/contact route, and exact outreach text.
- Enter real sender/compliance details; example or placeholder values are not acceptable for real outreach.
- Choose the recipient and preferred route, send email/contact-form outreach yourself, place calls yourself, and record replies/outcomes.
- Review generated pricing, offers, scripts, reports, and claims; estimates are decision support, not guarantees.
- Independently review copied remote URLs before opening them in an external browser.
- Activate Google billing and run the real Safe Live Test later.

It is built for operators who want to find businesses with:

- no website listed
- a broken, outdated, or weak website
- poor mobile/contact flow
- weak Google-facing profile signals
- observable public Google-presence gaps compared with selected nearby businesses
- review/reputation opportunities without using review count as a hard minimum
- nearby competitors with clearer websites, stronger proof, or easier quote/contact paths

The app creates audits, rankings, reports, mockups, paid-style static website exports, owner proposals, starting offers, outreach drafts, pricing guidance, and editable CRM records. It does **not** automatically send email, SMS, calls, or AI voice outreach.

## Contents

- [What v01.11 is](#current-scope)
- [Operator Experience workflow](#operator-experience-workflow)
- [Google Presence Intelligence](#google-presence-intelligence)
- [Intelligence levels and Adaptive Outreach](#intelligence-levels-and-adaptive-outreach)
- [Smart Offer and script usage examples](#smart-offer-and-script-usage-examples)
- [Credibility Engine and first-90-second skepticism](#credibility-engine-and-first-90-second-skepticism)
- [Seller Pricing Intelligence](#seller-pricing-intelligence)
- [Seller pricing usage examples](#seller-pricing-usage-examples)
- [What the app automates and what stays manual](#current-automation-boundary)
- [Free Demo Mode](#free-demo-mode)
- [CLI quick start](#cli-quick-start)
- [Online/offline decision guide](#online--offline-decision-tree)
- [Lead-search usage examples](#lead-search-usage-examples)
- [Real Google Places and optional PageSpeed](#real-google-places-search)
- [Growth Score and starting offers](#lead-scoring)
- [Prompt Paste and outreach](#prompt-paste-workflow)
- [Review, CRM, reports, proposals, and exports](#review-and-crm-workflow)
- [Local data, backup, migration, and privacy](#data-locations)
- [Source run, Windows build, and tests](#windows-source-run)
- [Known limitations, compliance, and troubleshooting](#known-limitations)

## Current Scope

This version is Windows-only.

v01.13a combines **Deep Website Audit**, **Qualification Intelligence**, **Google Presence Intelligence**, the **Credibility Engine**, and the **Adaptive Sales Copilot**. It preserves the integrity-hardened Practice/Live call boundary, full Back-state rollback, exact suppression, canonical Smart Offer planning, evidence invalidation, and last-known-good Google handling. The sales layer handles skeptical first-contact questions from a structured Seller Proof ledger instead of fabricated agency language. Project Value remains separate from the amount the current operator can credibly ask. The app never invents close probabilities, client proof, revenue loss, budget, decision-maker identity, local-office status, measurable results, or a universal experience score.

## Operator Experience workflow

Open a lead to use a single operator workspace rather than a technical tab dump:

1. **Before You Contact** brings together why the lead matters, a grounded opening, Project Value, your recommended ask, relevant proof, and direct actions for the call script, email, competitor view, and manual contact record.
2. **Audit Evidence** turns observed weaknesses into reviewable Revenue Leak cards. Each finding can be marked Unverified, Auto-observed, Human verified, or Rejected / false positive. Desktop/mobile screenshots open when the rendered audit captured them.
3. **Competitors** provides an at-a-glance target-versus-competitor matrix for quote CTA, tap-to-call, services, trust, FAQ, and local schema. The operator must confirm relevance and can manually replace a competitor record.
4. **Smart Offer** keeps prospect-side Project Value and seller-side recommended pricing visibly separate, then proposes the smallest scope that addresses the strongest verified gap.
5. **Activity** uses structured manual contact outcomes so later versions have clean history to learn from.

## Google Presence Intelligence

Google Presence Intelligence evaluates only public fields available through supported Google Places data. It does not inspect private Google Business Profile dashboards. Google Business Profile management APIs are reserved for a future authorized-client mode where the signed-in user owns or has permission to manage the listing.

The app deliberately separates two questions:

| Measure | Meaning | What it is not |
| --- | --- | --- |
| **Google Presence Strength** | How much useful public Google evidence is observable now | A probability, private completeness score, or Maps rank |
| **Google Presence Opportunity** | How much evidence-backed improvement appears available | A promise of more calls, leads, revenue, or ranking |
| **Evidence Confidence** | Low, Moderate, or Strong coverage of the public fields and competitor set | Certainty about business ownership, budget, or results |

Observable inputs can include business status, primary type/types, rating, review count, public phone, linked website, hours, Maps link, service-area-business status, photo references, public review samples, and selected competitor observations. Missing data stays unknown. Low review count is a weighted signal, never an automatic rejection.

The comparison layer can safely say things such as:

```text
Target rating exceeds 2 of 3 selected competitors.
Target review volume trails all 3 selected competitors.
Strong public Google reputation is not matched by the current website experience.
```

It must not say competitors are stealing traffic, claim an exact Map Pack position, invent hidden categories, label a profile incomplete from unavailable fields, or infer customer/revenue loss.

### Cost-controlled Places workflow

Live mode uses staged field masks:

1. **Discovery search** requests identity, location, status, type, Maps-link, and service-area fields. It does not request Enterprise rating/review fields for every discovery result.
2. **Preliminary shortlist** scores only evidence that discovery actually returned: operational status, category/type relevance, address/location or pure-service-area status, collected result position, conservative chain/franchise filtering, and category-opportunity weighting. It does not use rating, reviews, website, phone, hours, or photos because those fields have not been requested yet.
3. **Shortlisted details** request rating, review count, phone, website, hours, and photo references only for the selected candidates. The operator chooses a Google Data Depth cap in New Search:

   | Mode | Maximum rich Place Details calls | Intended use |
   | --- | ---: | --- |
   | Economy | 8 | Small, inexpensive searches and initial prospecting |
   | Balanced | 20 | Broader local-market review with moderate detail spend |
   | Deep Prospecting | 40 | Large searches where deeper qualification is worth the added calls |
   | Safe Live Test | All returned results, maximum 5 | Controlled real-API acceptance test |

4. **Deep qualification** runs website audit, competitor analysis, Google Presence, Sales Priority, and Smart Offer work only on the shortlist. Discovery-only candidates outside the shortlist do not become falsely qualified leads.
5. **Competitor assessment** reuses persisted public snapshots and requests no private Business Profile fields.

Before a live search runs, the dialog shows an upper-bound estimate such as `5 Text Search + 20 Place Details = up to 25 calls`. Actual calls may be lower when Google returns fewer businesses. One Place Details request is counted per shortlisted business; this is a request-count estimate, not a currency quote.

If a shortlisted Place Details request fails, LPM preserves its discovery fields, marks rich fields Unknown, assigns Hold / Research-first, and avoids automatic sales-asset generation. It never converts “not requested” into “no website,” “0 reviews,” “missing phone,” “missing hours,” or “few photos.” Review text is not requested by default; the client exposes a separate explicit review-sample field mask for a future operator-requested workflow.

This is progressive qualification: inexpensive evidence first, deeper evidence second. API billing and quotas remain controlled by the operator's Google Cloud account.

Official references: [Place Data Fields and SKU tiers](https://developers.google.com/maps/documentation/places/web-service/data-fields), [Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search), and [Place Details (New)](https://developers.google.com/maps/documentation/places/web-service/place-details).

### Google Presence usage examples

**Strong Google reputation + weak website**

```text
Strength: 82/100
Opportunity: 38/100
Recommended action: Website-only

Reason: The public reputation is already useful; the larger verified gap is the website's contact and trust presentation.
```

**Weak Google presence + strong website**

```text
Strength: 46/100
Opportunity: 67/100
Recommended action: Google Presence-only

Reason: The website is comparatively strong, while observable phone/hours/photo/reputation fields trail the selected comparison set.
```

**Both surfaces weak**

```text
Strength: 41/100
Opportunity: 78/100
Recommended action: Website + Google Presence

Reason: Evidence supports a combined conversion-path and owner-authorized Google-presence improvement scope.
```

**Both surfaces strong or evidence is insufficient**

```text
Recommended action: Research-first / already strong
or
Recommended action: Research-first / insufficient evidence
```

The Smart Offer follows the recommended action instead of selling every available service. Google-related scope is always framed as a public evidence review and an owner-authorized improvement checklist.

### Manual Google actions still required

The operator must manually:

- activate and fund their own Google Cloud billing account before live Places requests can run;
- save the Google Maps API key in **Settings**; never paste it into outreach, reports, source, or chat;
- confirm that selected competitors are genuinely comparable;
- confirm business identity, operational status, contact details, and any apparent website/Google mismatch before using it in outreach;
- obtain owner authorization before editing a client Google Business Profile;
- review categories, services, hours, photos, and review language with the owner before proposing changes;
- send all cold outreach manually and honor opt-outs/suppression requests.

Demo Mode and mocked Places fixtures work without billing or network access. The real maximum-five-business Safe Live Test remains a separate release gate and must not be marked passed until billing is active and the actual Google Places boundary has been exercised.

## Intelligence levels and Adaptive Outreach

The product uses this scale:

| Level | Meaning in Local Presence Miner | Current status |
| --- | --- | --- |
| Medium | Rules, templates, and straightforward scoring | Foundation used throughout the app |
| High | Weighted qualification with multiple signals, exceptions, disconfirmers, and uncertainty | Implemented in Qualification Intelligence |
| Extra High | Offer, email, call script, and objection handling adapt to the specific lead | Implemented in this v01.11 build |
| Ultra | Recommendations learn automatically from actual replies, objections, niche results, prices, and closes | Not implemented; structured outcomes are stored for a future release |

The Extra High layer is deterministic decision support, not autonomous AI. One shared reasoning model combines:

- Sales Priority, qualification class, and qualification confidence;
- public website/contact-path evidence and the strongest observed Revenue Leak;
- selected competitor context;
- available public contact route;
- recommended package and scope;
- Seller Pricing Intelligence, including Easy-Close, Recommended, and Stretch amounts;
- seller proof confidence and comparable offer history;
- disconfirmers and missing evidence that should weaken or stop a pitch.

It produces:

- a message strategy and call objective;
- a Smart Offer with lead-specific scope and live seller-calibrated prices;
- an initial email plus interested, price, existing-provider, and not-now reply scripts;
- a Guided Call tree with nested follow-up branches;
- explicit claims to avoid and human checks that must be completed.

Hold and Reject leads receive research-first guidance. They are excluded from the outreach-ready batch while their qualification snapshot remains Hold or Reject. Suppressed, Opted Out, and Do Not Contact leads remain absolute outreach blocks.

## Smart Offer and script usage examples

### Example: high-priority roofer with a weak quote path

```text
Sales Priority: 86/100
Class: Demo Priority
Confidence: Strong
Primary theme: Conversion path

Smart Offer
Positioning: Improve the existing site; do not assume a full redesign.
First scope: Homepage CTA and estimate/request flow
Easy-Close: $950
Recommended: $1,250
Stretch: $1,600

Why:
- The public audit shows no obvious quote/contact path.
- Selected nearby competitors make requesting an estimate easier.
- Seller Pricing Intelligence supports the recommended ask from recorded proof/history.
```

The opening email asks permission to share the evidence before pushing a project. If the prospect asks for price, the price-reply draft uses the current Seller Pricing Intelligence amounts rather than a hardcoded sample. If they say they already have a provider, the reply offers the evidence for that provider instead of demanding a replacement.

### Example: “We are already busy enough” call path

```text
IF: We're already busy enough
THEN: Determine whether this means capacity, no perceived need, or a request to stop.

IF: We're booked out
THEN ASK: Better-fit work, easier intake, hiring support, or no changes?

IF: We want better-fit jobs
THEN: Focus on clearer service fit and expectations, not “more leads.”

IF: We need easier intake
THEN: Offer a smaller contact/estimate-flow phase, not a cosmetic rebuild.

IF: We do not want changes
THEN: Close the opportunity and do not schedule follow-up without permission.
```

### Example: price branch

```text
IF: How much?
THEN: Show the live Easy-Close / Recommended / Stretch options.

IF: Show me the smaller first phase
THEN: Explain the exact first outcome and exclusions.

IF: That's too expensive -> Mostly budget -> No budget right now
THEN: Do not manufacture urgency; ask whether to close out or follow up in a specific month.

IF: That's too expensive -> Not sure it is worth it -> Can you guarantee results?
THEN: State clearly that rankings, leads, calls, and revenue are not guaranteed.
```

### Where manual entries and actions are still required

Before relying on the adaptive output, manually enter or confirm:

- seller profile, real proof items, testimonials, completed work, and offer outcomes in **Pricing Intelligence**;
- owner/decision-maker name only when you actually know it;
- competitor relevance and evidence notes;
- rejected audit findings or false positives;
- the prospect's actual goal, requested scope, timing, budget language, and approval process;
- every contact outcome, objection, reply signal, follow-up date, opt-out, and suppression request.

Cold outreach remains manual. Review and approve the exact draft, copy it, send it using your own email or phone tools, then record the result. Local Presence Miner does not send email, submit forms, place calls, leave voicemails, send SMS, run robocalls, or speak with an AI voice.

### Contact-outcome example

After a manual phone call, choose **Record Contact** and enter:

```text
Method: Phone
Outcome: Price objection
Responded to: Competitor comparison, Google presence
Objection: Too expensive
Next follow-up: 2026-08-18
Notes: Owner liked the estimate-flow comparison and asked for a smaller first phase.
```

This is operator-entered evidence only. v01.11 stores it locally; it does not yet learn from outcomes or claim an adaptive prediction.

### Manual and cold-outreach boundary

The app can find public data, draft wording, make reports, and surface a suggested next action. You must manually:

- confirm the business identity, contact route, website facts, competitor relevance, pricing, and outreach language;
- choose whether outreach is appropriate for your jurisdiction, platform rules, and the recipient;
- send any email, call, text, voicemail, or social message outside the app;
- record what happened after outreach, including opt-outs or suppression requests.

It never auto-sends cold outreach. An unapproved draft can be copied only for editing; final sending remains a human action.

## Credibility Engine and first-90-second skepticism

The Credibility Engine is the truthful proof layer behind the first 60–90 seconds of Guided Call. It assumes a cold prospect may reasonably ask who is calling, why the business was selected, whether the seller is legitimate, what has actually been completed, whether the seller is local, and how AI is being used.

It does not create credentials. It ranks only records that the operator entered in **Pricing Intelligence → Credibility & Proof** and keeps these states distinct:

| Proof status | What call/email language may say | What it must not say |
| --- | --- | --- |
| Completed | The named work was completed | That it was verified, successful, or client work unless separately recorded |
| Completed + Verified | The completed item was manually verified | That it produced an unrecorded result |
| Completed + Testimonial | A testimonial is recorded as available | That the testimonial is verified unless Verified is also checked |
| Completed + Measurable Result | A measurable-result artifact is recorded as available | A result number or causal claim that is not in Safe claims and verified |
| In Progress | “I’m building…” or “This is in progress…” | “I completed…” |
| Prototype | “I have a working prototype…” | Completed client work |
| Concept Only | “I have a concept…” | A built, delivered, or client-owned project |
| Unclassified | Legacy evidence that needs operator review | Any completed-work claim |

The migration deliberately marks older proof records **Unclassified**. It does not silently convert a historical Portfolio Example into completed client work. Open each legacy record, inspect the evidence, choose the correct status, and add provenance/safe-claim boundaries before using it in outreach.

### Seller identity and location setup

Open **Pricing Intelligence → Seller Profile** and manually configure:

1. Display name.
2. Business/brand name, if one is actually used.
3. Identity type: Individual / Freelancer, Registered Business, or Brand Name.
4. Location model: Local, Regional, Remote, Currently traveling, Remote-first service, or Not configured.
5. Actual city/region and service area, when supportable.

If these fields are blank, Call Mode says they are not configured. It does not invent an agency, office, registration, or local address. Choosing Remote or Remote-first produces transparent remote wording; choosing Local without a location does not invent a city.

### Proof-ledger fields and manual verification

Every proof record can store:

- proof type and status;
- title and niche/category relevance;
- explicit client-work and software/AI-project flags;
- completion date and public/example URL;
- testimonial, measurable-result, and before/after availability;
- provenance explaining where the evidence came from;
- one supportable claim per line under **Safe claims**;
- one forbidden/unsupported claim per line under **Do not claim**;
- private notes that are never intended for prospect delivery.

Manual operator work is required here. A checked box is not external verification by itself. Before marking evidence Verified, open the artifact, confirm ownership/permission, confirm the status, and make sure every Safe claim is narrower than what the artifact actually supports.

### “Have you done this before?” examples

No completed client work recorded:

```text
I'm newer on the client-service side, so I'm not going to pretend I have a large niche portfolio.
I'd rather show you the actual comparison and let the evidence and proposed work speak for themselves.
```

Only a prototype recorded:

```text
I have a working prototype, Roofing concept (Prototype); it is not completed client work.
I'd rather show you the actual comparison and let the work speak for itself.
```

Completed same-niche client work recorded:

```text
I have 2 completed relevant client projects recorded, including Completed Summit Roofing website project.
I can mention a testimonial or measurable result only when that supporting record is also verified.
```

The response is generated from the current ledger each time. Editing or deleting the proof stops future call guidance, proposals, reports, and unapproved drafts from using the old claim. Existing human-approved outbound remains immutable unless another evidence-integrity rule explicitly revokes its approval.

### First-90-second call workflow

Guided Call starts with only five likely early paths:

1. Who are you?
2. What is this about?
3. How did you find us?
4. We already have someone.
5. Have you actually done this before?

Use **Search all**, **Other**, or **I don’t know what they mean** when the prospect’s wording does not fit. The phase indicator moves through Identity/Relevance, Legitimacy/Evidence, Discovery/Objections, Price, and Next Action. It is decision support, not Listener Mode; the operator still chooses the meaning manually.

Credibility paths include:

- What company are you with?
- What exactly do you do?
- Are you local?
- Why did you pick us?
- Is this a sales call?
- Who gave you my number?
- Who have you done this for?
- Can I see examples?
- Do you have references?
- Is this legitimate or a scam?
- Will you need website access?
- What happens before payment?

**Quick** shows the core line, **Normal** shows the recommended response, and **Detailed** includes the next move. Back restores the entire prior path and structured state. Practice Call never writes credibility state, interactions, or suppression to the live database.

### AI skepticism example

```text
Prospect: Are you just using AI?

Suggested response:
AI is part of the tooling, but the important part is the system around it: evidence collection,
verification, competitor selection, qualification, human review, and unsupported-claim prevention.
I use AI to move faster, not to invent things.

Then choose the actual concern:
- Why would I pay if AI can make a website?
- Can't I use ChatGPT, Lovable, or Canva myself?
- Is this an automated sales pitch?
- Will AI make things up?
- Is AI safe for my business?
- Does AI hurt SEO?
- Is this all templates?
```

The app never claims AI guarantees quality, safety, conversions, or rankings. No message is sent automatically, and no Listener Mode, live transcription, intent detection, or outcome-learning loop is included in v0.1.11.

### Proof attachment recommender

When the prospect asks for examples, proof, or references, Call Mode separates:

```text
SEND
- verified, relevant, completed proof with a public artifact URL

OPTIONAL
- verified completed proof that requires the operator to locate/share the artifact manually

DO NOT SEND
- private Seller Pricing data
- internal notes
- unsupported or unverified results
- unrelated unfinished/prototype evidence unless its status is explicit and genuinely relevant
```

Direct references remain manual. A testimonial is not permission to give a prospect someone’s contact information. Obtain explicit reference permission outside the app before offering a direct introduction.

### Conversation memory and follow-up

In Live Call, **Record Outcome** can persist specific credibility signals instead of a generic objection:

- general credibility concern;
- wants examples, references, or proof;
- concerned about AI;
- asked about seller experience or location;
- skeptical decision maker;
- legitimacy/scam concern.

These signals change later follow-up, interested-reply, report-delivery, human checks, and proof recommendations. For example, an experience question produces a proof-aware follow-up; an AI concern produces a concise explanation of the evidence/human-review system; a legitimacy concern recommends a no-payment/no-access evidence review first.

This is still **Extra High deterministic decision support**, not Ultra learning. v0.2.x is reserved for Listener Mode and outcome learning from real transcripts/results.

## Seller Pricing Intelligence

Seller Pricing Intelligence answers two different questions and deliberately keeps their answers separate:

| Question | App term | What affects it |
| --- | --- | --- |
| What does this work reasonably appear to justify for this prospect? | **Project Value** | lead opportunity, recommended package, documented gaps, Growth Score, scope, and attached competitors |
| What can this particular operator currently justify asking? | **Your Current Pricing** | relevant completed work, verified proof, niche experience, comparable offers, actual wins, closing prices, and recency |

This separation matters. A beginner's limited portfolio can support a conservative first ask without pretending the underlying work has less value. Adding seller proof can change the recommended ask, but it does not lower or inflate Project Value.

### Pricing Intelligence navigation

Open **Pricing Intelligence** from the left navigation. The page has five sections:

- **Overview**: seller identity, private notes, proof totals, median closed value, pricing trend, and qualitative evidence confidence.
- **Offer History**: initial ask, final ask, closed amount, status, structured lost reason, and private CSV export.
- **Credibility & Proof**: status-separated projects, portfolio concepts, testimonials, case studies, before/after proof, provenance, safe claims, prohibited claims, and verification state.
- **Comparable Deals**: Project Value beside Easy-Close, Recommended, and Stretch asks, with the comparable sample and a plain-language explanation.
- **Pricing Performance**: observed price bands, wins with denominators, won value by niche, and small-sample suppression.

Project Value is calculated from the lead and scope. Seller pricing is then calibrated from actual seller evidence without lowering the underlying Project Value. Limited-history guidance favors a smaller starter scope over selling the full project for an unsustainably low price.

From a lead, **Owner Mode** includes private pricing guidance. **Generate customer proposal** asks which price to show; **Generate internal pricing proposal** contains the private reasoning; **Record as Presented Offer** explicitly saves the actual price and historical evidence snapshot. Generating a proposal alone never claims that it was sent.

### First-time seller setup

Set up the seller side before relying on its recommendations:

1. Open **Pricing Intelligence**.
2. In **Overview**, enter the operator's display name and business name.
3. Optionally enter an experience start date in `YYYY-MM-DD` format.
4. Use **Private notes** for operator context that should never appear in prospect deliverables.
5. Click **Save Seller Profile**.
6. Open **Credibility & Proof**.
7. Click **Add Proof** for each real item you can document.
8. Mark an item verified only after checking that it exists and is accurately described.
9. Open **Offer History** and enter real past offers if you have them.
10. Do not invent starter records just to make the recommendation rise.

The app does not ask the operator to choose an experience level or make up an experience score. Its evidence summary changes as real records are added.

### Seller Proof fields

Each proof record supports a specific piece of evidence:

| Field | Meaning | Example |
| --- | --- | --- |
| Proof type | Kind of experience or evidence | `Paid Project` |
| Title | A private, recognizable label | `Johnson Roofing quote-flow refresh` |
| Status | Completion/credibility boundary | `Completed + Verified` |
| Niche | Industry this proof supports | `roofing` |
| Description | Factual summary of what was done | `Reorganized the estimate path and review section` |
| Client name | Optional real client name | `Johnson Roofing` |
| Project value | Optional historical value | `1200` |
| Completion date | Optional `YYYY-MM-DD` date | `2026-07-15` |
| Public URL | Optional portfolio or public evidence link | `https://example.com/case-study` |
| Verified | Operator-confirmed evidence state | checked only after review |
| Client work | Explicitly identifies real client work | checked only for an actual client project |
| Software / AI | Identifies technical system proof | `Local Presence Miner` |
| Testimonial / measurable result / before-after | Availability flags, not automatic proof of success | checked only when the artifact exists |
| Provenance | Where the evidence came from and who verified it | `Public portfolio page checked 2026-08-28` |
| Safe claims | One supportable sentence per line | `Completed roofing website project` |
| Do not claim | Explicit unsupported boundaries | `Guaranteed more roofing leads` |
| Private notes | Internal context | permission limits, missing assets, or follow-up details |

Supported proof types are:

- Paid Project
- Unpaid Project
- Local-Business Website Project
- Audit Project
- Google Presence Project
- AI / Software System
- Automation Workflow
- Data-Processing Pipeline
- Portfolio Example
- Portfolio Concept
- Testimonial
- Measurable Outcome
- Niche-Specific Project
- Case Study
- Before / After
- Relevant Employment Experience
- Certification
- Other

Proof types are not treated as equal. The current transparent evidence weights are:

| Proof type | Base evidence weight |
| --- | ---: |
| Paid Project | 3 |
| Case Study | 3 |
| Before / After | 2 |
| Testimonial | 2 |
| Relevant Employment Experience | 2 |
| Certification | 1 |
| Portfolio Example | 1 |
| Unpaid Project | 1 |
| Other | 1 |

A verified record contributes more evidence than an unverified record. Completed-status gates are evaluated separately: a high-weight type that is In Progress, Prototype, Concept Only, or Unclassified cannot become completed client proof. Types not listed in the legacy weight table use the conservative default weight. These weights classify seller evidence; they never multiply or rewrite Project Value and are not a claim about universal market value.

### What verified means

Use **Verified** to mean that the operator has checked the underlying evidence and can truthfully rely on it. Examples include:

- the project was actually completed
- the testimonial is real and accurately attributed
- the portfolio URL exists
- the case study does not contain invented results
- the certification is current and belongs to the operator
- the operator has permission to identify the client when necessary

Only relevant verified proof can be turned into a suggested proof sentence in outreach. The app will not invent revenue gains, conversion improvements, client satisfaction, or a project outcome that is not stored.

### Offer History fields

Offer History is private sales data. A record can be linked to a lead or entered manually for an older prospect.

| Field | Meaning |
| --- | --- |
| Offer date | Date the offer state being recorded applies to |
| Business | Prospect business name |
| Niche | Prospect industry, used for comparable matching |
| City | Optional location context |
| Package | Package or service offered |
| Scope | What was actually included |
| Actual initial ask | First amount the operator really presented or intends to track |
| Recommended ask at offer | App recommendation preserved separately from the actual ask |
| Final negotiated ask | Later amount proposed after negotiation |
| Closed amount | Real amount secured when status is Won |
| Status | Current offer state |
| Lost reason | Structured explanation; required for useful loss analysis |
| Private notes | Internal sales context |
| Growth Score snapshot | Lead score when the record was created |
| Project Value snapshot | Prospect-side range when the record was created |
| Seller confidence snapshot | Low, Moderate, or Strong at that time |
| Proof snapshot | Seller evidence counts and relevant proof as they existed then |

The snapshot fields protect history. Editing the Seller Profile or adding proof later does not rewrite what was known when an earlier offer was recorded.

### Offer status glossary

| Status | Use it when |
| --- | --- |
| Draft | You are planning an offer; it has not been presented |
| Presented | The prospect actually received or heard the offer |
| Negotiating | Scope or price is being discussed |
| Accepted | The prospect agreed, but the project is not yet treated as secured/completed in your workflow |
| Rejected | The offer was explicitly declined |
| Won | A real customer/project was secured; record the actual closed amount |
| Lost | The opportunity ended without a win |
| Withdrawn | You chose to remove the offer |
| No Response | The prospect did not respond; this is not automatically price evidence |

`Accepted` and `Won` are deliberately different. A Won record requires a closed amount so pricing analytics learn from realized value instead of a vague verbal response.

### Lost reasons and why they matter

Available lost reasons include:

- Too expensive
- Budget unavailable
- No response
- Chose competitor
- DIY
- Timing
- Not decision maker
- Scope mismatch
- Trust / proof issue
- No perceived need
- Unknown
- Other

Only **Too expensive** and **Budget unavailable** are treated as price-relevant negative outcomes in v01.07. A no-response record can still be a comparable offer, but it is excluded from price-sensitivity and close-rate evidence. This prevents five ignored messages from being misread as proof that a particular price was too high.

### When an offer is recorded

Generating pricing guidance or a proposal does not create a Presented offer. To record a real presentation:

1. Open the lead.
2. Open the **Actions** tab.
3. Click **Record as Presented Offer**.
4. Review the prefilled business, niche, package, scope, recommendation, and Project Value.
5. Enter the actual initial ask. It may match or override the recommendation.
6. Keep status **Presented** unless a later state already applies.
7. Click **Save Offer Record**.

To update the result later:

1. Open **Pricing Intelligence**.
2. Open **Offer History**.
3. Select the record and click **Edit Selected**, or double-click it.
4. Add the final negotiated ask if one existed.
5. Choose Won, Lost, Rejected, No Response, or another accurate status.
6. For Won, enter the actual closed amount.
7. For a loss, choose the real lost reason rather than assuming price was the issue.
8. Save the record.

### How Project Value is calculated

Project Value is prospect-side. The current package bands are:

| Package | Starting Project Value band |
| --- | ---: |
| Google Presence Cleanup | $250-$600 |
| Conversion Tune-Up | $450-$1,000 |
| Starter Local Presence Build | $750-$1,800 |
| One-Page Conversion Site + Google Cleanup | $900-$2,200 |
| Full Local Authority Site | $2,000-$5,000 |
| Review Trust Builder | $300-$900 |
| Monitoring + Review Growth Plan | $150-$500 |
| No-Track-Record Pilot | $300-$900 |

The Growth Score adjusts that prospect-side band transparently:

- `75+`: the documented opportunity supports a 15% increase to the band
- `45-74`: the normal package band remains in use
- below `45`: the estimate moves toward a smaller prospect-side scope

A missing website and attached competitors add explanation and scope context. Seller projects, testimonials, offer history, and old `Previous sales/proof notes` do not change Project Value.

### How comparable offers are selected

The app scores potential historical comparables using:

- same niche
- same package
- overlapping scope words
- a Growth Score within 15 points
- overlapping Project Value ranges
- recency within one or two years

Exact matches are not required. Same-niche evidence is strongest, unrelated niches are penalized, and the ten highest qualifying records are used. Draft offers are ignored.

The comparable section can show:

- number of selected offers
- median initial ask
- median won amount
- comparable ask range
- number of comparable wins
- average negotiation discount when at least three wins support it
- the reason each internal comparable matched

Percentages are suppressed until at least five price-relevant resolved outcomes exist. Until then the app shows the numerator and denominator with an explicit small-sample warning.

### How Your Current Pricing is calculated

The seller-aware recommendation operates on top of Project Value:

1. Calculate Project Value from the lead and scope.
2. Summarize overall and niche-relevant seller proof.
3. Select recent/relevant comparable offers.
4. If comparable wins exist, anchor to the higher of the median comparable win and the newest comparable win.
5. Apply transparent price steps for Moderate or Strong proof.
6. Add a smaller documented opportunity step for a Growth Score of 75 or higher.
7. Keep the result within a rational relationship to Project Value.
8. Derive a lower Easy-Close position and higher Stretch position.
9. Explain every component in **Why This Number?**

Current price-step sizes are:

- $100 when the Project Value floor is below $1,000
- $250 when the floor is $1,000-$2,499
- $500 when the floor is $2,500 or higher

When no comparable wins exist, the engine uses starter-risk calibration rather than pretending it has historical evidence:

- Low proof: 75% of the Project Value floor
- Moderate proof: 85% of the Project Value floor
- Strong proof: 100% of the Project Value floor

The recommendation is still bounded and paired with a smaller Starter scope. It is not permission to sell the full project at the Starter amount.

### Easy-Close, Recommended, and Stretch

| Position | Meaning | How to use it |
| --- | --- | --- |
| Easy-Close | Lower-friction entry point | Offer a genuinely smaller first phase, not the identical full scope at a destructive discount |
| Recommended | Primary evidence-based ask | Use when the documented scope, seller proof, and comparable history line up normally |
| Stretch | Higher defensible position | Use when scope and opportunity are strong and you are prepared to defend what is included |

The Pricing Intelligence output also labels three phases:

- **Starter**: normally the first one or two high-value scope items
- **Core**: the recommended package and full core scope
- **Expanded**: core scope plus a verified add-on or second phase

### Evidence Confidence

Evidence Confidence is a qualitative seller-evidence label:

- **Low**: little relevant proof or won history
- **Moderate**: at least some relevant paid proof plus a relevant win or enough additional relevant evidence
- **Strong**: multiple relevant paid projects, several verified relevant records, and multiple relevant wins

It is not a predicted close probability. The app does not display a fabricated `88% confidence` number.

The Overview confidence can differ from a lead-specific niche confidence. Ten roofing projects may support Strong roofing evidence while a first dental lead remains Low.

### Pricing Performance interpretation

Pricing Performance shows:

- total offers
- non-draft/presented offer count
- wins, losses, and no-response counts with denominators
- median initial ask
- median closed price
- average won value
- total won value
- recent pricing trend
- proof inventory
- observed price bands
- top niches by won value
- top niches by number of wins

The fixed v01.07 price bands are:

- Under $750
- $750-$999
- $1,000-$1,249
- $1,250-$1,499
- $1,500-$1,999
- $2,000+

A price-band win rate is suppressed when fewer than five offers are in that band. Even with a larger sample, a strong band is correlation, not proof that the price caused the result.

### Proposal and outreach privacy boundary

There are two proposal paths:

- **Generate customer proposal**: prompts for the one intentionally selected customer-facing price and omits seller confidence, historical offers, negotiation patterns, and private proof inventory.
- **Generate internal pricing proposal**: includes Project Value, Easy-Close, Recommended, Stretch, proof summary, comparable history, phased options, and reasoning. It is labeled private and should not be sent.

Unpriced drafts, selected-price proposals, and internal proposals use different filenames so one cannot silently overwrite another.

Prospect lead packages do not contain Seller Profile notes, Seller Proof records, past offer history, internal close-rate analysis, or negotiation notes. Private pricing data also stays out of ordinary activity-log messages.

### Local and deterministic behavior

Seller pricing analysis runs locally and deterministically in v01.07. Seller history is not sent to an AI provider. The app stores API keys separately from pricing exports, and `offers.csv`/`seller_proof.csv` do not contain API secrets.

## Seller Pricing Usage Examples

These examples use the current v01.07 behavior. They illustrate workflow and interpretation; they are not promises that a prospect will accept a price.

### Example 1: Brand-new seller with no history

Situation:

```text
Lead: strong roofing prospect
Growth Score: 80
Recommended package: One-Page Conversion Site + Google Cleanup
Completed paid projects: 0
Comparable historical offers: 0
Testimonials: 0
```

Expected interpretation:

```text
Project Value: $1,050-$2,550
Evidence Confidence: Low
Comparable history: 0

Starter: tightly scoped first phase
Core: full recommended scope
Expanded: core plus a verified add-on
```

The lower seller ask does not mean the full project is only worth a beginner price. Use the Starter amount for a smaller scope such as the homepage conversion path and quote flow. Keep service-page expansion, deeper Google work, or other additions in later phases.

### Example 2: Roofing seller history changes the ask

Enter this real-history pattern:

| Offer | Niche | Initial ask | Outcome |
| --- | --- | ---: | --- |
| Roof Offer 1 | roofing | $750 | Won at $750 |
| Roof Offer 2 | roofing | $1,000 | Won at $900 |
| Roof Offer 3 | roofing | $1,200 | Lost: No response |
| HVAC Offer | HVAC | $1,250 | Won at $1,150 |

Add real proof:

```text
3 completed paid projects total
2 relevant roofing project records
2 roofing testimonials
```

For a strong new roofing prospect, the verified v01.07 acceptance scenario produces:

```text
PROJECT VALUE
$1,050-$2,550

YOUR CURRENT PRICING
Easy-Close: $1,000
Recommended: $1,250
Stretch: $1,500

Evidence Confidence: Moderate
Comparable roofing offers: 3
Price-relevant resolved outcomes: 2
```

The HVAC win does not become a roofing pricing anchor. The $1,200 no-response loss remains comparable context but is not interpreted as proof that $1,200 was too expensive.

### Example 3: Manually override the recommendation

Suppose the app recommends $1,250, but the operator decides the actual scope supports $1,375.

1. Open the lead.
2. Click **Record as Presented Offer**.
3. Leave the preserved recommendation at $1,250.
4. Change **Actual initial ask** to $1,375.
5. Save as Presented.

The record now preserves:

```text
Recommended ask at offer: $1,250
Actual initial ask: $1,375
Status: Presented
Project Value and proof: snapshot from that date
```

Future analysis can learn whether the operator's override worked. The app does not silently replace the recommendation with the chosen amount.

### Example 4: Record a negotiated win correctly

The operator initially presented $1,500, later offered $1,350, and secured the work at $1,250.

Record:

```text
Initial ask: $1,500
Final negotiated ask: $1,350
Closed amount: $1,250
Status: Won
```

Do not overwrite Initial ask with $1,250. Keeping all three amounts lets the app measure actual realized value and typical discounting. Average negotiation discount appears only when at least three comparable wins support it.

### Example 5: No response is not a pricing conclusion

Five $1,500 offers receive no response.

Correct recording:

```text
Status: No Response
Lost reason: No response, if using Lost instead
```

Incorrect conclusion:

```text
$1,500 is too expensive.
```

The app excludes these records from price-relevant resolved outcomes. Use **Too expensive** only when the prospect actually indicated price was the issue, and **Budget unavailable** only when budget was genuinely the reason.

### Example 6: Same Project Value, different niche confidence

The seller has:

```text
4 roofing projects
2 roofing testimonials
3 roofing wins
0 dental projects
0 dental wins
```

A roofing and dental prospect may have similar Project Value because their documented scope and opportunity are similar. The roofing seller ask can still be higher because relevant proof differs. The explanation should say seller pricing confidence differs; it should not claim the dental work itself has lower value solely because the seller is new to dental.

### Example 7: Use a phased offer instead of discounting everything

Suppose Project Value is $1,800-$2,600 but the seller has limited evidence.

Present scope choices such as:

```text
Starter
Homepage conversion refresh + quote flow
$750

Core
Homepage, service structure, reviews, contact flow
$1,600

Expanded
Core scope + additional service pages / verified add-on
$2,100
```

The $750 option is not the same $1,600 scope sold more cheaply. It is deliberately smaller.

### Example 8: Generate the correct proposal

For an internal review:

1. Open the lead's **Actions** tab.
2. Click **Generate internal pricing proposal**.
3. Review Project Value, comparable deals, seller proof counts, and reasoning.
4. Do not send this file to the prospect.

For the customer:

1. Click **Generate customer proposal**.
2. Enter the exact selected price.
3. Review the resulting scope and factual claims.
4. Send only after human approval.

The customer file shows the selected package/price, not the seller's Low/Moderate/Strong confidence, beginner calibration, old closing history, private testimonials inventory, or negotiation metrics.

### Example 9: Use Owner Mode before a call

Open the lead and review Owner Mode. A pricing section can look like:

```text
Project Value: $1,050-$2,550
Easy-Close: $1,000
Recommended: $1,250
Stretch: $1,500
Evidence Confidence: Moderate
```

The generated call opening does not lead with price. If the prospect asks, the optional section uses the current recommendation:

```text
For the issues I found, the useful full-scope version is around $1,250-$1,500,
depending on what we include. A tighter first phase can start around $1,000.
```

Objection notes avoid false urgency and pressure. They offer scope clarification, time to review, or a smaller phase rather than invented scarcity.

### Example 10: Export private pricing data

To back up or analyze offers:

1. Open **Pricing Intelligence > Offer History**.
2. Click **Export offers.csv**.
3. Choose a private folder.

To export proof:

1. Open **Pricing Intelligence > Proof & Experience**.
2. Click **Export seller_proof.csv**.
3. Choose a private folder.

These exports can contain sensitive business/client notes. Store them like private CRM data. They are never automatically included in prospect lead packages.

### Example 11: Upgrade an existing v01.06 database

On first v01.07 initialization of a v01.06 database:

1. The app detects the pre-v01.07 schema.
2. It creates a sibling backup ending in `.backup-before-v0107`.
3. It adds `seller_profiles`, `seller_proof`, and `offer_history`.
4. Existing leads, searches, audits, verification data, outreach drafts, suppression entries, contact interactions, settings, reports, and activity remain in place.

Do not delete the backup until you have opened the app and confirmed your existing workflow data.

### Example 12: A practical weekly pricing routine

At the start of the week:

1. Review **Pricing Performance** for totals and missing outcomes.
2. Update stale Presented or Negotiating records.
3. Add newly completed projects and testimonials as proof.
4. Verify any proof that is now ready to share.
5. Export private CSV backups if desired.

Before each proposal:

1. Review the lead's Growth Score and Project Value.
2. Open **Comparable Deals** for that lead.
3. Read **Why This Number?**
4. Decide Starter, Recommended, Stretch, or a manual override.
5. Generate the private proposal first when the deal is important.
6. Generate the customer proposal with only the selected price.
7. Record it as Presented only after the prospect actually receives it.

After each outcome:

1. Enter the final negotiated ask.
2. Enter the closed amount for a win.
3. Choose the real loss/no-response reason.
4. Add any legitimate new proof after the project is actually completed.

### Common pricing-data mistakes

Avoid these mistakes:

- entering fake wins or testimonials to raise the recommendation
- marking an unverified portfolio claim as verified
- using Closed amount for a project that was merely verbally accepted
- replacing Initial ask with the final negotiated amount
- labeling every non-response as Too expensive
- recording a generated proposal as Presented when it was never sent
- putting private seller weakness or close-rate data in a customer proposal
- selling the full Core scope for the smaller Starter amount
- treating a price-band correlation as proof that the band caused wins
- treating Evidence Confidence as a close probability

## Current Automation Boundary

Automated:

- public Google Places lead collection when configured
- deterministic Growth Scores and quick raw-HTML audits
- optional PageSpeed checks with explicit not-run/configuration-required/failure/success states
- optional rendered Microsoft Edge verification, evidence snippets, and screenshots when Edge is available
- competitor matching, sample-grounded Industry Intelligence, reports, proposals, concepts, and outreach drafts
- CRM organization, authoritative interaction summaries, verification-gated approval, follow-up ordering, and suppression enforcement

Human-controlled:

- factual verification, Google ownership claims, and competitor approval
- outreach review, approval, copying, and sending
- the final selected price, business credentials, testimonials, licenses, and client facts
- production-site approval, integrations, hosting, legal/compliance decisions, and opt-out handling

The app does not automate sales outreach.

It does not build Android, APK, PWA, Electron, React Native, Flutter, or mobile functionality. The existing Infinity Rae Android project in the parent repo is intentionally untouched.

All code for this app lives under:

```text
local-presence-miner/
```

## Free Demo Mode

Demo mode works without:

- Google API keys
- OpenAI API keys
- Yelp API access
- PageSpeed API keys
- internet access

This is the best way to test the app first.

```powershell
cd local-presence-miner
.\run_windows.ps1
```

In the app:

1. Open **Lead Searches**.
2. Click **New Search**.
3. Leave **Demo mode** checked.
4. Pick a category, for example `Home Services / roofers`.
5. Keep `Flint`, `MI`, and ZIP `48502`.
6. Click **Run Search**.
7. Open **Leads**.
8. Double-click a lead.

Expected demo result:

- ranked leads appear in SQLite
- each lead gets a Growth Score
- each lead shows target signals
- competitors appear when enough demo businesses exist
- outreach drafts are generated
- a starting offer is generated
- reports and mockups can be generated locally

## CLI Quick Start

The Windows desktop app is the main workflow, but the CLI is useful for debugging, repeatable tests, and packaging a lead set for someone else to inspect.

Free offline/demo run:

```powershell
cd local-presence-miner
.\.venv\Scripts\python.exe -m local_presence_miner run --city "Flint" --state MI --niche roofers --offline --reports --report-kind owner_short --mockups --comparisons --packages --top-mockups 1 --export-csv --ai-mode prompt --out out\demo_cli --debug
```

Full v01.07 offline demo with proposals and concept website exports:

```powershell
.\.venv\Scripts\python.exe -m local_presence_miner run --city "Flint" --state MI --niche roofers --offline --reports --report-kind owner_full --mockups --comparisons --proposals --site-exports --packages --top-mockups 1 --export-csv --ai-mode prompt --out out\v0107_demo --debug
```

If `.venv` does not exist yet:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Preflight check:

```powershell
.\.venv\Scripts\python.exe -m local_presence_miner preflight --out out\preflight
```

Real online run, after setting `GOOGLE_MAPS_API_KEY`:

```powershell
.\.venv\Scripts\python.exe -m local_presence_miner run --city "Flint" --state MI --niche roofers --online --max-results 20 --reports --report-kind internal --comparisons --ai-mode prompt --out out\flint_roofers
```

Generated CLI outputs can include:

- `reports\`
- `mockups\`
- `comparisons\`
- `prompts\`
- `packages\`
- `proposals\`
- `site_exports\`
- `exports\leads.csv`

## Online / Offline Decision Tree

Use **offline/demo** when:

- you do not have a Google API key
- you are testing the app for free
- you want Matt or another tester to see the workflow without internet/API setup
- you are debugging reports, mockups, packages, prompts, scoring, or CRM flow

Use **online** when:

- `GOOGLE_MAPS_API_KEY` is set
- you want real local businesses from Google Places
- you are okay with live website requests during audits
- you understand public Places data cannot prove profile ownership

Use **AI off** when:

- you want deterministic local reports only
- you do not want to paste anything into ChatGPT

Use **AI prompt mode** when:

- you have ChatGPT Plus but no OpenAI API key
- you want the app to write paste-ready prompts under `prompts\`
- you want to paste ChatGPT's answer into the desktop **Prompt Paste** helper for local summarizing

`--ai-mode api` is intentionally treated as prompt mode in this build. A real API-backed AI worker should be added on a separate branch because it changes cost, privacy, error handling, and testing requirements.

## Usage Examples

### Example 1: Find No-Website Roofers

Use this when you want businesses that have commercial activity but no clear website.

Suggested search fields:

```text
City: Flint
State/region: MI
Business category: Home Services / roofers
Target ZIP: 48502
Target miles away: 10
Maximum results: 20
Minimum review count: 0
Minimum Google rating: 0
Include no website: yes
Include weak websites: yes
Include lower collected result position: yes
Include 0-20 review opportunities: yes
Demo mode: yes for testing, no for real Google data
```

What to look for:

- `No website listed`
- `Profile appears incomplete`
- `Review growth opportunity`
- `Lower collected result position`

Good first offer:

```text
Starter Local Presence Build
```

Simple first approach:

```text
I noticed your public profile does not currently list a website. I made a short public audit and a simple one-page concept showing how customers could call, trust, and request a quote faster. Want me to send it over?
```

### Example 2: Find Businesses That Would Look Stronger With 10-20 Reviews

Use this when a business looks real but not trusted enough yet.

Suggested search fields:

```text
Minimum review count: 0
Include 0-20 review opportunities: yes
Include no website: optional
Include weak websites: yes
Target miles away: 5-15
```

Target signals:

- review count below 20
- few public photos
- weak or missing trust proof on the website
- competitors have more reviews or stronger proof sections

Good first offer:

```text
Review Trust Builder
```

Example scope:

- review request script
- QR review card copy
- post-job text/email wording for the owner to send
- review reply templates
- website proof/review section
- Google profile review-response workflow

Simple first approach:

```text
I found a few public-facing trust gaps. You look like a real local business, but nearby competitors show more review proof and clearer contact paths. I made a small plan for getting the next 10-20 real reviews and making them more visible. Want me to send it?
```

### Example 3: Find Weak Website Opportunities

Use this when businesses have a site, but the site does not convert well.

Target website audit findings:

- no HTTPS
- no mobile viewport
- no tap-to-call link
- no quote/contact form
- no service pages
- no visible reviews/testimonials
- no LocalBusiness schema
- no clear primary CTA

Good first offer:

```text
Conversion Tune-Up
```

Simple first approach:

```text
I found a few public website gaps that may make mobile visitors work harder than they should: no obvious call/quote path, limited trust proof, and weaker local SEO basics. I made a short before/after improvement plan. Want me to send it over?
```

### Example 4: Starting From No Track Record

If you do not have case studies yet, do not fake them.

Use the app's **Previous sales/proof notes** field honestly:

```text
I am building my first few local case studies. I can offer a fixed-scope pilot and only ask for a testimonial if the work is useful.
```

Good first offer:

```text
No-Track-Record Pilot
```

Recommended first ask:

```text
Can I send you the audit and one-page concept?
```

Do not open with:

```text
I can get you ranked #1.
```

Do open with:

```text
I found a few public-facing gaps and made a simple concept for how I would make the business easier to trust and contact. If it is not useful, no pressure.
```

## Real Google Places Search

Real searches require a Google Maps API key.

Add the key in the app's **Settings** window, or create `.env` from `.env.example`:

```text
GOOGLE_MAPS_API_KEY=your_key_here
```

Then run:

```powershell
cd local-presence-miner
.\run_windows.ps1
```

In **New Search**, turn **Demo mode** off.

The Google Places service:

- uses the current Places Text Search endpoint
- requests only required fields through a field mask
- uses request timeouts
- retries transient failures
- supports pagination
- deduplicates by place ID
- shortlists candidates before requesting rich details instead of enriching the first results returned
- offers Economy (8), Balanced (20), and Deep Prospecting (40) detail caps
- shows an estimated Text Search + Place Details request count before the run
- preserves unrequested rich fields as Unknown

CLI example for a 100-business discovery search with a 20-candidate rich-detail cap:

```powershell
.\.venv\Scripts\python.exe -m local_presence_miner.cli run --online `
  --city Peoria --state IL --niche roofers --max-results 100 `
  --google-data-depth balanced
```

Controlled five-business acceptance run, after Google billing is activated:

```powershell
.\.venv\Scripts\python.exe -m local_presence_miner.cli run --online `
  --city Peoria --state IL --niche roofers --max-results 100 `
  --safe-live-test
```

Important: the app cannot prove whether a Google Business Profile is claimed. It uses **verification required** instead of saying **unclaimed**.

## Optional PageSpeed

PageSpeed is optional because it is slower and network/API-dependent.

In Settings or `.env`:

```text
PAGESPEED_API_KEY=your_key_here
```

In **New Search**, enable:

```text
Run PageSpeed checks: yes
```

Recorded fields, where available:

- performance
- accessibility
- best practices
- SEO

## Category Picker

The app includes a large searchable category dropdown so you do not have to invent niches from scratch.

Examples:

```text
Home Services / roofers
Home Services / plumbers
Home Services / electricians
Home Services / garage door repair
Health And Wellness / dentists
Beauty And Personal Care / barbers
Auto And Transportation / auto repair shops
Professional Services / accountants
Events / wedding photographers
High Intent Emergency / emergency plumbers
```

Good beginner categories:

- roofers
- plumbers
- garage door repair
- auto repair shops
- dentists
- barbers
- landscapers
- pest control
- towing companies
- med spas

These often have obvious website, review, quote, or trust gaps.

## Lead Scoring

The score is deterministic and transparent. Higher means a stronger sales opportunity.

Signals include:

- no website
- unreachable website
- weak website
- no HTTPS
- poor mobile readiness
- no tap-to-call link
- no contact/quote form
- missing service pages
- missing trust signals
- missing LocalBusiness schema
- incomplete Google-facing information
- few public photos
- low collected local result position
- 0-20 review-growth opportunity
- competitor website gap
- enough review activity to suggest real demand

The app does not give a high score just because a business has a low rating.

## Starting Offer Builder

Every lead gets an editable starting offer. The app auto-fills what it can, and you can fill the rest.

Editable fields:

- target ZIP code
- target mile radius
- business phone
- current website
- Google Maps URL
- Yelp/other profile URL
- current local result position
- review count and rating
- competitor names
- competitor review/website signals
- previous sales/proof notes

Generated output:

- offer name
- price range
- scope
- opening angle
- proof plan
- first ask
- risk reversal
- talk track

Example generated offer:

```text
Starter Local Presence Build for Old Town Roofers Co

Opening angle:
I found no website listed, profile appears incomplete, a lower collected result position, and a review growth opportunity.

Offer:
$750-$1,800 one-page local website plus Google profile cleanup.

First ask:
Ask for permission to send the short audit and one-page concept, not for a full project on first contact.
```

## Pricing Guidance

Pricing guidance is deliberately conservative when you have no track record.

The app can show:

- suggested offer name
- suggested range
- first-step pilot price
- rationale
- warnings

If **Previous sales/proof notes** is blank, the app steers toward:

```text
No-Track-Record Pilot
```

Important: the app does not recommend payment per posted review. Charge for legitimate work like the review request system, owner/staff scripts, QR card copy, reply templates, website proof sections, and profile cleanup. Do not sell fake reviews, guaranteed review counts, or disguised review activity.

Fair starter pricing menu:

| Tier | Fair range | Use when |
| --- | --- | --- |
| Presence Audit | $0-$150 | first contact, qualification, or no-track-record proof |
| Owner-Ready Proposal + Mockup | $150-$450 | warm lead wants to see the plan |
| Static Local Website | $750-$1,800 | no/weak site, needs mobile contact flow |
| Conversion Site + Google Cleanup | $1,200-$2,800 | site plus profile/contact/review proof cleanup |
| Local Authority Site | $2,500-$6,500+ | multiple service pages and stronger proof system |
| Review Request System | $300-$900 | legitimate scripts/templates/workflow, not paid reviews |
| Human-Managed Chat Bubble | $250-$900 setup + $100-$500/mo | chat UI routed to a person, email, CRM, or chat provider |
| AI Answer Bubble | $750-$2,500 setup + API/platform costs + $150-$750/mo | real AI assistant with approved source docs and monitoring |

Beginner rule: start near the low end until you have proof. Charge more for real implementation, integrations, forms, hosting, source-document setup, monthly monitoring, and revisions.

AI/chat bubble rule: a visual bubble is just UI. A real AI answer bubble costs more because it needs an AI provider, approved FAQ/source material, handoff rules, safety limits, lead capture, and ongoing review.

## Prompt Paste Workflow

Use this when you have ChatGPT Plus but no OpenAI API key.

1. Generate a competitor comparison with `--ai-mode prompt`, or click **Open competitor comparison** in the desktop app.
2. Open the generated prompt under `prompts\`.
3. Paste it into ChatGPT.
4. Copy ChatGPT's answer.
5. Open **Prompt Paste** in the desktop app.
6. Paste the answer and click **Parse Answer Preview**.
7. Treat the parsed result as a draft. Verify claims manually before sending anything to a business owner.

The app does not need to be tied to your ChatGPT account for this workflow. Tying directly into an OpenAI API key can be added later, but it should be a separate branch because it introduces cost controls, privacy handling, rate limits, and failure modes.

## Outreach Drafts

The app generates editable drafts only.

Draft types:

- initial cold email
- short follow-up
- final follow-up
- interested-reply email
- price-reply email using live Seller Pricing Intelligence
- existing-provider reply email
- not-now / needs-time reply email
- call opening script
- voicemail script
- report-delivery email
- mockup-delivery email

Every draft is grounded in observed findings. The wording avoids unsupported claims. Guided Call adds nested branches for price, value uncertainty, competing quotes, timing, another approver, business capacity, better-fit work, easier intake, guarantees, and a clear request to stop.

The drafts should say:

```text
I noticed your website is not currently listed on the public profile.
```

They should not say:

```text
Your Google listing is unclaimed.
```

unless a human manually verified that.

## Review And CRM Workflow

Recommended workflow:

1. Run a demo or real search.
2. Open **Leads**.
3. Sort/filter by high score and priority.
4. Double-click a lead. Use **Review Queue** to see only New and Needs Review leads.
5. Review target signals, audit findings, competitors, and starting offer.
6. Edit ZIP/radius/profile links/previous proof notes if needed.
7. Generate a report.
8. Generate a mockup.
9. In **Lead & CRM**, correct contact details and record the owner, tags, notes, contact method/outcome, and follow-up date.
10. Edit outreach drafts, then explicitly approve only the draft you reviewed. Editing it later clears approval.
11. Mark the lead **Qualified**, **Not Qualified**, **Contacted**, or **Do Not Contact** as work progresses.
12. Add suppressed businesses to the suppression list; suppressed leads cannot have approved outreach.
13. Export CSV only after review.

SQLite is the source of truth. CSV files are exports, not the app database.

## Reports And Mockups

Reports are HTML and printable from Windows browsers.

Report density options:

- `owner_short`: shareable after manual review; hides internal scoring detail, competitor table, and outreach drafts.
- `owner_full`: shareable after manual review; includes more audit and competitor context, but not internal outreach drafts.
- `internal`: operator-only; includes outreach drafts and deeper scoring context.

Reports include:

- business overview
- Growth Score
- target signals
- score breakdown
- website audit
- Google-facing observations
- competitor comparison
- recommended offer
- outreach drafts in internal reports
- disclaimers

Competitor comparison reports are written under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\comparisons\
```

They rate the target and top competitors on:

- completeness
- UI friendliness
- presentation readiness based on observable structure and trust signals
- customer interaction friendliness
- overall efficiency

The comparison also explains what makes a good website for that business type and writes a paste-ready ChatGPT prompt under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\prompts\
```

Mockups are generated static one-page concepts. They include:

- business name
- niche-relevant headline
- city/region positioning
- phone CTA
- quote CTA
- services
- trust section
- FAQ/contact area

Mockups are concepts only. They do not copy competitor branding, text, logos, or exact layouts.

Lead packages are ZIP files under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\packages\
```

Each package includes the owner report, mockup, competitor comparison, AI prompt text when enabled, and a manifest with the most important warnings for testers.

## Paid-Style Website Export

The app includes static website concept-folder exports under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\site_exports\
```

Each export includes:

- `index.html`
- `styles.css`
- `README_FOR_BUILDER.md`
- `AI_WEBSITE_BUILDER_PROMPT.md` when exported from the live app/database
- `LOVABLE_PROMPT.md` when exported from the live app/database
- `CANVA_WEBSITE_PROMPT.md` when exported from the live app/database
- `assets\PUT_HERO_VIDEO_HERE.txt`


### Competitor-grounded AI builder prompts

When a lead has been compared with selected competitors, Local Presence Miner now generates builder prompts from the actual stored target audit and competitor audit evidence. The prompts include:

- public target facts
- current target strengths and weaknesses
- selected competitor names, websites, selection reasons, readiness scores, strengths, and weaknesses
- evidence-backed target-vs-competitor gaps with honest denominators
- category-based service ideas explicitly labeled as items to verify
- a required homepage structure and demo goals
- strict rules against inventing testimonials, licenses, warranties, service areas, pricing, or other private facts
- screenshot paths when rendered evidence exists

Three variants are written:

```text
<Business>__AI-WEBSITE-BUILDER-PROMPT.md
<Business>__LOVABLE-PROMPT.md
<Business>__CANVA-WEBSITE-PROMPT.md
```

The generic version is platform-neutral. The Lovable version requests plan-first implementation and a focused prospect demo. The Canva version emphasizes a concise single-page visual website concept. None of these files automatically contact an external AI builder.

The exported site is meant to feel closer to a paid local-service website:

- sticky desktop nav
- premium hero section
- optional muted video background slot
- service cards
- trust/proof section
- Google presence fixes
- customer process
- FAQ
- quote form markup
- sticky mobile call/quote CTA
- optional chat/AI bubble placeholder
- local schema placeholder
- package/pricing section

Hero video instructions:

```text
site_exports\<lead>\assets\hero-video.mp4
```

Use a 7-10 second muted looping MP4. For example:

- real estate: mansion/interior/exterior pan
- roofing: roofline, truck arrival, inspection, crew footage
- salon/barber: clean interior, chair, finished cut/style footage
- auto: shop bay, lift, diagnostics, detailing shot
- dental/medical: office pan, front desk, clean treatment room

Use real business footage or properly licensed stock. Do not copy competitor media.

The chat bubble is optional UI only until connected. Sell it as a separate add-on if you connect human chat, CRM routing, or a real AI answer system.

## Export Example

From the app:

1. Open **Reports**.
2. Click **Export Leads CSV**.

The export is written under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\exports\
```

CSV export includes:

- status
- priority
- score
- business name
- phone
- website
- Google/Yelp links
- rating/reviews
- local result position
- recommended offer
- target signals
- suppression flag
- follow-up fields
- notes

## Suppression List

Use suppression for:

- opt-outs
- do-not-contact businesses
- duplicate domains
- phone numbers you should not contact
- businesses you manually reject

Suppressed leads:

- are visually marked
- cannot be approved for contact
- are excluded from safe outreach approval

## Data Locations

Runtime data is stored under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\
```

This includes:

- SQLite database
- settings
- logs
- generated reports
- generated mockups
- exports
- rendered-verification screenshots, when explicitly enabled and Microsoft Edge is available

Runtime data is not written to Program Files.

Google Maps and PageSpeed API keys saved through Settings are protected with Windows user-scoped encryption. Other operator settings remain readable local configuration. Saved settings take effect immediately.

### v0.1.11 credibility migration

When an already integrity-hardened v0.1.11 database contains the older Seller Proof and Contact Interaction tables but not the credibility fields, startup creates:

```text
local_presence_miner.sqlite3.backup-before-v0111-credibility
```

before adding the new columns. The copy is created once and is never overwritten on later starts. Existing leads, interactions, offers, verification state, pricing history, and proof rows remain in place. Legacy proof receives `Unclassified`, and credibility booleans default to false; this intentionally favors manual review over invented history.

The earlier `.backup-before-v0111` safeguard for Google/rich-refresh migration remains intact. A database that still needs both upgrades may receive both backups because each protects a different schema boundary.

## Windows Source Run

```powershell
cd local-presence-miner
.\run_windows.ps1
```

The script:

1. creates `.venv` if missing
2. installs requirements
3. launches the PySide6 desktop app
4. prints readable startup errors

## Windows Build

```powershell
cd local-presence-miner
.\build_windows.ps1
```

The script:

1. creates a clean `.build-venv`
2. installs dev/build dependencies
3. runs pytest
4. runs Ruff
5. builds a PyInstaller executable
6. writes the packaged app to:

```text
dist\LocalPresenceMiner\
```

Main executable:

```text
dist\LocalPresenceMiner\LocalPresenceMiner.exe
```

The packaged app should not require Python to already be installed.

## Tests And Checks

Run tests:

```powershell
cd local-presence-miner
.\.venv\Scripts\python.exe -m pytest
```

Run lint:

```powershell
cd local-presence-miner
.\.venv\Scripts\python.exe -m ruff check .
```

Current coverage includes:

- proof-ledger status/provenance boundaries and truthful experience language
- same-niche relevance ranking, proof attachments, and unsupported-claim prevention
- first-90-second credibility/AI call branches and structured conversation memory
- proof-aware email/proposal/report regeneration and approved-draft immutability
- Practice/Live isolation, Back rollback, competitor verification, and DNC enforcement
- v0.1.11 credibility backup/migration preservation
- scoring boundaries
- category catalog
- competitor selection
- outreach wording guardrails
- SQLite persistence
- CSV export
- report generation
- mockup generation
- suppression enforcement
- website-audit helpers

## Project Structure

```text
local-presence-miner/
  app.py
  run_windows.ps1
  build_windows.ps1
  pyproject.toml
  requirements.txt
  requirements-dev.txt
  local_presence_miner/
    cli.py        repeatable run, preflight, debug, package generation
    domain/       scoring, categories, models, competitor matching
    database/     SQLAlchemy schema and repositories
    services/     Google Places, audits, offers, outreach, comparisons, proposals, packages, site exports
    ui/           PySide6 desktop interface
    templates/    Jinja2 report, comparison, and mockup templates
    assets/       QSS styling and packaged assets
  sample_data/    offline demo businesses
  tests/          pytest coverage
  docs/           architecture, data model, compliance
```

## Known Limitations

- Rendered browser audits require an installed Microsoft Edge browser. The UI disables them with an explanation when unavailable.
- Yelp is stored as an operator-filled profile URL; there is no Yelp API integration in this version.
- PageSpeed is optional and depends on network/API availability.
- Collected Places result order, where retained, is only a **Places search visibility proxy**. It is not presented as an exact Google Maps or Map Pack ranking.
- Google profile ownership cannot be proven from public Places data. Treat it as **verification required**.
- Direct OpenAI API chat is not included in this version. The supported AI path is prompt-paste: generate prompt files, use ChatGPT Plus manually, then paste the answer into the local parser.
- The exported chat bubble is a front-end placeholder until connected to human chat, a form backend, CRM, or a real AI provider.
- Site exports need real copy, photos/video, service facts, form wiring, hosting, and final QA before being sold as finished live websites.

## Compliance Notes

This app is a research, audit, drafting, and CRM tool.

It does not implement:

- robocalling
- prerecorded cold calls
- automatic AI cold calls
- automatic SMS blasting
- CAPTCHA bypass
- private data scraping
- login bypass
- hidden email harvesting
- automatic mass email sending
- fake reviews
- review manipulation
- competitor content copying

Operator responsibilities:

- review every draft before outreach
- use truthful sender information
- include lawful contact and opt-out information where required
- honor opt-outs
- distinguish observations from conclusions
- do not guarantee rankings, revenue, or call volume
- do not claim a profile is unclaimed unless manually verified

## Troubleshooting

If the app does not start:

```powershell
cd local-presence-miner
.\.venv\Scripts\python.exe app.py
```

Check logs under:

```text
%LOCALAPPDATA%\LocalPresenceMiner\logs\
```

If dependency installation fails, delete `.venv` and rerun:

```powershell
Remove-Item .venv -Recurse -Force
.\run_windows.ps1
```

If the packaged app fails, rebuild:

```powershell
.\build_windows.ps1
```
