# Final L01 progress-correction acceptance — FAIL

## A. Verdict

**FAIL — one P1 remains on the representative-content sufficiency boundary.** The former failures are closed, but ordinary loading/status text with common punctuation or a different wait sentence still produces paid website/SEO recommendations. This is not accepted as the first-customer commercial baseline. Production edits: **zero**. No correction was executed.

## B. Exact source identity

The user explicitly selected the corrected **Progress_Correction** archive, superseding the older Final_Correction filename/hash in the acceptance attachment. See `SCOPE.md`; the behavioral acceptance contract is unchanged.

- Input: `MarketLens_L01_Progress_Correction_Independent_Review_Bundle_20261006.zip`.
- ZIP SHA-256: `d1f24e4948ef3f1129f97cbbac39276ba7dda45011c8311847f2a16bcce25f0e`.
- Candidate: **272 files**, `2a244cf6de8fafaad58e56e59ba8bfb5843f1e70294fc8e8d91ab74ef6f9fbee`.
- Reconstructed parent: **272 files**, `4ab4420bd07ba9ca57472578fb12549eee10a83aae47cbc36a2381576a321ae9`.
- Parent delta: **4 modified / 0 added / 0 deleted**: `docs/seo-intelligence.md`, `local_presence_miner/domain/intervention_assessment.py`, `local_presence_miner/domain/website_evidence.py`, `tests/test_a02_a03_page_eligibility.py`.
- Current response interpretation **6**; assessment semantics **10**.
- Independently verified all 400 unique safe ZIP members, CRC, exact file hashes, candidate tree, counterpart reconstruction and unchanged input before/after each run. `FINAL_SOURCE_IDENTITY.json` confirms no source changes.
- Tree hashing uses SHA-256 of UTF-8 canonical JSON mapping relative paths to byte length and SHA-256, sorted keys, compact separators, `ensure_ascii=False`; see `audit.py`.

## C. Unchanged 13-case probe

**13 passed** in 31.97s. Supplied assertions were not edited. `checks/boundary13.*` and `observations/boundary13/` are freshly generated evidence, separate from historical `input/` receipts.

## D. Four formerly failing cases

All **PASS**, including SQLite commit/reopen:

| Prior reproduction | Current result |
|---|---|
| Fetched brand-only | Uncertain; no scope/price, proposal rejects $350, no Call Guide ask or $350 draft |
| Fetched Welcome + loading | Same conservative result |
| Imported loading + descriptive static metadata | Same conservative result |
| Imported Welcome + loading | Same conservative result |

Exact before/after summary: `FOUR_PRIOR_CASES.json`. The preceding progress failure, `Loading... 75% complete. Please wait while the site loads.`, is also closed in the separately rerun **6/6 supplied progress cases**.

## E. Unchanged 69-case replay

**69 passed** in 81.59s. The supplied replay was executed unchanged, including its existing version-10 assessment prerequisite. Its original 55, six composition/positive cases and eight history/version/hours controls pass. No historical expectation or assertion was relaxed in this audit.

## F. Six fresh boundary cases

Exactly six new cases were run, only after both required replays passed: **5 failed / 1 passed**, 22.46s. All use synthetic HTTP-200 fixtures, actual extraction, actual commercial consumers and SQLite reopen. No invented word counts or classifier monkeypatches were used.

Common HTML: title `Synthetic Plumbing`; descriptive static meta description; Service JSON-LD; `<button>Book our repair service</button>`; no descriptive body beyond the text below. Fetched cases A–E have `<h1>Synthetic Plumbing</h1>`.

| Case | Actual visible paragraph / imported H1 | Result after reopen |
|---|---|---|
| A | Paragraph `Loading (75%)` | FAIL: normal capture; $350 CTA/contact scope |
| B | Paragraph `Loading [3/10]` | FAIL: normal capture; $350 CTA/contact scope |
| C | Paragraph `Loading — 75% complete` | FAIL: normal capture; $350 CTA/contact scope |
| D | Paragraph `Please wait while we prepare your page` | FAIL: normal capture; $350 CTA/contact scope |
| E | Paragraph `We repair leaks. Call 555-0100.` | PASS: legitimate short prose; bounded CTA/contact scope survives |
| F | H1 `Loading (75%)`; empty paragraph; import actual extracted facts | FAIL: fetched uncertain, imported normal; $350 narrow SEO scope |

Full HTML, facts, recorded proof, assessments, proposal text, Call Guide, drafts, delivery results, and before/after observations are in `fresh-observations/`. `FRESH_SUMMARY.json` is a compact machine-readable comparison. All five negatives have the same commercial failure mechanism; they are **one P1**, not five independent findings.

## G. Fetched-path verdict

**FAIL** for A–D. Branding and controls are excluded from captured body proof, but the remaining status-only text itself is misclassified as descriptive content. The proof texts are literally `loading (75%)`, `loading [3/10]`, `loading — 75% complete`, and `please wait while we prepare your page`. Structured facts are uncertain; the current-response exception incorrectly promotes them to ordinary observed website evidence.

## H. Imported-path verdict

**FAIL** for F. Actual extraction yields branded title, H1 `Loading (75%)`, `word_count=6`, Service schema and static description; fetched interpretation is uncertain. Import considers the status heading descriptive. The count exceeds heading-word count because of the button, so the consistency veto does not block it. No omitted business prose is supported. This becomes ordinary paid SEO after persistence/reopen.

## I. Current-response/versioning verdict

