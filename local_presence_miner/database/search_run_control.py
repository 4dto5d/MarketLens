from __future__ import annotations

import logging
import os
import time
import uuid
from threading import Event, Thread

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from local_presence_miner.database.schema import ActivityLog, LeadSearch, SearchRunLead, SearchRunLease
from local_presence_miner.time_utils import utc_now

log = logging.getLogger(__name__)

SEARCH_LEASE_KEY = "search-workflow"
DEFAULT_SEARCH_LEASE_SECONDS = 120.0


class SearchLeaseLostError(RuntimeError):
    """Raised when this workflow no longer owns the database search lease."""


class DatabaseSearchLease:
    """Renewable ownership of the singleton Search Workflow lease row."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        owner_id: str,
        lease_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.owner_id = owner_id
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.search_id: int | None = None
        self._stop = Event()
        self._lost: Exception | None = None
        self._heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            name="marketlens-search-lease-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def bind_search(self, session: Session, search_id: int) -> None:
        """Attach the durable run to this lease in the run-creation transaction."""
        now = time.time()
        result = session.execute(
            update(SearchRunLease)
            .where(
                SearchRunLease.lock_key == SEARCH_LEASE_KEY,
                SearchRunLease.owner_id == self.owner_id,
                SearchRunLease.expires_at_epoch > now,
            )
            .values(
                search_id=search_id,
                heartbeat_at_epoch=now,
                expires_at_epoch=now + self.lease_seconds,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise SearchLeaseLostError("The database search lease expired before the Search Run was created.")
        self.search_id = search_id

    def heartbeat(self) -> None:
        if self._lost is not None:
            raise SearchLeaseLostError("The database search lease is no longer owned by this workflow.") from self._lost
        now = time.time()
        with self.session_factory() as session:
            result = session.execute(
                update(SearchRunLease)
                .where(
                    SearchRunLease.lock_key == SEARCH_LEASE_KEY,
                    SearchRunLease.owner_id == self.owner_id,
                    SearchRunLease.expires_at_epoch > now,
                )
                .values(
                    heartbeat_at_epoch=now,
                    expires_at_epoch=now + self.lease_seconds,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                session.rollback()
                error = SearchLeaseLostError("The database search lease expired or was replaced.")
                self._lost = error
                raise error
            session.commit()

    def release(self) -> None:
        self._stop.set()
        self._heartbeat_thread.join(timeout=max(1.0, min(5.0, self.lease_seconds)))
        try:
            with self.session_factory() as session:
                session.execute(
                    delete(SearchRunLease).where(
                        SearchRunLease.lock_key == SEARCH_LEASE_KEY,
                        SearchRunLease.owner_id == self.owner_id,
                    )
                )
                session.commit()
        except SQLAlchemyError:
            # A failed cleanup cannot transfer ownership. The bounded expiry
            # remains the crash/failure recovery mechanism.
            log.warning("Could not delete the completed search lease; it will expire.", exc_info=True)

    def _heartbeat_loop(self) -> None:
        interval = max(0.25, min(15.0, self.lease_seconds / 3.0))
        while not self._stop.wait(interval):
            try:
                self.heartbeat()
            except SearchLeaseLostError:
                return
            except SQLAlchemyError:
                # A short SQLite writer collision can delay one heartbeat. The
                # next interval retries while the authoritative expiry remains.
                log.warning("Search lease heartbeat was delayed by the database.", exc_info=True)


def try_acquire_database_search_lease(
    session_factory: sessionmaker[Session],
    *,
    lease_seconds: float = DEFAULT_SEARCH_LEASE_SECONDS,
) -> DatabaseSearchLease | None:
    """Atomically claim the singleton database lease if absent or expired."""
    now = time.time()
    duration = max(1.0, float(lease_seconds))
    owner_id = f"{os.getpid()}:{uuid.uuid4().hex}"
    statement = (
        sqlite_insert(SearchRunLease)
        .values(
            lock_key=SEARCH_LEASE_KEY,
            owner_id=owner_id,
            owner_pid=os.getpid(),
            search_id=None,
            acquired_at_epoch=now,
            heartbeat_at_epoch=now,
            expires_at_epoch=now + duration,
        )
        .on_conflict_do_update(
            index_elements=[SearchRunLease.lock_key],
            set_={
                "owner_id": owner_id,
                "owner_pid": os.getpid(),
                "search_id": None,
                "acquired_at_epoch": now,
                "heartbeat_at_epoch": now,
                "expires_at_epoch": now + duration,
            },
            where=SearchRunLease.expires_at_epoch <= now,
        )
    )
    with session_factory() as session:
        result = session.execute(statement)
        session.commit()
    if getattr(result, "rowcount", 0) != 1:
        return None
    return DatabaseSearchLease(session_factory, owner_id, duration)


def database_search_is_running(session_factory: sessionmaker[Session]) -> bool:
    with session_factory() as session:
        lease = session.get(SearchRunLease, SEARCH_LEASE_KEY)
        return bool(lease is not None and lease.expires_at_epoch > time.time())


def reconcile_interrupted_search_runs(session_factory: sessionmaker[Session]) -> int:
    """Finalize Running rows not protected by a current database lease."""
    now_epoch = time.time()
    recovered = 0
    with session_factory() as session:
        lease = session.get(SearchRunLease, SEARCH_LEASE_KEY)
        active_search_id = (
            lease.search_id
            if lease is not None and lease.expires_at_epoch > now_epoch
            else None
        )
        searches = list(
            session.scalars(select(LeadSearch).where(LeadSearch.lifecycle_state == "Running"))
        )
        for search in searches:
            if search.id == active_search_id:
                continue
            memberships = list(
                session.scalars(
                    select(SearchRunLead).where(SearchRunLead.search_id == search.id)
                )
            )
            search.total_candidates = max(search.total_candidates, len(memberships))
            search.processed_count = sum(
                item.processing_status in {"Succeeded", "Failed", "Skipped"}
                for item in memberships
            )
            search.succeeded_count = sum(
                item.processing_status == "Succeeded" for item in memberships
            )
            search.failed_count = sum(
                item.processing_status == "Failed" for item in memberships
            )
            search.skipped_count = sum(
                item.processing_status == "Skipped" for item in memberships
            )
            search.new_count = sum(item.discovery_kind == "new" for item in memberships)
            search.rediscovered_count = sum(
                item.discovery_kind == "rediscovered" for item in memberships
            )
            search.lifecycle_state = (
                "Interrupted / Partial" if search.succeeded_count else "Interrupted / Failed"
            )
            search.completed = True
            search.completed_at = utc_now()
            reason = (
                "Search was interrupted before finalization; startup recovery found "
                "no active database search lease for this run."
            )
            search.error_summary = "\n".join(
                value for value in (search.error_summary, reason) if value
            )[:8000]
            session.add(
                ActivityLog(
                    lead_id=None,
                    action="search_recovered",
                    message=f"{search.name}: {search.lifecycle_state}",
                )
            )
            recovered += 1
        session.commit()
    return recovered
