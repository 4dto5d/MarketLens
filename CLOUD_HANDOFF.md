# MarketLens — Codex cloud continuation

2026-11-09. Development candidate; independent acceptance and release are separate gates.

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
