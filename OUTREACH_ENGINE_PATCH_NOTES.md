# Local Presence Miner — Outreach Engine Patch Notes

FILE_STUB: 2026-08-24__local-presence-miner__v01.08-outreach-engine-v1-source

This patch builds on the v0.1.8 source plus the prior competitor-grounded website-builder prompt fix.
It intentionally does **not** bump the application version or create a Windows release. The next Windows/Codex build should preserve these changes and decide the release/version boundary.

## Implemented

### Public contact discovery
- New `ContactPoint` persistence model.
- Conservative official-website contact discovery via `WebsiteContactDiscovery`.
- Checks the official homepage plus a small number of ordinary contact/about/team pages.
- Finds only visibly published contact data or ordinary `mailto:` / `tel:` links.
- Can store public email, phone, contact-page, and supported social-profile links with source URL and confidence.
- Does **not** guess emails, decode hidden/obfuscated addresses, scrape data brokers, bypass access controls, or infer private contact information.
- Google Places phone remains available as a public source when already captured on the Lead.

### Batch public contact discovery
- Outreach screen can launch a background batch contact-discovery pass.
- Operator chooses 1–100 top unsuppressed leads.
- Runs sequentially with the configured request delay rather than high-concurrency crawling.
- Saves discovered public contact points locally.

### Preferred contact route
- Lead Detail now has a `Contact Intelligence` tab.
- Displays discovered contacts, evidence/source pages, and confidence.
- Operator can explicitly select the preferred contact route.
- Channel planner supports Email, Phone, Contact Form, Contact Research, and suppression-blocked states.
- The selected contact route overrides the default email-first behavior.

### Outreach batch export
- Outreach screen exports `outreach-ready.csv`.
- Only exports leads with an appropriate approved draft, required verification, no suppression block, and a usable contact route.
- Also exports `outreach-needs-review.csv` with the specific reason every skipped lead is not ready.
- Export is preparation only. It does not send email, submit forms, or place calls.

### Outreach copy improvements
- Initial email and follow-ups were tightened for cold outreach.
- Initial email uses only the strongest 1–2 target signals rather than dumping the audit.
- Search-generated drafts receive the selected competitor records as context.
- Competitor language stays generic/evidence-bounded rather than claiming unsupported rank/revenue effects.
- Existing sender identity and opt-out line are preserved.

### Guided Call Mode
- New `GuidedCallDialog`.
- 15-second, 30-second, and full opening options.
- Live “what did they say?” branch buttons.
- Lead-specific pricing answer comes from existing Seller Pricing Intelligence.
- Common branches include:
  - interested / what did you find?
  - happy with current website
  - already has provider
  - how much?
  - too expensive
  - need to think
  - send information
  - busy / bad time
  - no need for new website
  - AI website concern
  - already busy enough
  - how did you get this number?
  - what are you selling?
  - not interested
- Important branches have second-level replies:
  - too expensive -> budget / not convinced of value / cheaper provider
  - need to think -> price / timing / another decision maker
- Call Mode shows the currently preferred public contact route.
- `Record Call Outcome` opens the existing structured interaction dialog with Phone preselected.

### Outcome vocabulary
Expanded structured outcome/objection options for:
- requested information
- needs approval
- AI concern
- already busy enough
- cheaper provider

### Suppression integrity
- Suppression matching now includes discovered `ContactPoint` values such as public emails.
- Suppressing a discovered email can suppress the associated lead and unapprove outreach.
- Suppressing a lead also stores its discovered public contact values in the suppression system.

### Existing website-builder prompt fix preserved
The patch still includes the earlier changes that generate:
- generic competitor-grounded AI website-builder prompt
- Lovable-specific prompt
- Canva Website-specific prompt
and include them in exports/packages without fabricating business claims.

## Tests run in this environment

- `python -m compileall` succeeds for application and tests.
- Non-UI regression suite: **41 passed, 1 skipped**.
- The skipped case is Windows-only behavior.
- New tests cover:
  - public email/phone/contact-page discovery
  - no guessed contacts when no website exists
  - email-first channel planning
  - operator-selected phone override
  - suppression block
  - common guided-call branches
  - revised outreach copy
  - ContactPoint persistence
  - approved/verified outreach batch export
  - suppression by discovered email

## Not verified here

This Linux runtime does not have PySide6 and cannot build/run the Windows EXE.
Ruff also cannot be installed because this runtime has no package-network access.

Codex/Windows must still run:
- Ruff
- complete PySide6 test suite
- Lead Detail `Contact Intelligence` tab smoke test
- batch public-contact discovery UI smoke test
- Guided Call dialog smoke test
- nested objection-button smoke test
- Contact Interaction dialog from Guided Call
- Outreach Ready + Needs Review CSV export smoke test
- existing v0.1.8 database upgrade with automatic creation of `contact_points`
- PyInstaller build
- clean ZIP extraction/startup

## Deliberately not implemented

- automatic email sending
- automatic SMS
- robocalling / AI-spoken calls
- automatic contact-form submission
- Apollo API enrichment
- guessed/private email generation
- LinkedIn scraping
- CAPTCHA/login/paywall bypass
- decision-maker identity claims without a real source

Those should remain separate provider/integration work after the public-contact + human-led outreach workflow is stable.
