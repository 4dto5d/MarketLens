# Durable prospect findings — Pass 1

Open a business's **Audit Evidence → Source-linked findings**. Capture one contact-path check, record an attributed owner need, or record a manual ChatGPT/Claude response even when no website audit exists. Select a row to review/correct it or inspect its original sources and full history. New records start UNREVIEWED. A review requires your name and a reason; VERIFIED also requires acknowledgement that you checked the recorded source, date, attribution and exact wording.

VERIFIED means correspondence to the recorded source. It does not mean the business has a proven commercial problem, the owner agreed, a form failed a functional test, or contacting the owner is allowed. Review, assertion type, source validity and freshness are separate fields. Manual owner needs remain operator-attributed VERBATIM or PARAPHRASED statements or operator hypotheses. An optional original timestamp requires its original timezone offset; leave it unknown if unavailable. New v2 source envelopes retain the entered timestamp and offset alongside normalized time. Legacy v1 captures lack original timezone provenance: their historical UTC rendering is preserved but qualified as unverified UTC, with UNKNOWN freshness. Reviewing source cannot authenticate an unrecorded timezone. A correction appends a v2 revision; the editor leaves legacy time blank until an original offset is actually supplied. Manual needs do not create canonical conversation assertions, accepted scope or automatically priced work.

## Exact commercial boundary

The website adapter supports only these existing passive checks:

| Fact ID | Meaning of the recorded check |
| --- | --- |
| `website.check.tap_to_call` | Tap-to-call link detected in the sample |
| `website.check.contact_form` | Contact/quote form detected |
| `website.check.sitewide_contact_path` | Contact route detected across sampled pages |
| `website.check.viewport` | Mobile viewport metadata detected |
| `website.check.clear_primary_cta` | Primary CTA detected |

An absent detection is not proof of broken functionality or lost customers. Possible consequences and questions for the owner are stored separately. Once a fact is registered for durable review, an UNREVIEWED, UNKNOWN, DISPUTED, corrupt, stale, future-dated, wrong-website or superseded-source finding cannot support that fact in current commercial projections. An eligible VERIFIED finding permits the original bounded observation; it grants no extra commercial authority. Unregistered facts retain their existing rules.

`reviewed_contact_audit` removes only the held check and its exact generated label from the current view. Independent website checks, listing-hours evidence, SEO evidence, and rendered observations keep their own rules. It never rewrites raw captures or human notes. The intervention and sales-evidence adapters feed existing Proposal, Call Guide and outreach flows. Existing commercial dependency checks revoke affected approvals while retaining historical human text and acted-on offer identity. A review that does not change consumed commercial inputs need not stale unrelated work. UTC-normalized website timestamps keep source identity stable across SQLite reloads; older differing fingerprints conservatively require fresh review.

## Storage, corrections and ownership

`prospect_finding_revisions` is an additive append-only ledger. Each row includes business identity, stable finding key, revision/previous-row reference, assertion kind, exact claim, separate inference/question, immutable source JSON and SHA-256, review state, actor, reason and recording time. Website snapshots retain the original checks, eligibility evidence, source URL, audit ID and observation time, rather than relying on a mutable audit row alone. Manual snapshots preserve original entered wording and source attribution.

Corrections append a new revision with expected-head concurrency checks. Database uniqueness and SQLite triggers prevent forks, replacement, mutation, deletion, cross-business sources and source reparenting, including on legacy connections with foreign-key enforcement disabled. A real SQLite transaction wraps savepoints so a caller rollback or failed commercial refresh cannot commit half a review. Callers still own commit/rollback.

Rescanning updates the existing audit without changing historical finding bytes. The current-source hash then differs, and the old review cannot silently certify the new capture. Explicitly choose **Use the current scan as a new source revision**, inspect it and record a new review. A preview hash detects another scan arriving before save. Corrupt latest revisions remain visible and fail closed; prior verification is never revived automatically.

Guided Opportunity worksheets can link `finding_revision:<id>:<sha256>` references. Links pin exact revisions and require valid same-business ownership. Later corrections do not move a historical worksheet link. Existing worksheets remain readable; missing/corrupt links are shown as needing review and cannot be silently resaved as valid evidence. Linking a finding is context, not scope acceptance or approval.

