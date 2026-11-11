# Response-version correction — November 11, 2026

Implemented for independent review. Source is frozen as 314 files, SHA-256 c4f92cb7f893cb764d07c22949de95f8bb48798bb57c67bf1fe25747d6dbd9a3. Parent is the 313-file candidate 94cae46553dcddc619a255b4b8c46f857612ab562f4a926157f5164b8724c1bd. Exact delta is 3 modified and 1 added, with no deletions. The isolated branch codex/response-version-correction-20261111 has an unborn HEAD. Manifests and the exact patch preserve the checkpoint. No SQL migration.

## Behavior and source changes

- domain/opportunity_intelligence.py requires schema 2 for current and unrecognized policies. Only known historical policies v1/v2/v3 use the schema-1 compatibility path. The version check precedes interpretation.
- services/opportunity_intelligence_service.py validates cached output before reuse. An invalid retained receipt is skipped when an operator explicitly authorizes a fresh execution. It stays immutable. Each execution still sends at most one inference request.
- tests/test_decision_brief_contract.py supplies a historical originating policy to its historical-response fixture, preserving the original historical-readability assertions.
- tests/test_intelligence_response_versions.py covers new mismatched completions, existing stored mismatches, cache reuse, raw receipt retention, history, adoption, valid v2 output, three known historical policies and an unknown policy.

## Before and after

Before the fix, three of the six new tests failed. A schema-1 response to a v4 request completed successfully, retained current eligibility and cache reuse. After the fix, the mismatched response raises a version error, keeps its raw text in a failed terminal receipt, yields no current advice, and cannot be adopted. A preexisting completed mismatch stays in the append-only ledger but is marked ineligible on read. An explicitly requested fresh v2 result can complete and be reused. Genuine schema-1 historical packets remain inspectable and noncurrent.

## Fresh verification

The affected 13-module suite passed 161 tests in 119.19 seconds on Windows with offscreen Qt, including the six new regression tests. The new tests first reproduced 3 failures and 3 passes on parent production behavior, then passed all 6 after the fix. Ruff and compileall passed. Fresh mypy reported 91 historical diagnostics in 22 files, with zero new diagnostics against the supplied verified-parent receipt. Complete commands and outputs accompany the source.

The full regression suite was not repeated in this narrow pass. Its 1,466-test parent receipt belongs to the prior candidate. Existing synthetic consumer isolation and UI workflow tests were rerun in the affected suite. There was no manual native Windows acceptance, live inference, release, merge or publication.

## Limits and next step

This change closes the reproduced response-version path. Natural-language grounding and model quality remain subject to independent review. No current live-model intelligence quality has been measured. Perform the included read-only acceptance replay against the exact frozen bytes, then decide whether to authorize one synthetic live-model evaluation with explicit per-send consent.

Usage percentages were unavailable from an authenticated meter. No usage readings are inferred.
