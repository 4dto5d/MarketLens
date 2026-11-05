from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceTier:
    name: str
    price_range: str
    best_for: str
    deliverables: list[str]
    upsells: list[str]


SERVICE_TIERS: list[ServiceTier] = [
    ServiceTier(
        name="Presence Audit",
        price_range="$0-$150",
        best_for="First contact, no-trust-record outreach, or qualifying a prospect.",
        deliverables=[
            "public website/profile audit",
            "competitor snapshot",
            "top 5 fixes",
            "recommended first offer",
        ],
        upsells=["proposal", "mockup", "starter site"],
    ),
    ServiceTier(
        name="Owner-Ready Proposal + Mockup",
        price_range="$150-$450",
        best_for="Warm leads that want to see the plan before committing.",
        deliverables=[
            "owner-facing proposal",
            "one-page visual concept",
            "competitor gap summary",
            "scope and timeline",
        ],
        upsells=["static website build", "Google cleanup", "review request system"],
    ),
    ServiceTier(
        name="Static Local Website",
        price_range="$750-$1,800",
        best_for="No website, ugly website, or weak mobile/contact flow.",
        deliverables=[
            "polished static website export",
            "mobile sticky call/quote CTAs",
            "service sections",
            "quote form markup",
            "FAQ/process/proof sections",
            "basic LocalBusiness schema",
        ],
        upsells=["form backend", "hosting setup", "copy/photo cleanup", "monthly maintenance"],
    ),
    ServiceTier(
        name="Conversion Site + Google Cleanup",
        price_range="$1,200-$2,800",
        best_for="Businesses with some proof but poor conversion and weak Google-facing details.",
        deliverables=[
            "static or builder-hosted website",
            "Google profile cleanup checklist",
            "review display section",
            "service-area copy",
            "contact/quote flow",
            "analytics handoff checklist",
        ],
        upsells=["AI chat widget", "CRM pipeline", "review request system", "service pages"],
    ),
    ServiceTier(
        name="Local Authority Site",
        price_range="$2,500-$6,500+",
        best_for="Higher-ticket local services where multiple service pages and proof can pay off.",
        deliverables=[
            "homepage",
            "3-10 service pages",
            "FAQ and service-area pages",
            "proof/gallery layout",
            "schema plan",
            "conversion copy",
        ],
        upsells=["blog/content plan", "AI chat", "monthly reporting", "GBP posting workflow"],
    ),
    ServiceTier(
        name="Review Request System",
        price_range="$300-$900",
        best_for="Real businesses with low review count and owner/staff willingness to ask customers.",
        deliverables=[
            "owner/staff request scripts",
            "QR card copy",
            "post-job text/email templates",
            "review reply templates",
            "website review proof section",
        ],
        upsells=["monthly reputation workflow", "site proof updates", "CRM follow-up reminders"],
    ),
    ServiceTier(
        name="Human-Managed Chat Bubble",
        price_range="$250-$900 setup + $100-$500/mo",
        best_for="Businesses that want a chat button but do not need true AI automation.",
        deliverables=[
            "chat bubble UI",
            "question capture form",
            "routing to email/CRM/chat provider",
            "FAQ starter prompts",
            "response expectations copy",
        ],
        upsells=["real AI assistant", "after-hours routing", "lead qualification form"],
    ),
    ServiceTier(
        name="AI Answer Bubble",
        price_range="$750-$2,500 setup + API/platform costs + $150-$750/mo",
        best_for="Businesses with repeat questions, enough traffic, and budget for maintenance.",
        deliverables=[
            "AI chat provider selection",
            "approved FAQ/source document setup",
            "handoff rules",
            "lead capture fields",
            "prompt/system guardrails",
            "monthly review and tuning",
        ],
        upsells=["CRM integration", "booking integration", "call tracking", "knowledge base updates"],
    ),
]


def pricing_table_text() -> str:
    lines: list[str] = []
    for tier in SERVICE_TIERS:
        lines.append(f"{tier.name}: {tier.price_range}")
        lines.append(f"Best for: {tier.best_for}")
        lines.append("Includes: " + "; ".join(tier.deliverables))
        lines.append("Upsells: " + "; ".join(tier.upsells))
        lines.append("")
    return "\n".join(lines).strip()
