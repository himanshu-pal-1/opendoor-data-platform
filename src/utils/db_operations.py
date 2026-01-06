"""Common database operations.

This module provides helper functions for common database operations
including bulk inserts, upserts, and query utilities.
"""

from typing import Any, Optional, Type, TypeVar

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.utils.db_connection import session_scope

logger = structlog.get_logger()

T = TypeVar("T")


class DatabaseError(Exception):
    """Raised when a database operation fails."""

    pass


def bulk_insert(
    session: Session,
    table_name: str,
    records: list[dict],
    batch_size: int = 1000,
) -> int:
    """Perform bulk insert of records.

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.
        records: List of dictionaries to insert.
        batch_size: Number of records per batch.

    Returns:
        Number of records inserted.
    """
    if not records:
        return 0

    total_inserted = 0
    columns = list(records[0].keys())

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]

        # Build parameterized INSERT statement
        col_list = ", ".join(columns)
        param_list = ", ".join(f":{col}" for col in columns)
        stmt = text(f"INSERT INTO {table_name} ({col_list}) VALUES ({param_list})")

        try:
            for record in batch:
                session.execute(stmt, record)
            session.flush()
            total_inserted += len(batch)
        except Exception as e:
            logger.error(
                "bulk_insert_error",
                table=table_name,
                batch_start=i,
                error=str(e),
            )
            raise DatabaseError(f"Bulk insert failed: {e}")

    logger.info("bulk_insert_complete", table=table_name, count=total_inserted)
    return total_inserted


def bulk_upsert(
    session: Session,
    table_name: str,
    records: list[dict],
    conflict_columns: list[str],
    update_columns: Optional[list[str]] = None,
    batch_size: int = 1000,
) -> int:
    """Perform bulk upsert (insert or update on conflict).

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.
        records: List of dictionaries to upsert.
        conflict_columns: Columns that define uniqueness for conflict detection.
        update_columns: Columns to update on conflict (all non-conflict if None).
        batch_size: Number of records per batch.

    Returns:
        Number of records processed.
    """
    if not records:
        return 0

    total_processed = 0
    columns = list(records[0].keys())

    if update_columns is None:
        update_columns = [c for c in columns if c not in conflict_columns]

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]

        # Build parameterized UPSERT statement
        col_list = ", ".join(columns)
        param_list = ", ".join(f":{col}" for col in columns)
        conflict_list = ", ".join(conflict_columns)
        update_set = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)

        stmt = text(f"""
            INSERT INTO {table_name} ({col_list})
            VALUES ({param_list})
            ON CONFLICT ({conflict_list}) DO UPDATE SET {update_set}
        """)

        try:
            for record in batch:
                session.execute(stmt, record)
            session.flush()
            total_processed += len(batch)
        except Exception as e:
            logger.error(
                "bulk_upsert_error",
                table=table_name,
                batch_start=i,
                error=str(e),
            )
            raise DatabaseError(f"Bulk upsert failed: {e}")

    logger.info("bulk_upsert_complete", table=table_name, count=total_processed)
    return total_processed


def execute_query(
    session: Session,
    query: str,
    params: Optional[dict] = None,
) -> list[dict]:
    """Execute a SELECT query and return results as dictionaries.

    Args:
        session: SQLAlchemy session.
        query: SQL query string.
        params: Query parameters.

    Returns:
        List of result dictionaries.
    """
    try:
        result = session.execute(text(query), params or {})
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as e:
        logger.error("query_execution_error", query=query[:100], error=str(e))
        raise DatabaseError(f"Query execution failed: {e}")


def count_records(session: Session, table_name: str, where: Optional[str] = None) -> int:
    """Count records in a table.

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.
        where: Optional WHERE clause (without 'WHERE' keyword).

    Returns:
        Record count.
    """
    query = f"SELECT COUNT(*) FROM {table_name}"
    if where:
        query += f" WHERE {where}"

    result = session.execute(text(query))
    return result.scalar() or 0


def table_exists(session: Session, table_name: str) -> bool:
    """Check if a table exists in the database.

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.

    Returns:
        True if table exists.
    """
    query = text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = :table_name
        )
    """)
    result = session.execute(query, {"table_name": table_name})
    return result.scalar() or False


def truncate_table(session: Session, table_name: str, cascade: bool = False) -> None:
    """Truncate a table (delete all records).

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.
        cascade: Whether to cascade to dependent tables.
    """
    cascade_str = " CASCADE" if cascade else ""
    session.execute(text(f"TRUNCATE TABLE {table_name}{cascade_str}"))
    logger.info("table_truncated", table=table_name)


def get_table_stats(session: Session, table_name: str) -> dict:
    """Get statistics for a table.

    Args:
        session: SQLAlchemy session.
        table_name: Name of the table.

    Returns:
        Dictionary with table statistics.
    """
    stats = {}

    # Row count
    stats["row_count"] = count_records(session, table_name)

    # Table size
    size_query = text("""
        SELECT pg_size_pretty(pg_total_relation_size(:table_name)) as size,
               pg_total_relation_size(:table_name) as size_bytes
    """)
    result = session.execute(size_query, {"table_name": table_name})
    row = result.fetchone()
    if row:
        stats["size"] = row[0]
        stats["size_bytes"] = row[1]

    return stats


class TransactionManager:
    """Context manager for database transactions.

    Provides automatic commit/rollback handling with optional savepoints.

    Example:
        >>> with TransactionManager(session) as tx:
        ...     tx.execute("INSERT INTO ...")
        ...     if some_condition:
        ...         tx.create_savepoint("sp1")
        ...         tx.execute("UPDATE ...")
    """

    def __init__(self, session: Session):
        """Initialize transaction manager.

        Args:
            session: SQLAlchemy session.
        """
        self.session = session
        self._savepoints: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.session.rollback()
            logger.warning("transaction_rollback", error=str(exc_val))
            return False

        try:
            self.session.commit()
            logger.debug("transaction_committed")
        except Exception as e:
            self.session.rollback()
            logger.error("transaction_commit_failed", error=str(e))
            raise

        return False

    def execute(self, query: str, params: Optional[dict] = None):
        """Execute a query within the transaction."""
        return self.session.execute(text(query), params or {})

    def create_savepoint(self, name: str) -> None:
        """Create a savepoint for partial rollback."""
        self.session.execute(text(f"SAVEPOINT {name}"))
        self._savepoints.append(name)
        logger.debug("savepoint_created", name=name)

    def rollback_to_savepoint(self, name: str) -> None:
        """Rollback to a savepoint."""
        self.session.execute(text(f"ROLLBACK TO SAVEPOINT {name}"))
        logger.debug("savepoint_rollback", name=name)

    def release_savepoint(self, name: str) -> None:
        """Release a savepoint."""
        self.session.execute(text(f"RELEASE SAVEPOINT {name}"))
        if name in self._savepoints:
            self._savepoints.remove(name)
        logger.debug("savepoint_released", name=name)
