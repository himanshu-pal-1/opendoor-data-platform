"""Utility modules for the OpenDoor Data Platform.

This module exports database utilities and common helper functions.
"""

from src.utils.db_connection import (
    check_connection,
    close_engine,
    get_engine,
    get_session,
    get_session_factory,
    session_scope,
)
from src.utils.db_operations import (
    DatabaseError,
    TransactionManager,
    bulk_insert,
    bulk_upsert,
    count_records,
    execute_query,
    get_table_stats,
    table_exists,
    truncate_table,
)

__all__ = [
    # Connection management
    "get_engine",
    "get_session",
    "get_session_factory",
    "session_scope",
    "check_connection",
    "close_engine",
    # Database operations
    "bulk_insert",
    "bulk_upsert",
    "execute_query",
    "count_records",
    "table_exists",
    "truncate_table",
    "get_table_stats",
    "TransactionManager",
    "DatabaseError",
]
