"""Append-only storage; the service owns interpretation and the caller commits."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from local_presence_miner.database.schema import Lead, ProspectFindingRevision


@contextmanager
def finding_write_transaction(session: Session):
    """Savepoints must sit inside a real transaction under legacy SQLite mode."""
    connection = session.connection()
    try:
        driver = connection.connection.driver_connection
        if connection.dialect.name == 'sqlite' and driver is not None and not driver.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        with session.begin_nested():
            yield
    except OperationalError as exc:
        if connection.dialect.name == 'sqlite' and 'locked' in str(exc).casefold():
            raise ValueError('Another database change is in progress; reload and retry the review.') from exc
        raise


def finding_head(session: Session, lead_id: int, finding_key: str) -> ProspectFindingRevision | None:
    return session.scalar(select(ProspectFindingRevision).where(
        ProspectFindingRevision.lead_id == lead_id, ProspectFindingRevision.finding_key == finding_key,
    ).order_by(ProspectFindingRevision.revision.desc()).limit(1))


def finding_rows(session: Session, lead_id: int) -> list[ProspectFindingRevision]:
    return list(session.scalars(select(ProspectFindingRevision).where(
        ProspectFindingRevision.lead_id == lead_id,
    ).order_by(ProspectFindingRevision.finding_key, ProspectFindingRevision.revision)))


def append_finding_revision(
    session: Session, row: ProspectFindingRevision, *, expected_revision: int,
) -> ProspectFindingRevision:
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Expected revision must be a nonnegative integer.")
    if session.get(Lead, row.lead_id) is None:
        raise ValueError("Finding requires an existing business.")
    head = finding_head(session, row.lead_id, row.finding_key)
    if (head.revision if head else 0) != expected_revision:
        raise ValueError("Finding changed since it was opened; reload before saving.")
    row.revision = expected_revision + 1
    row.previous_id = head.id if head else None
    try:
        with finding_write_transaction(session):
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        raise ValueError("Finding revision conflicts with another change or its source ownership.") from exc
    return row
