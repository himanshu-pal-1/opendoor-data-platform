"""Main data ingestion pipeline.

This module implements the full data ingestion workflow for the
OpenDoor Data Platform, orchestrated with Prefect.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from prefect import flow, task
from prefect.task_runners import SequentialTaskRunner

from pipelines.pipeline_config import get_settings
from src.ingest.cms import CMSClient, CMSEnricher, CMSParser
from src.ingest.nppes import NPPESClient, NPPESLoader, NPPESParser
from src.transform.valuation_engine import ValuationEngine
from src.utils.db_connection import check_connection, session_scope

logger = structlog.get_logger()


@task(name="download_nppes_data", retries=3, retry_delay_seconds=60)
def download_nppes_data(data_dir: Optional[str] = None) -> Path:
    """Download the latest NPPES data file.

    Args:
        data_dir: Directory to store downloaded files.

    Returns:
        Path to the downloaded/extracted NPI file.
    """
    settings = get_settings()
    data_dir = data_dir or settings.nppes_directory

    logger.info("starting_nppes_download", data_dir=data_dir)

    client = NPPESClient(download_dir=data_dir)
    file_path = client.download_latest(extract=True)

    logger.info("nppes_download_complete", file=str(file_path))
    return file_path


@task(name="parse_and_load_nppes", retries=2, retry_delay_seconds=120)
def parse_and_load_nppes(file_path: Path) -> dict:
    """Parse NPPES file and load physicians into database.

    Args:
        file_path: Path to NPPES CSV file.

    Returns:
        Dictionary with loading statistics.
    """
    settings = get_settings()

    logger.info("starting_nppes_parse", file=str(file_path))

    parser = NPPESParser(chunk_size=settings.batch_size)

    with NPPESLoader(batch_size=settings.batch_size) as loader:
        stats = loader.load_from_file(file_path, parser)

    logger.info("nppes_load_complete", **stats)
    return stats


@task(name="download_cms_data", retries=3, retry_delay_seconds=60)
def download_cms_data(
    year: Optional[int] = None,
    data_dir: Optional[str] = None,
) -> Path:
    """Download CMS Medicare payment data.

    Args:
        year: Data year (defaults to most recent).
        data_dir: Directory to store downloaded files.

    Returns:
        Path to the downloaded CMS file.
    """
    settings = get_settings()
    data_dir = data_dir or settings.cms_directory

    if year is None:
        year = datetime.now().year - 1  # Previous year's data

    logger.info("starting_cms_download", year=year, data_dir=data_dir)

    client = CMSClient(download_dir=data_dir)

    try:
        file_path = client.download_physician_payments(year)
        logger.info("cms_download_complete", file=str(file_path))
        return file_path
    except Exception as e:
        logger.warning("cms_download_failed", year=year, error=str(e))
        # Return None or raise - for now, log and continue
        raise


@task(name="parse_and_load_cms", retries=2, retry_delay_seconds=120)
def parse_and_load_cms(file_path: Path, year: int) -> dict:
    """Parse CMS payment file and load into database.

    Args:
        file_path: Path to CMS CSV file.
        year: Data year.

    Returns:
        Dictionary with loading statistics.
    """
    settings = get_settings()

    logger.info("starting_cms_parse", file=str(file_path), year=year)

    parser = CMSParser(chunk_size=settings.batch_size)

    stats = {"total": 0, "inserted": 0, "errors": 0}

    with session_scope() as session:
        from sqlalchemy import text

        for payment in parser.parse_physician_payments(file_path, year):
            stats["total"] += 1

            try:
                # Insert payment record
                stmt = text("""
                    INSERT INTO cms_payments (
                        physician_npi, year, total_medicare_payment,
                        total_services, total_beneficiaries,
                        avg_submitted_charge, avg_medicare_allowed,
                        avg_medicare_payment, service_breakdown
                    ) VALUES (
                        :npi, :year, :total_payment, :total_services,
                        :total_beneficiaries, :avg_submitted, :avg_allowed,
                        :avg_payment, :service_breakdown::jsonb
                    )
                    ON CONFLICT (physician_npi, year) DO UPDATE SET
                        total_medicare_payment = EXCLUDED.total_medicare_payment,
                        total_services = EXCLUDED.total_services,
                        total_beneficiaries = EXCLUDED.total_beneficiaries,
                        avg_submitted_charge = EXCLUDED.avg_submitted_charge,
                        avg_medicare_allowed = EXCLUDED.avg_medicare_allowed,
                        avg_medicare_payment = EXCLUDED.avg_medicare_payment,
                        service_breakdown = EXCLUDED.service_breakdown
                """)

                import json

                session.execute(stmt, {
                    "npi": payment.npi,
                    "year": payment.year,
                    "total_payment": float(payment.total_medicare_payment),
                    "total_services": payment.total_services,
                    "total_beneficiaries": payment.total_beneficiaries,
                    "avg_submitted": float(payment.avg_submitted_charge) if payment.avg_submitted_charge else None,
                    "avg_allowed": float(payment.avg_medicare_allowed) if payment.avg_medicare_allowed else None,
                    "avg_payment": float(payment.avg_medicare_payment) if payment.avg_medicare_payment else None,
                    "service_breakdown": json.dumps(payment.service_breakdown),
                })

                stats["inserted"] += 1

                if stats["inserted"] % 10000 == 0:
                    session.commit()
                    logger.debug("cms_progress", inserted=stats["inserted"])

            except Exception as e:
                stats["errors"] += 1
                logger.warning("cms_record_error", npi=payment.npi, error=str(e))

        session.commit()

    logger.info("cms_load_complete", **stats)
    return stats


@task(name="create_practices")
def create_practices() -> dict:
    """Create practice records from physician data.

    Identifies unique practices based on organization NPIs and
    creates practice records in the database.

    Returns:
        Dictionary with creation statistics.
    """
    logger.info("starting_practice_creation")

    stats = {"practices_created": 0, "physicians_linked": 0}

    with session_scope() as session:
        from sqlalchemy import text

        # Find unique organization NPIs (Type 2 NPIs)
        org_query = text("""
            SELECT DISTINCT parent_organization_npi
            FROM physicians
            WHERE parent_organization_npi IS NOT NULL
        """)

        result = session.execute(org_query)
        org_npis = [row[0] for row in result.fetchall()]

        for org_npi in org_npis:
            # Get practice details from physicians
            physician_query = text("""
                SELECT
                    MIN(first_name || ' ' || last_name) as first_physician,
                    COUNT(*) as physician_count,
                    MIN(practice_address_line1) as address,
                    MIN(practice_city) as city,
                    MIN(practice_state) as state,
                    MIN(practice_zip) as zip_code,
                    MIN(specialty_primary) as specialty
                FROM physicians
                WHERE parent_organization_npi = :org_npi
            """)

            physician_data = session.execute(
                physician_query, {"org_npi": org_npi}
            ).fetchone()

            if physician_data:
                # Create practice record
                practice_insert = text("""
                    INSERT INTO practices (
                        organization_npi, name, address_line1,
                        city, state, zip_code, physician_count,
                        specialty_primary, practice_type
                    ) VALUES (
                        :org_npi, :name, :address, :city, :state,
                        :zip, :physician_count, :specialty, 'group_small'
                    )
                    ON CONFLICT (organization_npi) DO UPDATE SET
                        physician_count = EXCLUDED.physician_count,
                        updated_at = NOW()
                    RETURNING id
                """)

                practice_result = session.execute(practice_insert, {
                    "org_npi": org_npi,
                    "name": f"Practice {org_npi}",  # Would need actual name lookup
                    "address": physician_data[2],
                    "city": physician_data[3],
                    "state": physician_data[4],
                    "zip": physician_data[5],
                    "physician_count": physician_data[1],
                    "specialty": physician_data[6],
                })

                practice_id = practice_result.fetchone()[0]
                stats["practices_created"] += 1

                # Link physicians to practice
                link_query = text("""
                    INSERT INTO practice_physicians (practice_id, physician_npi)
                    SELECT :practice_id, npi
                    FROM physicians
                    WHERE parent_organization_npi = :org_npi
                    ON CONFLICT DO NOTHING
                """)

                session.execute(link_query, {
                    "practice_id": practice_id,
                    "org_npi": org_npi,
                })

        # Also create solo practices for sole proprietors
        solo_query = text("""
            INSERT INTO practices (
                organization_npi, name, address_line1, city, state,
                zip_code, physician_count, specialty_primary, practice_type
            )
            SELECT
                npi, first_name || ' ' || last_name || ' Practice',
                practice_address_line1, practice_city, practice_state,
                practice_zip, 1, specialty_primary, 'solo'
            FROM physicians
            WHERE is_sole_proprietor = TRUE
            AND parent_organization_npi IS NULL
            ON CONFLICT DO NOTHING
        """)

        result = session.execute(solo_query)
        stats["solo_practices_created"] = result.rowcount

        session.commit()

    logger.info("practice_creation_complete", **stats)
    return stats


@task(name="enrich_practices")
def enrich_practices() -> dict:
    """Enrich practices with CMS payment data.

    Returns:
        Dictionary with enrichment statistics.
    """
    logger.info("starting_practice_enrichment")

    enricher = CMSEnricher()
    stats = {"enriched": 0, "skipped": 0}

    with session_scope() as session:
        from sqlalchemy import text

        # Get practices that need enrichment
        practices_query = text("""
            SELECT id, organization_npi, specialty_primary, state
            FROM practices
            WHERE revenue_annual IS NULL
            LIMIT 1000
        """)

        practices = session.execute(practices_query).fetchall()

        for practice in practices:
            practice_id, org_npi, specialty, state = practice

            # Get physician NPIs for this practice
            physicians_query = text("""
                SELECT physician_npi
                FROM practice_physicians
                WHERE practice_id = :practice_id
            """)

            physician_result = session.execute(
                physicians_query, {"practice_id": practice_id}
            )
            physician_npis = [row[0] for row in physician_result.fetchall()]

            if not physician_npis and org_npi:
                physician_npis = [org_npi]

            # Get payments
            payments = enricher.get_physician_payments_from_db(
                session, physician_npis
            )

            if not payments:
                stats["skipped"] += 1
                continue

            # Calculate aggregates
            total_medicare = sum(p.total_medicare_payment for p in payments.values())
            total_beneficiaries = sum(p.total_beneficiaries for p in payments.values())

            # Estimate payer mix and revenue
            payer_mix = enricher.estimate_payer_mix(
                total_medicare, None, specialty, state
            )

            estimated_revenue = enricher.estimate_total_revenue(
                total_medicare, payer_mix["medicare"]
            )

            estimated_panel = enricher.estimate_patient_panel(
                total_beneficiaries, payer_mix["medicare"]
            )

            # Update practice
            update_query = text("""
                UPDATE practices SET
                    revenue_annual = :revenue,
                    patient_panel_size = :panel_size,
                    payer_mix_medicare = :medicare,
                    payer_mix_commercial = :commercial,
                    payer_mix_medicaid = :medicaid,
                    payer_mix_self_pay = :self_pay,
                    payer_mix_other = :other,
                    updated_at = NOW()
                WHERE id = :practice_id
            """)

            session.execute(update_query, {
                "practice_id": practice_id,
                "revenue": float(estimated_revenue),
                "panel_size": estimated_panel,
                "medicare": payer_mix["medicare"],
                "commercial": payer_mix["commercial"],
                "medicaid": payer_mix["medicaid"],
                "self_pay": payer_mix["self_pay"],
                "other": payer_mix["other"],
            })

            stats["enriched"] += 1

        session.commit()

    logger.info("practice_enrichment_complete", **stats)
    return stats


@task(name="calculate_valuations")
def calculate_valuations() -> dict:
    """Calculate valuations for all practices.

    Returns:
        Dictionary with valuation statistics.
    """
    logger.info("starting_valuation_calculation")

    engine = ValuationEngine()
    stats = {"calculated": 0, "errors": 0}

    with session_scope() as session:
        from sqlalchemy import text

        from src.models.practice import Practice, PracticeLocation

        # Get practices with revenue data
        practices_query = text("""
            SELECT
                id, name, practice_type, organization_npi,
                address_line1, city, state, zip_code,
                physician_count, patient_panel_size, revenue_annual,
                ebitda, payer_mix_medicare, payer_mix_commercial,
                payer_mix_medicaid, payer_mix_self_pay, payer_mix_other,
                specialty_primary
            FROM practices
            WHERE revenue_annual IS NOT NULL
            AND revenue_annual > 0
        """)

        practices = session.execute(practices_query).fetchall()

        for row in practices:
            try:
                # Build Practice model
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

                # Calculate valuation
                result = engine.calculate_valuation(practice)

                # Store valuation
                insert_query = text("""
                    INSERT INTO valuations (
                        practice_id, valuation_amount, valuation_low,
                        valuation_high, method, payer_mix_multiplier,
                        geographic_multiplier, specialty_multiplier,
                        size_multiplier, growth_multiplier, combined_multiplier,
                        base_revenue, patient_panel_size, revenue_per_patient,
                        revenue_multiple, confidence_level, data_completeness_score,
                        payer_mix_rationale, geographic_rationale, specialty_rationale
                    ) VALUES (
                        :practice_id, :valuation, :low, :high, :method,
                        :payer_mult, :geo_mult, :spec_mult, :size_mult,
                        :growth_mult, :combined_mult, :base_revenue,
                        :panel_size, :rev_per_patient, :rev_multiple,
                        :confidence, :data_score,
                        :payer_rationale, :geo_rationale, :spec_rationale
                    )
                """)

                session.execute(insert_query, {
                    "practice_id": str(practice.id),
                    "valuation": float(result.valuation_amount),
                    "low": float(result.valuation_low) if result.valuation_low else None,
                    "high": float(result.valuation_high) if result.valuation_high else None,
                    "method": result.method.value,
                    "payer_mult": result.multipliers.payer_mix_multiplier,
                    "geo_mult": result.multipliers.geographic_multiplier,
                    "spec_mult": result.multipliers.specialty_multiplier,
                    "size_mult": result.multipliers.size_multiplier,
                    "growth_mult": result.multipliers.growth_multiplier,
                    "combined_mult": result.multipliers.combined_multiplier,
                    "base_revenue": float(result.base_revenue) if result.base_revenue else None,
                    "panel_size": result.patient_panel_size,
                    "rev_per_patient": float(result.revenue_per_patient) if result.revenue_per_patient else None,
                    "rev_multiple": result.revenue_multiple,
                    "confidence": result.confidence_level.value,
                    "data_score": result.data_completeness_score,
                    "payer_rationale": result.multipliers.payer_mix_rationale,
                    "geo_rationale": result.multipliers.geographic_rationale,
                    "spec_rationale": result.multipliers.specialty_rationale,
                })

                stats["calculated"] += 1

            except Exception as e:
                stats["errors"] += 1
                logger.warning("valuation_error", practice_id=str(row[0]), error=str(e))

        session.commit()

    logger.info("valuation_calculation_complete", **stats)
    return stats


@task(name="segment_physicians")
def segment_physicians() -> dict:
    """Segment physicians into acquisition target categories.

    Returns:
        Dictionary with segmentation statistics.
    """
    logger.info("starting_physician_segmentation")

    stats = {"type_1": 0, "type_2": 0, "type_3": 0, "type_4": 0}

    with session_scope() as session:
        from sqlalchemy import text

        current_year = datetime.now().year

        # Type 1: Solo owners 55+, potential decline
        type_1_query = text("""
            INSERT INTO physician_segments (
                physician_npi, segment_type, segment_score,
                acquisition_likelihood, is_solo_owner, is_near_retirement
            )
            SELECT
                npi, 'type_1', 0.8, 0.7, TRUE, TRUE
            FROM physicians
            WHERE is_sole_proprietor = TRUE
            AND birth_year IS NOT NULL
            AND (:current_year - birth_year) >= 55
            ON CONFLICT (physician_npi) DO UPDATE SET
                segment_type = 'type_1',
                segment_score = 0.8,
                acquisition_likelihood = 0.7,
                is_solo_owner = TRUE,
                is_near_retirement = TRUE,
                updated_at = NOW()
        """)

        result = session.execute(type_1_query, {"current_year": current_year})
        stats["type_1"] = result.rowcount

        # Type 2: Group practice members
        type_2_query = text("""
            INSERT INTO physician_segments (
                physician_npi, segment_type, segment_score,
                acquisition_likelihood, has_partnership_potential
            )
            SELECT
                npi, 'type_2', 0.5, 0.4, TRUE
            FROM physicians
            WHERE parent_organization_npi IS NOT NULL
            AND is_sole_proprietor = FALSE
            AND npi NOT IN (SELECT physician_npi FROM physician_segments)
            ON CONFLICT (physician_npi) DO UPDATE SET
                segment_type = 'type_2',
                segment_score = 0.5,
                has_partnership_potential = TRUE,
                updated_at = NOW()
        """)

        result = session.execute(type_2_query)
        stats["type_2"] = result.rowcount

        # Type 3: Health system employed (would need additional data)
        # Placeholder - would identify based on organization type

        # Type 4: Recent graduates (within 5 years)
        type_4_query = text("""
            INSERT INTO physician_segments (
                physician_npi, segment_type, segment_score,
                acquisition_likelihood, is_recent_graduate
            )
            SELECT
                npi, 'type_4', 0.4, 0.3, TRUE
            FROM physicians
            WHERE graduation_year IS NOT NULL
            AND (:current_year - graduation_year) <= 5
            AND npi NOT IN (SELECT physician_npi FROM physician_segments)
            ON CONFLICT (physician_npi) DO UPDATE SET
                segment_type = 'type_4',
                segment_score = 0.4,
                is_recent_graduate = TRUE,
                updated_at = NOW()
        """)

        result = session.execute(type_4_query, {"current_year": current_year})
        stats["type_4"] = result.rowcount

        session.commit()

    logger.info("segmentation_complete", **stats)
    return stats


@flow(
    name="full_ingestion_pipeline",
    description="Complete data ingestion pipeline for OpenDoor Data Platform",
    task_runner=SequentialTaskRunner(),
)
def run_ingestion_pipeline(
    nppes_file: Optional[Path] = None,
    cms_file: Optional[Path] = None,
    cms_year: Optional[int] = None,
) -> dict:
    """Run the complete data ingestion pipeline.

    Args:
        nppes_file: Pre-downloaded NPPES file (downloads if not provided).
        cms_file: Pre-downloaded CMS file (downloads if not provided).
        cms_year: CMS data year.

    Returns:
        Dictionary with pipeline execution statistics.
    """
    logger.info("starting_ingestion_pipeline")

    results = {}

    # Check database connection
    if not check_connection():
        raise RuntimeError("Database connection failed")

    # Step 1: Download and load NPPES data
    if nppes_file is None:
        nppes_file = download_nppes_data()

    results["nppes"] = parse_and_load_nppes(nppes_file)

    # Step 2: Download and load CMS data
    if cms_year is None:
        cms_year = datetime.now().year - 1

    if cms_file is None:
        try:
            cms_file = download_cms_data(cms_year)
            results["cms"] = parse_and_load_cms(cms_file, cms_year)
        except Exception as e:
            logger.warning("cms_pipeline_step_failed", error=str(e))
            results["cms"] = {"status": "skipped", "error": str(e)}

    # Step 3: Create practice records
    results["practices"] = create_practices()

    # Step 4: Enrich practices with CMS data
    results["enrichment"] = enrich_practices()

    # Step 5: Calculate valuations
    results["valuations"] = calculate_valuations()

    # Step 6: Segment physicians
    results["segmentation"] = segment_physicians()

    logger.info("ingestion_pipeline_complete", results=results)
    return results


def main():
    """Main entry point for running the ingestion pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Run OpenDoor data ingestion pipeline")
    parser.add_argument("--nppes-file", type=Path, help="Path to NPPES file")
    parser.add_argument("--cms-file", type=Path, help="Path to CMS file")
    parser.add_argument("--cms-year", type=int, help="CMS data year")
    args = parser.parse_args()

    results = run_ingestion_pipeline(
        nppes_file=args.nppes_file,
        cms_file=args.cms_file,
        cms_year=args.cms_year,
    )

    print("\nPipeline Results:")
    for step, result in results.items():
        print(f"  {step}: {result}")


if __name__ == "__main__":
    main()
