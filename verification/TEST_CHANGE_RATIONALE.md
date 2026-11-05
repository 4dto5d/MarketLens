# Existing-test change rationale

No test was deleted, skipped, or marked xfail.

## v0.1.13 state/workflow change

| Existing test area | Former expectation | Why v0.1.13 changes it | New invariant |
|---|---|---|---|
| Later candidate failure | The workflow raised immediately after candidate two and only proved candidate one survived | v0.1.13 explicitly isolates candidate-local failures and must continue later candidates | The run returns normally as `Completed With Errors`; one membership is Failed, every later candidate is processed, and all successful leads are durable |
| Single-flight scope | The first v0.1.13 check used threads in one interpreter and therefore exercised only the Python global | The release promise covers separately launched MarketLens instances using one database | A real child process holds the database-backed renewable lease; a second process reports it active, cannot enter, and cannot reconcile the live row |
| Abrupt search-process death | No startup reconciliation existed for a durable `Running` row after its worker process vanished | Run History must not claim an active job forever | A real child process is terminated while its heartbeat lease is current; the persisted lease expires, startup derives `Interrupted / Partial` from saved memberships, and a separate parameterized test covers the no-success `Interrupted / Failed` case |
| Missing canonical candidate identity | The processing loop discarded the staged fallback membership key and raised `NoResultFound`, aborting later candidates | A malformed candidate is lead-local and must not kill the batch | Blank Place ID becomes a failed membership with a readable reason, no empty-ID Lead is created, and the later valid candidate succeeds |
| Existing v0.1.13 database | The correction adds the `search_run_leases` table | Existing v0.1.13 data needs a recoverable boundary before that additive schema change | An immutable pre-correction v0.1.13 fixture migrates with exact Lead/SearchRunLead preservation and a non-overwriting `.backup-before-v0113a` |
| Version/user-agent metadata | The corrected artifact still identified internally as the defective v0.1.13 build | The frozen correction must be distinguishable without relying on its ZIP filename | Application, CLI, window, package metadata, and dynamic User-Agent identify v0.1.13a; Windows fixed/string versions identify 0.1.13.1 |

All v0.1.12 integrity/security tests remain present. The renamed candidate-failure test reflects the required new semantics; it was not weakened, skipped, or deleted.

| Existing test area | Former fixture/expectation | Conflict with Pass 1 | New invariant |
|---|---|---|---|
| Contact Discovery tests | Replaced `session.get` and used reserved `.example` hosts | Bypassed the public-network policy and used intentionally non-public domains | A fake transport runs behind real URL/DNS validation using public fixture addresses |
| Positive outreach approval/export tests | Unsigned bodies, incomplete sender, and unknown proof dependencies could approve | Canonical approval must deny missing sender/compliance and unknown dependencies | Explicit synthetic sender, fully signed exact body, and explicit empty dependency set |
| Seller Proof pricing/credibility fixtures | Proof type or `verified` implicitly represented completed/shareable client work | New proof defaults deny classification and disclosure | Tests explicitly state completed/client-work status and only the permission needed by the assertion |
| Proof refresh preservation test | Any approved draft survived every Seller Proof change | Supporting evidence must revoke; unrelated proof must not | Renamed to assert an unrelated proof change preserves the exact valid approval; dependency deletion/downgrade tests cover revocation |
| Raw safe-claim/title assertions | Verified records could expose titles or safe claims without permission | Verification does not grant disclosure permission | Assert bounded permitted labels and assert private titles/claims are absent |
| Rendered audit availability | Missing Edge was the only unavailable condition | Browser subresources/DNS cannot be comprehensively guarded | Assert the explicit v0.1.12 security limitation and no launch/network behavior |
| Google API fixtures | Requests did not include redirect policy | Fixed endpoints must not automatically redirect | Fixtures accept and assert `allow_redirects=False` |
| Version/user agent tests | v0.1.11 and legacy product label | Release identity became v0.1.12 / MarketLens Local in Pass 1 | Assert the current release and the MarketLens Local user-facing name |

New tests added independently cover both positive and negative cases for every Pass 1 invariant. The stale-Google regression test initially failed and exposed a real compatibility defect: stale review/rating still affected Google Opportunity. Production code was minimally corrected, and the test remains.
