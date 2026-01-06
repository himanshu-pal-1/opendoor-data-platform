"""Database initialization script.

This module provides functionality to initialize the database schema
by running the SQL migration files.
"""

import os
from pathlib import Path

import structlog
from sqlalchemy import text

from src.utils.db_connection import get_engine, session_scope

logger = structlog.get_logger()


def run_sql_file(file_path: Path) -> None:
    """Execute a SQL file against the database.

    Args:
        file_path: Path to the SQL file.

    Raises:
        Exception: If SQL execution fails.
    """
    logger.info("running_sql_file", file=str(file_path))

    with open(file_path, "r") as f:
        sql_content = f.read()

    engine = get_engine()
    with engine.connect() as conn:
        # Split by semicolons and execute each statement
        # This handles multiple statements in a single file
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]

        for statement in statements:
            if statement:
                try:
                    conn.execute(text(statement))
                except Exception as e:
                    logger.error(
                        "sql_statement_error",
                        error=str(e),
                        statement=statement[:100],
                    )
                    raise

        conn.commit()

    logger.info("sql_file_complete", file=str(file_path))


def init_database() -> None:
    """Initialize the database with the schema.

    This function runs all migration files in order to set up
    the database schema.
    """
    migrations_dir = Path(__file__).parent

    # Run schema initialization
    schema_file = migrations_dir / "init_schema.sql"
    if schema_file.exists():
        run_sql_file(schema_file)
        logger.info("database_initialized")
    else:
        logger.error("schema_file_not_found", file=str(schema_file))
        raise FileNotFoundError(f"Schema file not found: {schema_file}")


def check_tables_exist() -> dict[str, bool]:
    """Check which tables exist in the database.

    Returns:
        Dictionary of table names and their existence status.
    """
    tables = [
        "physicians",
        "practices",
        "practice_physicians",
        "payers",
        "payer_contracts",
        "valuations",
        "physician_segments",
        "cms_payments",
        "audit_log",
    ]

    results = {}

    with session_scope() as session:
        for table in tables:
            query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = :table_name
                )
            """)
            result = session.execute(query, {"table_name": table})
            results[table] = result.scalar() or False

    return results


def main():
    """Main entry point for database initialization."""
    import argparse

    parser = argparse.ArgumentParser(description="Initialize OpenDoor database")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check if tables exist, don't create them",
    )
    args = parser.parse_args()

    if args.check:
        tables = check_tables_exist()
        print("\nTable Status:")
        for table, exists in tables.items():
            status = "✓" if exists else "✗"
            print(f"  {status} {table}")

        all_exist = all(tables.values())
        if all_exist:
            print("\nAll tables exist!")
        else:
            missing = [t for t, e in tables.items() if not e]
            print(f"\nMissing tables: {', '.join(missing)}")
    else:
        print("Initializing database...")
        init_database()
        print("Database initialized successfully!")


if __name__ == "__main__":
    main()
