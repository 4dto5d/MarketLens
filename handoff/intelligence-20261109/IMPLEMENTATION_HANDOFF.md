# MarketLens — optional intelligence implementation

November 9, 2026. Delivered for independent review; not accepted or released.

## Identity and preservation

- Verified parent: 288 files, SHA-256 `67f0e9b454ce28c14328bc55ec6c00087266f72ebd42f87cd8d75af2e7bcd3d5`.
- Final candidate: 303 files, SHA-256 `7617b41a14acaf0f486f3f7064a801713e5847aac9b49583919fccf0edc39f36`.
- Exact delta: 15 added / 4 modified / 0 deleted; see `CHANGED_FILES.json` and `IMPLEMENTATION.patch`.
- Underlying local parent commit: `1b830a0ffd3650f8924961cc6f05d3b77463f303`, plus its verified correction overlay. Original checkout preserved; implementation is isolated in `worktree`, with verified bytes in `verified-source`.
- GitHub source commit: `93543e1f49f844b263c1527a128536cefc034bc5`, branch `codex/opportunity-intelligence-cloud-20261109`. Remote ref was independently checked using `git ls-remote`. Main remains unchanged. Later handoff-only commits are outside the 303-file tested-source manifest.

## Implemented increment

Optional intelligence inside Guided Opportunity, Off by default. Each request requires a readable disclosure preview, with exact technical details available separately. Normal advice is rendered in plain language. Focused, Full Prospect and Deep Investigation are single requests over selected supplied evidence, with no tools, research loop or automatic inference retry.

Source context preserves review, freshness, fact/inference and owner-attribution distinctions. Findings are selected explicitly, worksheets require opt-in, corrupt source claims are removed, and raw manual AI-observation prompts remain withheld. Current commercial and delivery constraints remain visible. No model output becomes a verified finding or owner confirmation.

Advice has a separate append-only run/result/review ledger. An explicit operator action can append a question or next action to a new worksheet revision; prior human text and source history remain intact. Same-business, account, source and worksheet bindings are rechecked before adoption. Generated advice cannot select an offer, quote, approve outreach, change qualification/DNC or authorize delivery.

App-owned ChatGPT authentication uses loopback PKCE, validated OIDC, account-bound credentials, rotating refresh and protected Windows storage outside OneDrive. No Codex/browser credentials or API-key billing fallback. Protected storage initializes lazily, allowing an Off panel to construct on non-Windows systems without a plaintext fallback.

## Live verification and corrections

The user completed native Windows sign-in; eight account-supported models were listed. Real synthetic GPT-6.1 Sol requests exposed and reproduced a client defect: token-sized SSE envelopes exceeded a wire-processing cap before the accepted answer limit. A realistic regression demonstrates the defect. The separate finite wire allowance was increased while output and individual-event bounds remain enforced.

A subsequent request reached the original 60-second deadline and exposed a concurrent socket-close AttributeError. Timeout/cancellation are now safely normalized. Based on the observed runtime, local deadlines became 180/240/360 seconds for Focused/Full/Deep. Input and accepted-output bounds remain 24/64/128 KiB and 16/32/64 KiB; instructions request concise answers. These defaults are not measured savings or latency guarantees.

The last explicitly counted synthetic attempt returned HTTP 200 followed by a provider `quota` failure. No completed inference was accepted. Actual canonical offer, scope, price availability, qualification, Call Guide, delivery and outreach projections remained identical before/after (`commercial_unchanged:true` in `live/RUN4_VERIFICATION.json`). This does not establish universal plan exhaustion or a reset time. No further model requests were sent.

Local daily limits were explicitly raised 1→2→3→4 for diagnostics; failed dispatches remain counted. Authentication/catalog are verified. **Completed live inference and reasoning quality remain quota-blocked/unverified.** Test doubles are labeled and do not establish ChatGPT/Claude performance. No five-case LLM comparison was invented.

## Verification

- Fresh baseline full pytest: **1,311 passed**.
- Corrected focused suite: **69 passed**. Includes persistence/reopen, actual commercial consumers, UI, JWT/PKCE/DPAPI, realistic stream limits and failure controls.
- Final complete regression: **1,378 passed**, plus **2 passed** sequential process controls: **1,380 total passing cases**. All collected cases are accounted for. See `VERIFICATION_RESULTS.json` and full command/exit-code receipts.
- Earlier full parallel run: 1,371 passed, two existing subprocess startup-deadline failures; both exact controls passed sequentially. Assertions were preserved.
- Final Ruff and compileall: passed.
- Mypy: **91 historical errors / 0 new**, normalized diagnostics compared.
- Windows Qt: actual dialog/preview checks, dark styling, native synthetic test window and user-performed sign-in. No independent usability acceptance or Windows executable build.

The native screenshot depicts the synthetic panel before sign-in. The readable-preview image is a separate Qt offscreen capture with explicit Segoe UI loading. Neither contains credentials. Full logs and command/exit-code receipts identify fresh versus superseded checks.

## Migration and boundaries

Three additive advice-ledger tables, linked to Lead and adopted ActivityLog records. SQLite guards enforce append-only history, same-business ownership, single finalization, FK integrity and preservation of referenced records. Repeat initialization and database integrity/FK checks are covered. No old rows are inferred into AI facts or approvals; no destructive migration.

No canonical Offer ID, pricing, scoring, Qualification, contact/DNC, finding or approval-contract change. No automated AI discoverability, external research, customer-facing generated copy, scope/price adoption, economics automation, autonomous delivery, merge or release. The first slice explicitly adopts only questions and next actions.

## Cloud continuation and shortcuts

The branch includes `AGENTS.md`, `CLOUD_HANDOFF.md` and `.codex/cloud_setup.sh`. No saved Codex cloud environment exists, and available tools cannot create/publish one. Follow `CLOUD_SETUP_STEPS.md` for the one-time setup. Linux installation/execution remains unverified; Windows receipts are not cloud provisioning evidence. Credentials, private prospect records and databases are excluded from GitHub/cloud. Remote operation of the app itself is deferred.

Desktop shortcuts:

- **MarketLens - Current Candidate**: frozen candidate using the project venv and normal application settings.
- **MarketLens - AI Connection Test**: isolated synthetic test database, with no automatic inference.

## Remaining gates and limitations

Independent review of source/security/migration contracts; a completed bounded model answer after quota availability returns; captured reasoning-quality and operator-effort evaluation; actual Codex cloud environment setup. No rankings, revenue, buyer-budget, ROI or token-saving claims are established.

No authenticated usage percentage/meter was available. Failed streams provided no completed token-usage receipt. Percentages, monetary cost and reset times are not invented.

## Reproduction

Use Python 3.11, `requirements-dev.txt`, and `QT_QPA_PLATFORM=offscreen` for automated Qt checks. `ENVIRONMENT_LOCK.txt` captures the local environment. Production dependency additions are `PyJWT[crypto]==2.10.1` and `filelock==3.20.0`; pytest-xdist is verification tooling. Exact source and parent counterparts, manifests, patch and receipts accompany this handoff. The bundle is an audit artifact, not a Windows release package.
