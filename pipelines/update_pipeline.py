"""Incremental update pipeline.

This module implements the incremental data update workflow for
keeping the OpenDoor Data Platform current with new data.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog
from prefect import flow, task

from pipelines.pipeline_config import DATA_SOURCES, get_settings
from src.transform.valuation_engine import ValuationEngine
from src.utils.db_connection import session_scope

logger = structlog.get_logger()


@task(name="check_for_updates")
def check_for_updates() -> dict[str, bool]:
    """Check which data sources have updates available.

    Returns:
        Dictionary of source names and whether updates are available.
    """
    logger.info("checking_for_updates")

    updates_available = {}

    with session_scope() as session:
        from sqlalchemy import text

        for source_name, source_config in DATA_SOURCES.items():
            # Get last update timestamp from audit log
            query = text("""
                SELECT MAX(changed_at) as last_update
                FROM audit_log
                WHERE table_name LIKE :pattern
            """)

            pattern = f"{source_name}%"
            result = session.execute(query, {"pattern": pattern})
            row = result.fetchone()

            last_update = row[0] if row and row[0] else None

            if last_update is None:
                updates_available[source_name] = True
            else:
                # Check if update interval has passed
                if source_config.update_frequency == "daily":
                    threshold = timedelta(days=1)
                elif source_config.update_frequency == "weekly":
                    threshold = timedelta(weeks=1)
                elif source_config.update_frequency == "monthly":
                    threshold = timedelta(days=30)
                elif source_config.update_frequency == "quarterly":
                    threshold = timedelta(days=90)
                else:  # annually
                    threshold = timedelta(days=365)

                updates_available[source_name] = (
                    datetime.utcnow() - last_update > threshold
                )

    logger.info("update_check_complete", updates=updates_available)
    return updates_available


@task(name="download_updates")
def download_updates(sources: list[str]) -> dict[str, Path]:
    """Download updates for specified data sources.

    Args:
        sources: List of source names to update.

    Returns:
        Dictionary of source names to downloaded file paths.
    """
    settings = get_settings()
    downloaded = {}

    for source in sources:
        logger.info("downloading_update", source=source)

        try:
            if source == "nppes":
                from src.ingest.nppes import NPPESClient

                client = NPPESClient(download_dir=settings.nppes_directory)
                downloaded[source] = client.download_latest()

            elif source == "cms_payments":
                from src.ingest.cms import CMSClient

                client = CMSClient(download_dir=settings.cms_directory)
                year = datetime.now().year - 1
                downloaded[source] = client.download_physician_payments(year)

        except Exception as e:
            logger.error("download_update_failed", source=source, error=str(e))

    logger.info("downloads_complete", downloaded=list(downloaded.keys()))
    return downloaded


@task(name="process_updates")
def process_updates(downloads: dict[str, Path]) -> dict:
    """Process downloaded update files.

    Args:
        downloads: Dictionary of source names to file paths.

    Returns:
        Dictionary with processing statistics.
    """
    settings = get_settings()
    stats = {}

    for source, file_path in downloads.items():
        logger.info("processing_update", source=source, file=str(file_path))

        try:
            if source == "nppes":
                from src.ingest.nppes import NPPESLoader, NPPESParser

                parser = NPPESParser(chunk_size=settings.batch_size)
                with NPPESLoader(batch_size=settings.batch_size) as loader:
                    stats[source] = loader.load_from_file(file_path, parser)

            elif source == "cms_payments":
                from src.ingest.cms import CMSParser

                year = datetime.now().year - 1
                parser = CMSParser(chunk_size=settings.batch_size)

                # Process CMS data
                payment_count = 0
                with session_scope() as session:
                    from sqlalchemy import text
                    import json

                    for payment in parser.parse_physician_payments(file_path, year):
                        stmt = text("""
                            INSERT INTO cms_payments (
                                physician_npi, year, total_medicare_payment,
                                total_services, total_beneficiaries
                            ) VALUES (:npi, :year, :payment, :services, :benes)
                            ON CONFLICT (physician_npi, year) DO UPDATE SET
                                total_medicare_payment = EXCLUDED.total_medicare_payment,
                                total_services = EXCLUDED.total_services
                        """)

                        session.execute(stmt, {
                            "npi": payment.npi,
                            "year": payment.year,
                            "payment": float(payment.total_medicare_payment),
                            "services": payment.total_services,
                            "benes": payment.total_beneficiaries,
                        })
                        payment_count += 1

                        if payment_count % 10000 == 0:
                            session.commit()

                    session.commit()

                stats[source] = {"processed": payment_count}

        except Exception as e:
            logger.error("process_update_failed", source=source, error=str(e))
            stats[source] = {"error": str(e)}

    logger.info("updates_processed", stats=stats)
    return stats


@task(name="refresh_valuations")
def refresh_valuations(limit: Optional[int] = 1000) -> dict:
    """Refresh valuations for practices with updated data.

    Args:
        limit: Maximum number of valuations to refresh.

    Returns:
        Dictionary with refresh statistics.
    """
    logger.info("refreshing_valuations", limit=limit)

    engine = ValuationEngine()
    stats = {"refreshed": 0, "errors": 0}

    with session_scope() as session:
        from sqlalchemy import text

        from src.models.practice import Practice, PracticeLocation

        # Get practices that need valuation refresh
        # Prioritize those updated since last valuation
        query = text("""
            SELECT
                p.id, p.name, p.practice_type, p.organization_npi,
                p.address_line1, p.city, p.state, p.zip_code,
                p.physician_count, p.patient_panel_size, p.revenue_annual,
                p.ebitda, p.payer_mix_medicare, p.payer_mix_commercial,
                p.payer_mix_medicaid, p.payer_mix_self_pay, p.payer_mix_other,
                p.specialty_primary
            FROM practices p
            LEFT JOIN valuations v ON p.id = v.practice_id
            WHERE p.revenue_annual IS NOT NULL
            AND p.revenue_annual > 0
            AND (v.id IS NULL OR p.updated_at > v.calculation_timestamp)
            ORDER BY p.updated_at DESC
            LIMIT :limit
        """)

        practices = session.execute(query, {"limit": limit}).fetchall()

        for row in practices:
            try:
                location = None
                if row[6]:  # state
                    location = PracticeLocation(
                        address_line1=row[4] or "Unknown",
                        city=row[5] or "Unknown",
                        state=row[6],
                        zip_code=row[7] or "00000",
                    )

                practice = Practice(
                    id=row[0],
                    name=row[1],
                    location=location,
                    physician_count=row[8] or 1,
                    patient_panel_size=row[9],
                    revenue_annual=row[10],
                    ebitda=row[11],
                    payer_mix_medicare=row[12] or 0,
                    payer_mix_commercial=row[13] or 0,
                    payer_mix_medicaid=row[14] or 0,
                    payer_mix_self_pay=row[15] or 0,
                    payer_mix_other=row[16] or 0,
                    specialty_primary=row[17],
                )

                result = engine.calculate_valuation(practice)

                # Insert new valuation (keeping history)
                insert_query = text("""
                    INSERT INTO valuations (
                        practice_id, valuation_amount, valuation_low,
                        valuation_high, method, combined_multiplier,
                        confidence_level, data_completeness_score
                    ) VALUES (
                        :practice_id, :valuation, :low, :high,
                        :method, :combined, :confidence, :data_score
                    )
                """)

                session.execute(insert_query, {
                    "practice_id": str(practice.id),
                    "valuation": float(result.valuation_amount),
                    "low": float(result.valuation_low) if result.valuation_low else None,
                    "high": float(result.valuation_high) if result.valuation_high else None,
                    "method": result.method.value,
                    "combined": result.multipliers.combined_multiplier,
                    "confidence": result.confidence_level.value,
                    "data_score": result.data_completeness_score,
                })

                stats["refreshed"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.warning("valuation_refresh_error", error=str(e))

        session.commit()

    logger.info("valuation_refresh_complete", **stats)
    return stats


@flow(name="incremental_update_pipeline")
def run_update_pipeline(
    force_sources: Optional[list[str]] = None,
) -> dict:
    """Run the incremental update pipeline.

    Args:
        force_sources: Force update these sources regardless of schedule.

    Returns:
        Dictionary with pipeline execution results.
    """
    logger.info("starting_update_pipeline")

    results = {}

    # Step 1: Check for updates
    updates = check_for_updates()

    # Add forced sources
    if force_sources:
        for source in force_sources:
            updates[source] = True

    sources_to_update = [s for s, available in updates.items() if available]

    if not sources_to_update:
        logger.info("no_updates_needed")
        return {"status": "no_updates", "checked": updates}

    # Step 2: Download updates
    downloads = download_updates(sources_to_update)
    results["downloads"] = list(downloads.keys())

    # Step 3: Process updates
    if downloads:
        results["processing"] = process_updates(downloads)

    # Step 4: Refresh valuations
    results["valuations"] = refresh_valuations()

    logger.info("update_pipeline_complete", results=results)
    return results


def main():
    """Main entry point for running the update pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Run incremental update pipeline")
    parser.add_argument(
        "--force",
        nargs="+",
        help="Force update these sources",
        default=None,
    )
    args = parser.parse_args()

    results = run_update_pipeline(force_sources=args.force)

    print("\nUpdate Pipeline Results:")
    for step, result in results.items():
        print(f"  {step}: {result}")


if __name__ == "__main__":
    main()
