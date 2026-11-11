# November 11 decision-brief correction candidate

This isolated correction starts from the exact 310-file November 10 candidate,
SHA-256 570d66746cf80793da01f0578ddc42b8d8585d030b478a20f29ca271a0257dc2.
Use the accompanying correction manifest, receipts and handoff for final identity.
Policy v4 / output schema 2 correct disclosure, typed evidence/action use, agreement
binding, operator self-report, active request invalidation and provider receipts.
Historical records remain retained. Live model quality and independent acceptance
remain separate verification gates.

# MarketLens — Codex cloud continuation

## November 10 decision-brief candidate

This isolated development increment builds on the verified 304-file citation correction, SHA-256
`b6e122bae02cea9dfd1aa13de5ca9ea72b4a4932f2c3002762ad40b0d46da7df`, which was not yet on the November 9 GitHub branch.
The earlier live receipt belongs to that citation correction, not this decision-brief candidate.
Read the accompanying decision-brief implementation handoff and current manifests for final verification.
Policy v3 adds explicitly selected source context, mode-specific decision tasks, supported reasoning effort,
conservative support presentation, readable source/history inspection and navigation into existing owner-confirmation workflows.
No new live inference or provider research is implied by offline verification. Earlier sections below are historical context.

2026-11-09. Development candidate; independent acceptance and release are separate gates.

November 10 citation correction: advice uses interpretation policy `opportunity-advice.v2`, short packet-local citation labels and schema-enumerated allowed labels. Canonical finding references and hashes remain in immutable snapshots; strict context/source validation is preserved. Older advice stays historical and cannot silently dispatch or be adopted. See `handoff/intelligence-citation-20261110/` for the updated source identity and actual verification outcome; earlier quota-blocked receipts remain historical evidence.

## Correct source

This branch contains the corrected November 8 Pass 1 source plus optional Guided Opportunity intelligence. The verified parent contains 288 files and has tested-tree SHA-256 `67f0e9b454ce28c14328bc55ec6c00087266f72ebd42f87cd8d75af2e7bcd3d5`. The underlying local parent commit is `1b830a0ffd3650f8924961cc6f05d3b77463f303`; the dirty correction overlay is part of that parent identity.

GitHub main previously contained the older October checkpoint `a639cf5d5a3ef07da7ec44b4f9df56d1db22f800`. This development branch advances source content beyond that checkpoint; do not treat main as the current candidate or rerun old research/audits as a prerequisite. The source manifest and implementation evidence accompany this branch under `handoff/intelligence-20261109/`.

## Setup and first checks

Choose this development branch when starting a cloud task. Configure Python 3.11. Run `bash .codex/cloud_setup.sh`; it creates `.venv` and installs the declared dependencies. Linux system libraries may require environment-admin setup if the script is not running as root. The setup script is supplied for Codex cloud; its execution there must be verified, not inferred from the Windows receipts.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_opportunity_intelligence.py tests/test_chatgpt_auth.py tests/test_chatgpt_inference.py tests/test_opportunity_intelligence_ui.py
.venv/bin/python -m ruff check .
.venv/bin/python -m compileall -q local_presence_miner app.py
.venv/bin/python -m mypy local_presence_miner
```

Use the handoff receipts for the actual Windows result and final candidate identity. Windows baseline: 1,311 passing tests, Ruff clean, 91 historical mypy errors. The first full parallel candidate check had 1,371 passes and two existing subprocess startup-timeout failures; the exact two controls passed sequentially. Subsequent bounded corrections and their verification are recorded in the accompanying implementation handoff; do not substitute this historical count for its final receipt.

Full regression is `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`. Keep the real cross-process startup/death controls sequential on resource-constrained machines; do not weaken their assertions to hide scheduling failures. Windows-specific tests should accurately report their platform restrictions. A Linux result does not verify Windows credentials or application packaging.

## Implemented behavior and limits

- Optional AI panel inside Guided Opportunity, Off by default, explicit per-request disclosure and no autonomous tools/retries.
- Readable context preview and normal advice display; exact structured data retained for inspection.
- Three bounded modes over supplied evidence. No live web research, API-key billing fallback or commercial decision authority.
- App-owned ChatGPT OAuth and protected Windows storage; no copied Codex/browser credentials. Model availability is account-specific.
- Separate append-only run/result/review history. Questions and next actions can be explicitly appended to a new worksheet; owner confirmation and commercial approvals remain in existing workflows.
- Website/owner findings are selected explicitly; raw manual AI-discoverability prompts remain withheld. Corrupt source claims are excluded. Freshness and concurrent revisions block stale adoption.

Native Windows sign-in successfully listed eight account-supported models. The initial real inference attempt failed at the local stream wire-size guard, after HTTP 200; event-envelope overhead was wrongly tied too tightly to accepted answer bytes. See the final handoff for the fix and actual live retry outcome. Never claim an API failure was caused by quota or authentication without its receipt.

No Windows tokens, prospect data, database or account session belongs in cloud. Use synthetic fixtures. Existing local DPAPI credentials are tied to Windows and are deliberately unavailable in cloud. Remote access to the application itself is deferred; this setup is for continuing code work.

## Next task boundary

Read the accompanying final implementation status first. Verify source identity and reproduce focused checks. Resolve only recorded open items or the user's next explicit request; do not reopen the product architecture, automate outreach, perform ranking research, redesign pricing or declare acceptance from a passing test alone.