The version mechanism itself passes controls: old version-5 brand-only normal cannot certify current content; a version-6 normal label/reason without sufficient proof cannot self-certify; version-9 commercial approval becomes stale under assessment 10 while human wording survives. Historical bytes, timestamps and source references are retained in the replay; all six fresh cases preserve raw records through reopen.

However, the current proof validator reuses the permissive predicate and accepts the actual status-only `content_proof.text` in A–D. This is a semantic proof-validation failure, not merely trusting a `normal` label and not fabricated evidence. Older observations were not rewritten. No migration was introduced.

## J. Actual commercial consumers

For **all five failed cases**, both before and after database reopen:

- Price is available; recommended price **$350**.
- A–D scope: `mobile call/quote button`, `homepage CTA rewrite`.
- F scope: `local SEO title/meta/H1 fixes`.
- Proposal generation accepts explicitly selected $350 and writes a proposal.
- Call Guide recommended ask is **350**.
- Generated outreach drafts contain **$350**.
- Delivery/payment readiness stays **false**. That gate does not repair the unsupported commercial recommendation.

Nothing was sent. Fixture files/databases stayed in isolated runtime directories, not application user data.

## K. Positive controls

Pass: real concise service prose; loading-dock/moving, pool-maintenance and account-management prose; descriptive imported heading with consistent facts; legitimate narrow SEO; independently supported listing-hours correction; healthy-business no-sale. These are covered by the freshly rerun 13/69/prior-six suites, plus eight targeted proof/version controls and fresh case E. A global loading/maintenance keyword ban is not acceptable.

## L. A01 smoke

The supplied replay passes the unclear `SEO maintenance` provider-responsibility validate-first case and the unrelated `accounting / payroll` positive control. No broader A01 re-audit was performed.

## M. Finding and exact semantic seam

**P1 — unrecognized status composition is treated as affirmative descriptive content.**

In `input/source/local_presence_miner/domain/website_evidence.py`:

- Lines 54–56: `_STATUS_PREFIX` requires restricted separators after the status clause. Parenthesis, bracket, whitespace followed by an em dash, and the unrecognized `while we prepare your page` continuation miss this grammar.
- Lines 78–81: `_descriptive_text` returns true for alphabetic text that is not a recognized shell/incidental label whenever `_STATUS_PREFIX` does not match. Absence of a known status match is therefore still positive evidence.
- Line 176 onward: `classify_response` uses that predicate to label the status body normal and save it as visible-body proof.
- Lines 84–104: `current_response_proves_content` reuses the same predicate, accepting this bad proof against uncertain lossy facts.
- Lines 234–241: `classify_page_facts` uses it to accept the imported status H1; count is a veto but cannot rescue the misclassified heading.

Expected: A–D and F stay uncertain/recapture-required; unsupported website/SEO scope, price, proposal, Call Guide ask and priced drafts are withheld through reopen. Keep raw evidence and human text. Do not reject real short business prose or independently supported opportunities.

No P0 reproduced. No extra P2/P3 product findings were sought or added. `CORRECTION_HANDOFF.md` is the single bounded follow-up, written only, not executed.

## N. Supplied receipts inspected, not rerun

Final-candidate receipts report **452 affected tests passed**, Ruff clean, compileall exit 0, mypy **91 parent / 91 candidate**. Independently reparsed both mypy logs: path/message/code/multiplicity multisets are identical after normalizing path separators and line/column numbers; zero new or removed errors. These are supplied verification, not new executions in this audit. Intermediate stage receipts remain labeled historical. See `SUPPLIED_RECEIPTS_REVIEW.json`.

## O. Independent executions

| Run | Result |
|---|---|
| Unchanged prior boundary | 13 passed |
| Unchanged supplied replay | 69 passed |
| Supplied prior progress cases | 6 passed |
| Targeted old-proof/current-proof/positive/count controls | 8 passed |
| New six-case status-composition probe | 5 failed, 1 passed |

These counts overlap; no unique-test grand total is claimed. Full pytest and static tools were not unnecessarily rerun. Tests ran with existing Windows Python 3.11/PySide6 environment, offscreen configuration, verified source-module origin and bytecode/cache suppression. No Windows release build or GUI acceptance is claimed. The 49 collected observation files are outputs, not test-count totals; copied historical observations are excluded using each run's start timestamp.

## P. Limitations and stop

This is a bounded synthetic acceptance of L01, not live-business research, ranking/revenue validation, platform-wide shell detection, or a broad audit. Source provenance and green supplied regressions do not override the reproduced P1. No baseline freeze or audit-loop closure is declared. No implementation, Windows packaging, outreach sending, AI, or subsequent feature work was performed. Stop after delivering this report/bundle and correction handoff.

## Q. Usage accounting

**Actual used readings: 4/75 → 50/83 (five-hour/weekly); +46/+8 percentage points.** Start: 2026-10-06 23:47:09 UTC. Final closeout: 2026-10-07 00:01:01 UTC (October 6, 6:01:01 PM MDT), immediately before ZIP assembly. Final remaining: **50% five-hour / 17% weekly**. The five-hour and weekly reset timestamps did not change during this audit. This started in a new five-hour window relative to the preceding correction; its historical 80/75 endpoint is not subtracted. All readings are account-wide, not task-exclusive. Zero reset credits redeemed; two available. Full receipts: `USAGE_CLOSEOUT.md`, `STARTING_USAGE.json`, `FINAL_USAGE.json`.
