# Local Presence Miner v01.08 — Competitor-Grounded Builder Prompt Fix

FILE_STUB: 2026-08-24__local-presence-miner__v01.08-builder-prompt-fix-v1

This source patch keeps the application version at v0.1.8 and fixes the AI website-builder handoff without changing the database schema.

## What changed

- Added `WebsiteBuilderPromptService`.
- Generates three evidence-grounded files per lead:
  - `<Business>__AI-WEBSITE-BUILDER-PROMPT.md`
  - `<Business>__LOVABLE-PROMPT.md`
  - `<Business>__CANVA-WEBSITE-PROMPT.md`
- Prompts use the stored target audit plus selected competitor audits instead of a generic one-line builder instruction.
- Prompts include target public facts, audit strengths/weaknesses, selected competitor evidence, screenshot paths, and target-vs-competitor gap denominators.
- Category-derived service ideas are explicitly labeled as unverified suggestions.
- Added strict no-invention rules for testimonials, credentials, warranties, pricing, service areas, and other unsupported facts.
- Static site exports created from a live session now include all three prompt files and embed the generic prompt in `README_FOR_BUILDER.md`.
- Competitor comparison generation now also writes the three builder-prompt variants.
- Lead packages now include the builder prompt files.
- Lead Detail now has a `Generate AI website-builder prompts` action.
- Added regression tests for competitor-grounded prompts and the no-competitor fallback.
- Correctly scoped the existing Windows DPAPI regression test to Windows so non-Windows source testing does not report a false failure.

## Verification performed here

- `python -m compileall -q local_presence_miner tests`: passed.
- Builder/report targeted tests: 3 passed.
- Non-UI test suite: 32 passed, 1 skipped (Windows DPAPI), 0 failures.
- Full test collection could not run in this environment because PySide6 is not installed; three existing UI-importing test modules therefore cannot be collected here.
- Ruff is not installed in this environment, so Codex/Windows should run Ruff before producing the release EXE.

## Recommended Windows handoff

Have Codex run the full PySide6 test suite, Ruff, launch the UI, verify the new Lead Detail button, generate a real/demo competitor comparison, inspect the three prompt files, then build the normal PyInstaller release.
