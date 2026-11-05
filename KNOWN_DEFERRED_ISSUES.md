# Known deferred issues — after v0.1.13a State & Workflow Hardening Correction

Completion and final identity freeze of the v0.1.13a correction does not mean every independent audit finding is resolved.

Explicitly deferred to Pass 2 or later:

- Project versus proof-artifact grouping and distinct project/artifact counts. Several Seller Proof rows can still represent one underlying project; no historical rows were guessed or merged in Pass 1.
- Canonical Offer IDs and offer-name consistency.
- Shared niche/category semantics and taxonomy.
- Stale Seller Pricing scope and history propagation redesign.
- Remaining scoring, search, contact-intelligence, and call-richness findings assigned to later passes.
- Listener/transcript ingestion and outcome learning. No automatic sending, robocalling, SMS blasting, hidden-email harvesting, or unsupported enrichment was added.
- A guarded rendered-browser architecture that validates/pins every navigation, redirect, subresource, worker, and browser DNS destination. Until then, rendered network audit remains explicitly skipped.
- Offer IDs; shared niche taxonomy; dentist/residential semantics; Project-to-Proof Artifact grouping; stale Seller Pricing scope; and Offer History propagation.
- Dead search controls, maximum-results semantics, registrable-domain handling, stylesheet recall, and HEAD-to-GET behavior.
- AuditFinding/evidence fusion, PageSpeed/theme/review redesign, and related scoring changes.
- Guided Call tree expansion, stable call-tree IDs, search/phases, and additional variants.

Externally blocked:

- Real Google Places Safe Live Test, pending Google billing activation and the required refundable prepayment. Demo Mode and mocked API fixtures do not replace this live check.
