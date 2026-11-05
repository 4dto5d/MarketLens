"""Current commercial review overlay; never a Qualification/contact authority."""
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import Lead
from local_presence_miner.domain.intervention_assessment import assess_interventions
from local_presence_miner.services.conversation_state_service import ConversationStateService
from local_presence_miner.services.intervention_evidence_service import collect_intervention_evidence


def commercial_triage_overlay(session: Session, lead: Lead) -> dict:
    conversation = ConversationStateService().build(session, lead)
    assessment = assess_interventions(collect_intervention_evidence(session, lead, conversation=conversation))
    labels = {"recommended": "Review scoped opportunity", "no_sale": "No paid recommendation",
              "validate_first": "Owner / technical validation", "insufficient_evidence": "Research only"}
    return {"state": assessment.state, "label": labels[assessment.state], "reason": assessment.summary,
            "next_step": assessment.owner_validation_question or assessment.summary,
            "contact_authorization": False,
            "limitation": "Commercial triage does not override Qualification, contact route, suppression or consent."}
