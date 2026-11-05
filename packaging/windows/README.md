# MarketLens Local v0.1.16 — Search Visibility Evidence

This is the v0.1.16 implementation candidate. The application displays 0.1.16; Windows FileVersion and ProductVersion are 0.1.16.0.

## Start here

1. Extract the entire ZIP to a normal folder. Do not run it from inside the ZIP.
2. Keep `MarketLensLocal.exe` beside the `_internal` folder.
3. Double-click `START_MARKETLENS_LOCAL.bat` or `MarketLensLocal.exe`.
4. Start with **Demo mode**. It needs no API key or internet connection.

## What this build does

- Finds and ranks local-business opportunities
- Preserves one canonical CRM lead across rediscovery while retaining each Search Run membership
- Prevents overlapping searches for the same database across threads and separately launched MarketLens processes
- Shows honest Completed, Completed With Errors, Partial, Failed, Interrupted / Partial, and Interrupted / Failed run states with counters
- Recovers stale Running rows after abrupt process death without touching a currently locked run
- Records a missing Google Place ID as a candidate-local failure and continues later candidates
- Revokes outreach readiness when current viability changes, without deleting approved text/history
- Uses stable collision-resistant paths for every per-lead artifact family
- Streams and caps decoded public HTTP responses while preserving DNS pinning and SSRF protections
- Shows a Growth Score and observed Revenue Leaks
- Provides Owner Mode conversation guidance
- Summarizes collected niche patterns in Industry Intelligence
- Creates reports, comparisons, proposals, mockups, and static site starters
- Stores editable CRM records and reviewed outreach drafts locally
- Preserves contact history and sorts due/overdue follow-ups first
- Recalculates CRM contact summaries after every interaction edit or deletion
- Requires minimum factual verification before an outreach draft can be approved
- Security-skips rendered-browser fetching until redirects, DNS, and every subresource can use the same public-network policy
- Keeps ordinary public Website Audit and Contact Discovery enabled through validated, DNS-pinned transport
- Embeds available screenshots in internal reports for portable evidence review
- Keeps Project Value separate from private seller-calibrated Easy-Close, Recommended, and Stretch asks
- Stores private proof, offer outcomes, actual close amounts, structured loss reasons, and historical evidence snapshots
- Requires an explicit action before an offer is recorded as presented
- Keeps private seller history and pricing analytics out of customer proposals and prospect lead packages
- Adds a pre-contact sales cockpit, evidence-review states, visual competitor comparison, and structured manual contact outcomes
- Adds High Qualification Intelligence and Extra High adaptive Smart Offers, email replies, and recursive Guided Call branches
- Preserves active conversation facts when commercial guidance refreshes and blocks stale/internal reply copying
- Persists stable Guided Call tree/node/strategy identity, exact response snapshots, and displayed/copied/used event order
- Requires the operator to confirm a truthful contact outcome instead of silently defaulting a live interaction to No answer
- Adds a structured Credibility & Proof ledger that separates Completed, In Progress, Prototype, Concept Only, and legacy Unclassified evidence
- Ranks truthful seller proof for each niche and shows a compact WHY YOU / Do Not Claim call card
- Handles skeptical first-contact questions about identity, company, location, experience, proof, references, legitimacy, access/payment, and AI
- Stores specific credibility concerns in Live Call conversation memory and adapts later follow-up, reports, and proposals
- Recommends Send / Optional / Do Not Send proof artifacts without exposing private pricing or internal notes
- Preserves neutral call startup, Practice/Live isolation, full Back rollback, exact suppression, and approved-draft immutability
- Separates public Google Presence Strength from improvement Opportunity and feeds the opportunity into Sales Priority and Smart Offer scope
- Uses only supported public Places fields for prospects; no private Business Profile access or exact Maps-ranking claims
- Shortlists cheap discovery results before rich Place Details; Economy enriches up to 8, Balanced 20, and Deep Prospecting 40
- Shows an upper-bound Google request count before live search and keeps unrequested website/review/phone/hours/photo fields Unknown
- Uses live Seller Pricing Intelligence amounts in price language; actual seller proof/history must be entered manually
- Keeps Hold/Reject work in review and blocks suppressed, Opted Out, and Do Not Contact leads from outreach export

The app does not send email, submit forms, SMS, calls, robocalls, or AI voice outreach. It does not estimate lost revenue without explicit assumptions. Generated sites are concepts until manually completed and approved. Human review is required before using any claim, offer, price, or draft.

Before using credibility responses, manually configure **Pricing Intelligence → Seller Profile**, then review every record under **Credibility & Proof**. Choose the real status, client-work/AI flags, provenance, Safe claims, and Do Not Claim boundaries. Legacy records are Unclassified until you review them. Never mark a prototype as completed client work or share a direct reference without permission.

Cold outreach is always manual: verify the lead and selected contact route, review/approve the exact draft, send it using your own email/phone tool, record the real outcome, and honor opt-outs or Do Not Contact immediately.

Real Google searches require a Google Maps API key in **Settings**. Saved API keys are encrypted for the current Windows user.

Google Cloud billing must be active for the real Places Safe Live Test. Demo Mode uses bundled public-data-style fixtures and makes no network request.

Local data and outputs are stored under `%LOCALAPPDATA%\LocalPresenceMiner\` by default.

If the app does not start, read `TROUBLESHOOTING.txt`.

For full usage examples, manual-entry/outreach boundaries, migration details, and proof-state rules, read `FULL_README.md`, `V0113_STATE_WORKFLOW_HARDENING.md`, `V0112_PASS1_INTEGRITY.md`, and `KNOWN_DEFERRED_ISSUES.md`.
