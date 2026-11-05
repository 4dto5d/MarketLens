from __future__ import annotations

from local_presence_miner.domain.competitor_matching import select_competitors
from local_presence_miner.domain.models import BusinessProfile, CompetitorMatch, WebsiteAudit
from local_presence_miner.domain.scoring import website_evidence_state, website_quality_score


class CompetitorService:
    def match_one(
        self,
        profile: BusinessProfile,
        profiles: list[BusinessProfile],
        audits: dict[str, WebsiteAudit],
    ) -> list[CompetitorMatch]:
        return select_competitors(profile, profiles, audits)

    def match_all(
        self,
        profiles: list[BusinessProfile],
        audits: dict[str, WebsiteAudit],
    ) -> dict[str, list[CompetitorMatch]]:
        return {profile.place_id: self.match_one(profile, profiles, audits) for profile in profiles}

    def average_website_score(
        self,
        competitors: list[CompetitorMatch],
        profiles: dict[str, BusinessProfile],
        audits: dict[str, WebsiteAudit],
    ) -> int:
        if not competitors:
            return 0
        scores = []
        for match in competitors:
            profile = profiles.get(match.place_id)
            if profile and (profile.google_details_retrieved or profile.website):
                audit = audits.get(match.place_id, WebsiteAudit())
                if not profile.website or website_evidence_state(audit) != "unknown":
                    scores.append(website_quality_score(audit, bool(profile.website)))
        return round(sum(scores) / len(scores)) if scores else 0
