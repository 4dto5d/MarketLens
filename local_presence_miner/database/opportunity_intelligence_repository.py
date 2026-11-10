"""Separate append-only advice ledger; never a commercial evidence producer."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from local_presence_miner.database.schema import Base
from local_presence_miner.time_utils import utc_now


class IntelligenceRun(Base):
    __tablename__ = "opportunity_intelligence_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False)
    account_binding: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    packet_json: Mapped[str] = mapped_column(Text, nullable=False)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class IntelligenceResult(Base):
    __tablename__ = "opportunity_intelligence_results"
    __table_args__ = (UniqueConstraint("run_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opportunity_intelligence_runs.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class IntelligenceReview(Base):
    __tablename__ = "opportunity_intelligence_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("opportunity_intelligence_runs.id", ondelete="RESTRICT"), nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False)
    worksheet_id: Mapped[int | None] = mapped_column(ForeignKey("activity_log.id", ondelete="RESTRICT"), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    review_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
