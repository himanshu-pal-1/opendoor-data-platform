"""NPPES data loader.

This module handles loading parsed NPPES physician data into the
database with support for batch inserts and upsert operations.
"""

from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from tqdm import tqdm

from src.ingest.nppes.nppes_parser import NPPESParser
from src.models.physician import Physician
from src.utils.db_connection import get_session

logger = structlog.get_logger()


class NPPESLoadError(Exception):
    """Raised when NPPES data loading fails."""

    pass


class NPPESLoader:
    """Loader for NPPES physician data into the database.

    This loader handles batch inserts of physician data with support
    for upsert operations (insert or update on conflict) and
    progress tracking.

    Attributes:
        batch_size: Number of records per batch insert.
        session: SQLAlchemy database session.

    Example:
        >>> loader = NPPESLoader(batch_size=5000)
        >>> stats = loader.load_from_file("/data/nppes/npidata.csv")
        >>> print(f"Loaded {stats['inserted']} physicians")
    """

    def __init__(
        self,
        batch_size: int = 5000,
        session: Optional[Session] = None,
    ):
        """Initialize NPPES loader.

        Args:
            batch_size: Number of records per batch insert.
            session: SQLAlchemy session (creates new if not provided).
        """
        self.batch_size = batch_size
        self._session = session
        self._owns_session = session is None

    @property
    def session(self) -> Session:
        """Get or create database session."""
        if self._session is None:
            self._session = get_session()
        return self._session

    def _physician_to_dict(self, physician: Physician) -> dict:
        """Convert Physician model to dictionary for database insert.

        Args:
            physician: Physician model instance.

        Returns:
            Dictionary with database column values.
        """
        return {
            "npi": physician.npi,
            "first_name": physician.first_name,
            "last_name": physician.last_name,
            "middle_name": physician.middle_name,
            "name_suffix": physician.name_suffix,
            "credential": physician.credential.value if physician.credential else None,
            "specialty_primary": physician.specialty_primary,
            "specialty_secondary": physician.specialty_secondary,
            "gender": physician.gender,
            "graduation_year": physician.graduation_year,
            "birth_year": physician.birth_year,
            "practice_address_line1": physician.practice_address_line1,
            "practice_address_line2": physician.practice_address_line2,
            "practice_city": physician.practice_city,
            "practice_state": physician.practice_state,
            "practice_zip": physician.practice_zip,
            "practice_phone": physician.practice_phone,
            "enumeration_date": physician.enumeration_date,
            "last_update_date": physician.last_update_date,
            "is_sole_proprietor": physician.is_sole_proprietor,
            "is_organization_subpart": physician.is_organization_subpart,
            "parent_organization_npi": physician.parent_organization_npi,
        }

    def _batch_upsert(self, batch: list[dict]) -> tuple[int, int]:
        """Perform batch upsert of physician records.

        Args:
            batch: List of physician dictionaries.

        Returns:
            Tuple of (inserted_count, updated_count).
        """
        if not batch:
            return 0, 0

        # Use PostgreSQL upsert (INSERT ... ON CONFLICT)
        stmt = text("""
            INSERT INTO physicians (
                npi, first_name, last_name, middle_name, name_suffix,
                credential, specialty_primary, specialty_secondary, gender,
                graduation_year, birth_year, practice_address_line1,
                practice_address_line2, practice_city, practice_state,
                practice_zip, practice_phone, enumeration_date, last_update_date,
                is_sole_proprietor, is_organization_subpart, parent_organization_npi,
                created_at, updated_at
            )
            VALUES (
                :npi, :first_name, :last_name, :middle_name, :name_suffix,
                :credential, :specialty_primary, :specialty_secondary, :gender,
                :graduation_year, :birth_year, :practice_address_line1,
                :practice_address_line2, :practice_city, :practice_state,
                :practice_zip, :practice_phone, :enumeration_date, :last_update_date,
                :is_sole_proprietor, :is_organization_subpart, :parent_organization_npi,
                NOW(), NOW()
            )
            ON CONFLICT (npi) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                middle_name = EXCLUDED.middle_name,
                name_suffix = EXCLUDED.name_suffix,
                credential = EXCLUDED.credential,
                specialty_primary = EXCLUDED.specialty_primary,
                specialty_secondary = EXCLUDED.specialty_secondary,
                gender = EXCLUDED.gender,
                practice_address_line1 = EXCLUDED.practice_address_line1,
                practice_address_line2 = EXCLUDED.practice_address_line2,
                practice_city = EXCLUDED.practice_city,
                practice_state = EXCLUDED.practice_state,
                practice_zip = EXCLUDED.practice_zip,
                practice_phone = EXCLUDED.practice_phone,
                last_update_date = EXCLUDED.last_update_date,
                is_sole_proprietor = EXCLUDED.is_sole_proprietor,
                is_organization_subpart = EXCLUDED.is_organization_subpart,
                parent_organization_npi = EXCLUDED.parent_organization_npi,
                updated_at = NOW()
        """)

        try:
            for record in batch:
                self.session.execute(stmt, record)
            self.session.commit()
            return len(batch), 0  # Simplified: count all as inserts
        except Exception as e:
            self.session.rollback()
            logger.error("batch_upsert_error", error=str(e), batch_size=len(batch))
            raise

    def load_physicians(
        self,
        physicians: list[Physician],
        show_progress: bool = True,
    ) -> dict:
        """Load a list of physicians into the database.

        Args:
            physicians: List of Physician models to load.
            show_progress: Whether to show progress bar.

        Returns:
            Dictionary with loading statistics.
        """
        stats = {
            "total": len(physicians),
            "inserted": 0,
            "updated": 0,
            "errors": 0,
        }

        batch = []
        iterator = tqdm(physicians, desc="Loading physicians") if show_progress else physicians

        for physician in iterator:
            try:
                batch.append(self._physician_to_dict(physician))

                if len(batch) >= self.batch_size:
                    inserted, updated = self._batch_upsert(batch)
                    stats["inserted"] += inserted
                    stats["updated"] += updated
                    batch = []

            except Exception as e:
                logger.warning("physician_load_error", npi=physician.npi, error=str(e))
                stats["errors"] += 1

        # Load remaining records
        if batch:
            try:
                inserted, updated = self._batch_upsert(batch)
                stats["inserted"] += inserted
                stats["updated"] += updated
            except Exception as e:
                logger.error("final_batch_error", error=str(e))
                stats["errors"] += len(batch)

        logger.info("load_complete", **stats)
        return stats

    def load_from_file(
        self,
        file_path: Path | str,
        parser: Optional[NPPESParser] = None,
        show_progress: bool = True,
    ) -> dict:
        """Load physicians from an NPPES file into the database.

        Args:
            file_path: Path to NPPES CSV file.
            parser: NPPESParser instance (creates new if not provided).
            show_progress: Whether to show progress bar.

        Returns:
            Dictionary with loading statistics.
        """
        if parser is None:
            parser = NPPESParser(chunk_size=self.batch_size)

        file_path = Path(file_path)
        logger.info("loading_from_file", file=str(file_path))

        stats = {
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "errors": 0,
        }

        batch = []

        for physician in parser.parse_file(file_path):
            stats["total"] += 1
            try:
                batch.append(self._physician_to_dict(physician))

                if len(batch) >= self.batch_size:
                    inserted, updated = self._batch_upsert(batch)
                    stats["inserted"] += inserted
                    stats["updated"] += updated
                    batch = []

                    if show_progress:
                        logger.info(
                            "progress",
                            total=stats["total"],
                            inserted=stats["inserted"],
                        )

            except Exception as e:
                logger.warning("physician_load_error", npi=physician.npi, error=str(e))
                stats["errors"] += 1

        # Load remaining records
        if batch:
            try:
                inserted, updated = self._batch_upsert(batch)
                stats["inserted"] += inserted
                stats["updated"] += updated
            except Exception as e:
                logger.error("final_batch_error", error=str(e))
                stats["errors"] += len(batch)

        logger.info("file_load_complete", **stats)
        return stats

    def close(self):
        """Close the database session if owned by this loader."""
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
