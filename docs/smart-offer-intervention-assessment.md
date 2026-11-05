# Evidence-bound intervention assessment

## Decision contract

Smart Offer separates legacy prospect triage from the question of which bounded
intervention is supported by current evidence. `InterventionAssessment` version 1
is a deterministic, qualitative policy, not an expected-value model or a forecast.

Current, subject-matched website checks and rich Google observations enter through
`intervention_evidence_service`. Search Market findings retain the existing frozen
evidence, context-binding and freshness guards. Raw signal strings, candidate
position, competitor count and GrowthScore cannot independently authorize a sale.
Missing, stale, failed or malformed observations are not negative findings.

The four states are `recommended`, `validate_first`, `insufficient_evidence` and
`no_sale`. Only supported paid candidates have canonical Offer IDs and deliverable
scope. Validation alternatives deliberately do not. Each candidate records its
observations/references, problem hypothesis, why now, comparison with alternatives,
expected effect, success metric, falsifier, effort and unknowns. Fit and confidence
are categorical judgments; neither is a probability or a revenue projection.

## Ranking and boundaries

Operational/reputation diagnosis can suspend paid recommendations. Explicit
contact-route defects support a small conversion repair before a wider site build.
Current missing listing fields support a bounded listing-verification/cleanup
scope. Review workflow requires specific trust intent and compatible review facts.
A missing website, sampled search absence, technical flag or content gap alone
supports validation, not an automatic website or SEO sale. No-sale and capacity
constraints prevent new paid scope. Healthy complete observations can support
no-sale; incomplete observations instead produce insufficient evidence.

Search evidence does not measure search demand, organic rank, ranking difficulty,
competitor delivery strength, qualified inquiry conversion or ROI. It can add
bounded query/probe observations to an independently justified listing candidate,
without a numeric uplift. Categorical precedence is inspectable policy, not proof
that the chosen intervention maximizes the owner's economic return.

## Canonical offers, pricing and history

Unconfirmed offers may recompute from eligible evidence. Human-selected or
commercially acted-on canonical identity stays sticky; alternatives require human
acceptance. Approval of an unpriced research draft is not authority to quote an
old catalog hint. A retained human catalog quote is explicitly described as a
human choice, not the engine's highest-leverage recommendation. No-sale or
validation blocks new paid scope even when historical identity is retained.

`CurrentOfferContext` carries the assessment and exact selected scope. Its material
dependency identity excludes unrelated advisory details and cosmetic selection
labels. Consumed evidence still invalidates old plans and approval at existing
freshness boundaries. Registry semantic version is 3, so previous snapshots need
fresh evaluation; historical bodies, prices and used/spoken replies are retained.

The service-cost band is the canonical catalog band, not buyer value or ROI.
GrowthScore changes neither that band nor pricing-comparison selection nor adds
an opportunity premium. Seller proof/history can still calibrate the ask. The
band is not a measured delivery-cost estimate; access, effort and owner economics
must be validated before a real quote. Upper planning ranges promise no extra
deliverables beyond the verified scope.

Qualification locally retains its historical score-adjusted band as a triage
compatibility heuristic for the same lead and catalog ID. It is not a quote or
buyer-value measure. This prevents the changed quotation helper from silently
reclassifying contact priorities; that legacy heuristic needs a separate audit.

## Output and compatibility

Smart Offer, Guided Call, outreach, owner report and proposal consume the same
commercial plan. No paid recommendation means no invented scope or price; explicit
priced proposal export is rejected in that state. Legacy scoring and raw factors
remain available internally for triage compatibility but are not owner-facing
commercial proof. DNC, contact readiness, Qualification, approval and manual text
contracts are unchanged. There is no database migration or new canonical Offer ID.

Next work should independently audit this candidate before extending intelligence.
Authenticated analytics, owner economics, competitor-quality evidence and measured
intervention outcomes remain absent, not inferred. Do not promise Maps or web
ranking improvements from a Places result window or this assessment.
