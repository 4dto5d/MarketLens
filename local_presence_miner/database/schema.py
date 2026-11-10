from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from local_presence_miner.time_utils import utc_now


class Base(DeclarativeBase):
    pass


class SEOResearchSnapshot(Base):
    """Immutable source checkpoint; derived advice is rebuilt, never historical truth.

    No rows are inferred from legacy Places observations or website booleans.
    Deleting a referenced lead is restricted rather than silently losing evidence.
    """

    __tablename__ = "seo_research_snapshots"
    __table_args__ = (Index("ix_seo_research_lead_id", "lead_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    binding_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_status: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_at: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


@event.listens_for(SEOResearchSnapshot, "before_update")
@event.listens_for(SEOResearchSnapshot, "before_delete")
def _immutable_seo_snapshot(_mapper, _connection, _target) -> None:
    raise ValueError("SEO evidence is immutable; append a new source checkpoint instead.")


class ProspectFindingRevision(Base):
    """Source-bound review history; source kinds are versioned adapter contracts."""

    __tablename__ = "prospect_finding_revisions"
    __table_args__ = (
        UniqueConstraint("lead_id", "finding_key", "revision", name="uq_finding_revision"),
        UniqueConstraint("previous_id", name="uq_finding_successor"),
        CheckConstraint("revision >= 1", name="ck_finding_revision_positive"),
        CheckConstraint("(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL)", name="ck_finding_chain"),
        CheckConstraint("finding_type != 'website_contact_path' OR (source_audit_id IS NOT NULL AND finding_key=fact_id)",
                        name="ck_website_finding_identity"),
        CheckConstraint("customer_copy_approved=0 OR (finding_type='ai_discoverability' AND review_state='VERIFIED' AND source_checked=1)",
                        name="ck_finding_copy_approval"),
        Index("ix_finding_lead_key", "lead_id", "finding_key", "revision"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False)
    finding_key: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_id: Mapped[int | None] = mapped_column(ForeignKey("prospect_finding_revisions.id", ondelete="RESTRICT"), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(80), nullable=False)
    fact_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    assertion_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_audit_id: Mapped[int | None] = mapped_column(ForeignKey("website_audits.id", ondelete="RESTRICT"), nullable=True)
    source_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    inference_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_state: Mapped[str] = mapped_column(String(24), nullable=False, default="UNREVIEWED")
    source_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_copy_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    customer_copy_contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


@event.listens_for(ProspectFindingRevision, "before_update")
@event.listens_for(ProspectFindingRevision, "before_delete")
def _immutable_finding_revision(_mapper, _connection, _target) -> None:
    raise ValueError("Finding history is append-only; record a new revision.")


class LeadSearch(Base):
    __tablename__ = "lead_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state_region: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    niche: Mapped[str] = mapped_column(String(120), nullable=False)
    criteria_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lifecycle_state: Mapped[str] = mapped_column(String(40), nullable=False, default="Pending", server_default="Pending")
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rediscovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_candidate: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    leads: Mapped[list[Lead]] = relationship(back_populates="search")
    memberships: Mapped[list[SearchRunLead]] = relationship(back_populates="search_run", cascade="all, delete-orphan")
    visibility_probes: Mapped[list[SearchVisibilityProbe]] = relationship(
        back_populates="search_run",
        cascade="all, delete-orphan",
    )


class SearchRunLease(Base):
    """Singleton, renewable cross-process ownership for Search Workflow."""

    __tablename__ = "search_run_leases"

    lock_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_pid: Mapped[int] = mapped_column(Integer, nullable=False)
    search_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquired_at_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    heartbeat_at_epoch: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at_epoch: Mapped[float] = mapped_column(Float, nullable=False)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("place_id", name="uq_leads_place_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("lead_searches.id"), nullable=True)
    place_id: Mapped[str] = mapped_column(String(180), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    google_maps_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    yelp_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    business_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    has_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_verification_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="New")
    priority: Mapped[str] = mapped_column(String(4), nullable=False, default="C")
    lead_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualification_class: Mapped[str] = mapped_column(String(40), nullable=False, default="Hold")
    qualification_confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="Low")
    qualification_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    recommended_offer: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    recommended_offer_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    offer_resolution_state: Mapped[str] = mapped_column(String(40), nullable=False, default="unmapped", server_default="unmapped")
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    niche_match_rule: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    approach_angle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_signals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    score_breakdown_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    operator_notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    system_notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    notes_provenance: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    next_follow_up_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    last_contacted_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    contact_method: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    contact_outcome: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    target_zip_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    target_radius_miles: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    past_sales_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    starting_offer_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    legacy_starting_offer_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_plan_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    commercial_output_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    commercial_plan_state: Mapped[str] = mapped_column(
        String(48), nullable=False, default="legacy_unknown_review_required", server_default="legacy_unknown_review_required"
    )
    commercial_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commercial_plan_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commercial_disposition: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    commercial_disposition_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    disposition_not_before: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    follow_up_permission: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    adaptive_assets_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    contact_discovery_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_started", server_default="not_started")
    contact_discovery_error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    contact_discovery_updated_at: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    business_status: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    primary_type: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    pure_service_area_business: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    google_public_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    google_retrieved_at: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    last_rich_google_retrieved_at: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    last_google_refresh_attempt_at: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    last_google_refresh_error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    google_rich_data_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    search: Mapped[LeadSearch | None] = relationship(back_populates="leads")
    search_memberships: Mapped[list[SearchRunLead]] = relationship(back_populates="lead")
    audit: Mapped[WebsiteAuditRecord | None] = relationship(back_populates="lead", uselist=False)
    drafts: Mapped[list[OutreachDraft]] = relationship(back_populates="lead")
    google_presence: Mapped[GooglePresenceAssessment | None] = relationship(back_populates="lead", uselist=False)


class SearchRunLead(Base):
    """Immutable run provenance plus lead-local processing state.

    ``lead_id`` is nullable so a malformed candidate can still be recorded even
    when it fails before a canonical Lead row can safely be created.
    """

    __tablename__ = "search_run_leads"
    __table_args__ = (
        UniqueConstraint("search_id", "candidate_place_id", name="uq_search_run_candidate_place"),
        UniqueConstraint("search_id", "lead_id", name="uq_search_run_lead"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("lead_searches.id"), nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    candidate_place_id: Mapped[str] = mapped_column(String(180), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    discovery_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    search_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    discovery_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", server_default="pending")
    processing_status: Mapped[str] = mapped_column(String(40), nullable=False, default="Pending", server_default="Pending")
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    search_run: Mapped[LeadSearch] = relationship(back_populates="memberships")
    lead: Mapped[Lead | None] = relationship(back_populates="search_memberships")


class SearchVisibilityProbe(Base):
    """One immutable acquisition attempt within a comparable query context."""

    __tablename__ = "search_visibility_probes"
    __table_args__ = (
        UniqueConstraint("search_id", "context_fingerprint", name="uq_visibility_probe_search_context"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("lead_searches.id"), nullable=False)
    market_query_id: Mapped[int | None] = mapped_column(ForeignKey("search_market_queries.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_niche: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    location_label: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    target_zip_code: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    resolved_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_result_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    collection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    raw_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retained_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    selected_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    comparability_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    attempt_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    acquisition_strategy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="legacy-v1", server_default="legacy-v1")
    center_resolution_provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    search_run: Mapped[LeadSearch] = relationship(back_populates="visibility_probes")
    market_query: Mapped[SearchMarketQuery | None] = relationship(back_populates="probes")
    observations: Mapped[list[SearchVisibilityObservation]] = relationship(
        back_populates="probe",
        cascade="all, delete-orphan",
        order_by="SearchVisibilityObservation.source_position",
    )


class SearchVisibilityObservation(Base):
    """One ordered Places response item; absence is derived only from complete probes."""

    __tablename__ = "search_visibility_observations"
    __table_args__ = (
        UniqueConstraint("probe_id", "source_position", name="uq_visibility_observation_position"),
        Index("ix_visibility_observation_place_time", "place_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    probe_id: Mapped[int] = mapped_column(ForeignKey("search_visibility_probes.id"), nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    search_run_lead_id: Mapped[int | None] = mapped_column(ForeignKey("search_run_leads.id"), nullable=True, unique=True)
    source_position: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_position: Mapped[int] = mapped_column(Integer, nullable=False)
    place_id: Mapped[str] = mapped_column(String(180), nullable=False, default="", server_default="")
    place_name: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    retained_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disposition: Mapped[str] = mapped_column(String(40), nullable=False)
    exclusion_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    probe: Mapped[SearchVisibilityProbe] = relationship(back_populates="observations")


class SearchMarketRun(Base):
    """Read-only market intelligence execution; its LeadSearch row only anchors probes and lease."""

    __tablename__ = "search_market_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("lead_searches.id"), nullable=False, unique=True)
    prospect_place_id: Mapped[str] = mapped_column(String(180), nullable=False)
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False)
    geography: Mapped[str] = mapped_column(String(240), nullable=False)
    query_universe_version: Mapped[str] = mapped_column(String(40), nullable=False)
    demo_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    lifecycle_state: Mapped[str] = mapped_column(String(40), nullable=False, default="Running", server_default="Running")
    error_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    queries: Mapped[list[SearchMarketQuery]] = relationship(
        back_populates="market_run", cascade="all, delete-orphan", order_by="SearchMarketQuery.ordinal"
    )


class SearchMarketQuery(Base):
    """Frozen, inspectable query-universe member; each retry remains a separate probe."""

    __tablename__ = "search_market_queries"
    __table_args__ = (
        UniqueConstraint("run_id", "query_id", name="uq_search_market_run_query"),
        Index("ix_search_market_query_run_ordinal", "run_id", "ordinal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_market_runs.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    query_id: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False)
    service_topic_id: Mapped[str] = mapped_column(String(120), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(160), nullable=False)
    cluster_name: Mapped[str] = mapped_column(String(160), nullable=False)
    geography: Mapped[str] = mapped_column(String(240), nullable=False)
    intent: Mapped[str] = mapped_column(String(80), nullable=False)
    provenance_rule: Mapped[str] = mapped_column(String(240), nullable=False)
    commercial_relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_version: Mapped[str] = mapped_column(String(40), nullable=False)

    market_run: Mapped[SearchMarketRun] = relationship(back_populates="queries")
    probes: Mapped[list[SearchVisibilityProbe]] = relationship(
        back_populates="market_query", order_by="SearchVisibilityProbe.id"
    )


class WebsiteAuditRecord(Base):
    __tablename__ = "website_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    meta_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checks_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    strengths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    weaknesses_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rendered_checks_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    pagespeed_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_run")
    rendered_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_run")
    desktop_screenshot: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    mobile_screenshot: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    lead: Mapped[Lead] = relationship(back_populates="audit")


class CompetitorRecord(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    competitor_place_id: Mapped[str] = mapped_column(String(180), nullable=False)
    competitor_name: Mapped[str] = mapped_column(String(240), nullable=False)
    website_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    evidence_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checklist_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    google_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")


class GooglePresenceAssessment(Base):
    __tablename__ = "google_presence_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, unique=True)
    google_presence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    opportunity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="Low", server_default="Low")
    observed_strengths_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    observed_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    unknowns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    competitor_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    recommended_action: Mapped[str] = mapped_column(String(120), nullable=False, default="Research-first", server_default="Research-first")
    top_issue: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    lead: Mapped[Lead] = relationship(back_populates="google_presence")


class ContactPoint(Base):
    __tablename__ = "contact_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, default="official_website")
    source_url: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="Moderate")
    verified_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proof_dependencies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    proof_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    dependency_state: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown", server_default="unknown")
    dependency_body_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    approval_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    commercial_output_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    commercial_dependency_state: Mapped[str] = mapped_column(
        String(48), nullable=False, default="legacy_unknown_review_required", server_default="legacy_unknown_review_required"
    )
    commercial_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    approval_revoked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    approval_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    lead: Mapped[Lead] = relationship(back_populates="drafts")


class OutreachApprovalHistory(Base):
    __tablename__ = "outreach_approval_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outreach_draft_id: Mapped[int | None] = mapped_column(ForeignKey("outreach_drafts.id"), nullable=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proof_dependencies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    proof_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    approval_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    commercial_output_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    revocation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SuppressionEntry(Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("value", name="uq_suppression_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(240), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class CommercialDispositionRecord(Base):
    """Append-only audit trail for explicit commercial disposition changes."""

    __tablename__ = "commercial_disposition_records"
    __table_args__ = (UniqueConstraint("lead_id", "revision", name="uq_commercial_disposition_lead_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_disposition: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    not_before: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    follow_up_permission: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source_interaction_id: Mapped[int | None] = mapped_column(ForeignKey("contact_interactions.id"), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    crm_status_before: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    crm_status_after: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ConversationAssertion(Base):
    """Append-only, correctable semantic assertion beneath contact history."""

    __tablename__ = "conversation_assertions"
    __table_args__ = (UniqueConstraint("assertion_uid", name="uq_conversation_assertions_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assertion_uid: Mapped[str] = mapped_column(String(36), nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    interaction_id: Mapped[int | None] = mapped_column(ForeignKey("contact_interactions.id"), nullable=True)
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False, default="null", server_default="null")
    assertion_state: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="OPERATOR_OBSERVATION", server_default="OPERATOR_OBSERVATION")
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source_text_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_RECORDED", server_default="NOT_RECORDED")
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    supersedes_assertion_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_assertions.id"), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    correction_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ContactInteraction(Base):
    __tablename__ = "contact_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semantic_capture_version: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    interaction_datetime: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False, default="Email")
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="Outbound")
    outcome: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    response_signals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    objection: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outreach_draft_id: Mapped[int | None] = mapped_column(ForeignKey("outreach_drafts.id"), nullable=True)
    follow_up_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    contact_name: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    contact_role: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    decision_maker_status: Mapped[str] = mapped_column(String(40), nullable=False, default="Unknown", server_default="Unknown")
    business_goal: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    capacity_status: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    buyer_questions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    commitments_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    branch_path_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    guided_call_identity_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    guided_call_sequence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    credibility_concern: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    wants_examples: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    wants_references: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    concerned_about_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    wants_proof: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    seller_experience_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    local_presence_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    decision_maker_skeptical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    legitimacy_concern: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    commercial_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    linked_outreach_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SellerProfile(Base):
    __tablename__ = "seller_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    business_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    experience_start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    identity_type: Mapped[str] = mapped_column(String(60), nullable=False, default="Individual / Freelancer", server_default="Individual / Freelancer")
    location_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="Not configured", server_default="Not configured")
    location_label: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    service_area: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SellerProject(Base):
    __tablename__ = "seller_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_profile_id: Mapped[int] = mapped_column(ForeignKey("seller_profiles.id"), nullable=False)
    project_type: Mapped[str] = mapped_column(String(80), nullable=False, default="Other", server_default="Other")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="Unclassified", server_default="Unclassified")
    niche: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    niche_match_rule: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    client_work: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    software_ai_project: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    provenance: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    grouping_state: Mapped[str] = mapped_column(String(48), nullable=False, default="explicit", server_default="explicit")
    counting_state: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy_unresolved", server_default="legacy_unresolved")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    legacy_source_proof_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    superseded_by_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SellerProof(Base):
    __tablename__ = "seller_proof"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_profile_id: Mapped[int] = mapped_column(ForeignKey("seller_profiles.id"), nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("seller_projects.id"), nullable=True)
    grouping_state: Mapped[str] = mapped_column(String(40), nullable=False, default="unresolved", server_default="unresolved")
    proof_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="Unclassified", server_default="Unclassified")
    niche: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    niche_match_rule: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    public_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    client_work: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    software_ai_project: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    testimonial_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    measurable_result_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    before_after_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    provenance: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    safe_claims_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    prohibited_claims_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    internal_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    share_client_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    share_public_url: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    share_testimonial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    share_case_study: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    share_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    artifact_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    artifact_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    withdrawn_or_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawal_or_deletion_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OfferHistory(Base):
    __tablename__ = "offer_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    seller_profile_id: Mapped[int] = mapped_column(ForeignKey("seller_profiles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    offer_date: Mapped[str] = mapped_column(String(10), nullable=False)
    business_name: Mapped[str] = mapped_column(String(240), nullable=False)
    niche: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    canonical_niche_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    niche_match_rule: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    package_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    canonical_offer_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    offer_resolution_state: Mapped[str] = mapped_column(String(40), nullable=False, default="unmapped", server_default="unmapped")
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    initial_ask: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_ask_at_offer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_ask: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Draft")
    lost_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    growth_score_at_offer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_value_low_at_offer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_value_high_at_offer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_confidence_at_offer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proof_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    commercial_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    commercial_dependency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
