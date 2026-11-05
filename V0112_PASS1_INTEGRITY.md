# v0.1.12 Pass 1 integrity model

## Approval lifecycle

A generated or manually revalidated draft stores the exact subject/body hash, an ordered dependency-set hash, each supporting proof ID and proof fingerprint, the proof snapshot, permitted usage types, and a claim/evidence hash. Approval stores those values again in an approval snapshot. A material proof change or deletion preserves the old subject/body and snapshot in `outreach_approval_history`, revokes approval, records the reason and time, and moves an Approved-to-Contact lead to Needs Review.

Missing legacy dependency metadata means **unknown**, not “no dependencies.” On the first v0.1.12 migration, every historical approved draft whose dependency state is unknown is conservatively revoked and recorded in history. Its exact text is not rewritten. New dependency records are created only by deterministic generation or explicit operator review; replacement proof is never selected automatically.

## Permission model

Existence, verification, internal reasoning, client-name disclosure, URL disclosure, testimonial disclosure, case-study/before-after disclosure, and reference permission are separate facts. All external permissions default false. `internal_only` overrides every sharing permission. Permission also requires the relevant evidence: URL sharing requires a verified URL; testimonial sharing requires verified testimonial evidence; case-study sharing requires verified case-study/before-after evidence; reference sharing requires verified client work; naming requires a verified recorded client name.

Project and proof-artifact identity are not modeled in Pass 1. The completed-project count may therefore still count several permitted proof artifacts from one real project separately. That known claim-integrity issue is explicitly deferred under the later execution guardrails.

## Canonical approval paths

Only `database.repositories.set_outreach_approval` grants draft approval. `save_outreach_draft(..., approved=True)`, the Lead Detail approval action, and the Outreach approval action route through it. Direct lead-status updates cannot grant Approved to Contact. The Outreach clipboard action and `OutreachBatchService` independently re-run `outreach_approval_errors` at use/export time, so a stale raw approval flag is not contact-ready.

The validator checks suppression/DNC, lead and claim verification, exact sender/compliance values, placeholders, exact-body fingerprint, dependency document/hash, live proof fingerprint, and every required disclosure permission.

## Public network boundary

`safe_request` validates scheme, URL syntax, credentials, hostname, every resolved address, every redirect location, and the redirect limit before sending a hop. `PinnedPublicTransport` revalidates its token, connects to the validated numeric IP without proxies or a second DNS lookup, sends the original Host header, preserves TLS certificate/hostname verification, and disables automatic redirects/retries.

Website Audit and Contact Discovery, including same-origin stylesheets and HEAD checks, use this boundary. PageSpeed validates the prospect URL before delegating it and does not follow unexpected Google endpoint redirects. Places calls use fixed HTTPS Google endpoints and do not follow redirects. Rendered browser fetching is skipped because the browser's subresource and DNS behavior is not fully guarded. Remote-URL UI actions copy rather than navigate.

## Migration and rollback boundary

Before adding v0.1.12 fields, startup creates `local_presence_miner.sqlite3.backup-before-v0112` once when an older Seller Proof/outreach schema is present. SQLite's backup API captures committed WAL data, and the destination is created through a temporary file then renamed without replacing an existing backup. Reopening is idempotent. Operational rollback is: close v0.1.12, retain the failed/current database separately, restore a copy of the pre-v0.1.12 backup, and reopen it with the untouched v0.1.11 release artifact.