For an existing database, initialization creates a validated SQLite backup named `.backup-before-prospect-findings` before adding the table and guards. Upgrading an existing Pass 1 ledger creates `.backup-before-finding-disclosure-v2` before adding the disclosure-version column with legacy default 0. No source/review rows are rewritten. Reinitialization is idempotent, preserves backups and creates no inferred legacy findings. Businesses/audits referenced by finding history cannot be deleted or reparented. No destructive migration is needed. Backups contain private operator data and should stay local.

## Provider-neutral extension contract

Source envelopes use `schema_version`, `source_kind`, `subject`, `observed_at` and structured `payload`. The table and envelope do not require a Google ID, crawler or search-engine URL. Future source kinds need an explicit validating adapter and commercial eligibility policy; unsupported kinds are preserved but fail closed today.

The enabled manual AI-discoverability adapter retains provider/model/version (UNKNOWN is allowed), exact prompt and response, original timestamp with timezone or UNKNOWN, test/location/account context, separate browsing availability/use, manually annotated mentions/omissions/competitors, citations/references, related-test group, variability notes and operator-noted inaccuracies. Each row is one captured response; there is no automatic test runner, aggregation, visibility score or external query. Model statements and noted inaccuracies are not authenticated business facts. Literal names/recorded aliases and conflicting annotations are validated conservatively; ambiguous cases stay UNCLEAR. Original response whitespace is preserved. Trading aliases are operator annotations, not automatically verified identity facts.

## Manual AI observations in proposals

Recording or verifying an AI capture never changes prospect rank, Qualification, Smart Offer, pricing or accepted scope. It can be linked to Guided Opportunity using the same revision references as other findings. A healthy business with only a manual omission remains without a justified paid recommendation.

An AI review has a separate **Approve the complete external-disclosure preview for proposal selection** checkbox. VERIFIED/source-check acknowledgement alone does not grant customer-facing use. This approval is immutable revision metadata, not owner approval or outreach permission. Every new revision defaults to unapproved. The preview contains all dynamic information permitted in the proposal: the single-response observation, recorded test time/model/version and limitations. Exact prompts, full responses, test context, citations and internal references remain internal and are never automatically disclosed. Approval contract version 2 binds this preview/output contract; historical approvals remain recorded at legacy version 0 but are withheld until an explicit new review approves the complete disclosure. The statement never claims overall AI invisibility or predicts demand, revenue or ranking gains.

`approved_ai_observations` selects only current heads with valid source hashes, unchanged business identity, a known nonfuture test date within 30 days, current VERIFIED version-2 disclosure approval and a clear mention annotation. UNKNOWN, DISPUTED, stale, future, corrupt, superseded and identity-mismatched records are precisely withheld. Approval makes an observation available for selection: **every proposal defaults to none**. The existing customer-proposal action offers unchecked eligible observations and their complete approved external preview. The service takes explicit revision references and checks current eligibility again before generation; a raced dispute/correction raises an error instead of substituting evidence. Bulk drafts and internal pricing proposals also default to none. Excluded observations and approvals remain intact.

Proposal HTML and its sidecar contain only the selected public disclosure whitelist and revision references/version, never the raw AI source. AI observations stay outside commercial-plan and outreach-copy inputs and create no paid scope. HTML/XML template environments explicitly recognize `.html.j2`/`.xml.j2`: dynamic text is escaped while template-owned headings, tables and formatting remain HTML. This corrects a pre-existing escaping weakness in the customer HTML renderers; plain-text templates retain their existing behavior.

Previously generated proposal files remain historical artifacts; files already printed/shared cannot be recalled. Older Pass 1 artifacts may contain prompt/context disclosure, so generate a fresh proposal through the corrected workflow before sharing. Capture/review is not authenticated provider execution. Search, citations, geography and aliases remain internal recorded observations/annotations, not verified methodology or ZIP-level visibility results.

## Deliberate limits

Only contact-path, manual owner-need and manual AI-response adapters are enabled. Legacy per-index audit annotations remain historical UI context and cannot override the durable review gate. There is no general fact extractor, research-source importer, economics automation, new canonical offer, Qualification/contactability change, outreach sending or Windows packaging. Historical free text is preserved; the app cannot retroactively remove unsupported prose an operator has manually authored. Existing approval and copy/export freshness guards remain the outreach use boundary. Automated model querying, APIs, bulk prompt testing, integrated LLM reasoning and an AI dashboard remain deferred.
