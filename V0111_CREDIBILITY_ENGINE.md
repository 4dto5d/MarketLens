# Local Presence Miner v0.1.11 — Credibility Engine

This release expands the integrity-hardened v0.1.11 Adaptive Sales Copilot. It does not add Listener Mode, live transcription, automated sending/calling, or outcome learning.

## Product boundary

- Intelligence level: Extra High deterministic decision support.
- Ultra remains reserved for v0.2.x Listener Mode and outcome learning.
- Every credibility claim is derived from operator-entered Seller Profile/Proof data or the app's bounded public-evidence workflow.
- Missing seller evidence stays missing. It is not replaced with an agency persona, local office, client history, reference, testimonial, measurable result, or experience duration.

## Added

- Structured proof statuses: Completed, Completed + Verified, Completed + Testimonial, Completed + Measurable Result, In Progress, Prototype, Concept Only, and Unclassified.
- Explicit client-work, software/AI-project, testimonial, measurable-result, before/after, provenance, safe-claim, and prohibited-claim fields.
- Seller identity type, location model, location label, and service area.
- Same-niche/similar/general/technical/developmental proof ranking.
- Compact WHY YOU card and Do Not Claim guidance in Guided Call.
- First-90-second skeptical call branches for identity, company, location, source, selection reason, experience, proof, references, legitimacy, access/payment, differentiation, and AI concerns.
- Five likely early paths by default, plus Search all, Other, I don't know what they mean, and credibility rescue.
- Structured credibility conversation signals stored on real Live Call interactions.
- Proof-aware emails, report delivery, proposals, and reports.
- Send / Optional / Do Not Send proof attachment recommendations.
- Automatic regeneration of dynamic call guidance and unapproved drafts after proof changes.
- A dedicated `.backup-before-v0111-credibility` schema safeguard.

## Preserved integrity behavior

- Guided Call startup is neutral.
- Practice cannot write interactions or suppression and cannot leak into Live.
- Back restores the full prior state snapshot.
- DNC/suppression remains absolute and exact/typed.
- Canonical Smart Offer and Seller Pricing Intelligence remain authoritative.
- Approved outbound stays immutable during automatic proof regeneration.
- Competitor wording still requires manual Competitors Reviewed verification.
- Evidence changes still invalidate dependent verification/approval.
- Google stale-data, last-known-good preservation, radius limits, backfill, and per-lead durable commits remain intact.

## Manual operator work

Before using credibility wording, the operator must:

1. Configure a truthful identity and location/service model.
2. Review every legacy Unclassified proof record.
3. Select the actual completion state.
4. Mark client work only when a real client relationship existed.
5. Add provenance and narrow Safe claims.
6. Add explicit Do Not Claim boundaries.
7. Verify artifacts, ownership, attribution, and permission.
8. Review the generated response or email.
9. Send/call manually and record the actual outcome.
10. Honor opt-outs and DNC immediately.

Direct references require explicit permission outside the app. A testimonial does not automatically authorize sharing a person's contact information.

## Migration

An integrity-hardened v0.1.11 database receives a one-time sibling copy ending in `.backup-before-v0111-credibility` before proof/profile/conversation credibility columns are added. Legacy proof rows receive `Unclassified`; no historical proof is silently called completed.

## Verification boundary

Offline/deterministic verification covers the proof states, relevance ranking, call tree, conversation memory, email/proposal/report integration, approved-draft immutability, migration preservation, Practice/Back behavior, competitor verification, and DNC.

The real maximum-five-business Google Places Safe Live Test remains pending until Google Cloud billing can be activated. This release does not remove, weaken, replace, or represent that live gate as passed.
