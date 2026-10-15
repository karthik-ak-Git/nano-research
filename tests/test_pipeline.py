"""End-to-end tests for the complete intelligence pipeline, storage, and export."""

import asyncio
import json
import pytest
from pathlib import Path
from company_agent.database import init_db, get_db_session
from company_agent.models import Company, Fact, ChangeEvent
from company_agent.repositories import CompanyRepository
from company_agent.pipeline import ResearchPipeline
from company_agent.schemas import CompanyProfile


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure database is initialized before each pipeline test."""
    init_db()


@pytest.mark.asyncio
async def test_end_to_end_pipeline_with_mock_provider():
    # Use mock browser provider for zero external spend
    pipe = ResearchPipeline(browser_provider_name="mock")
    # Equinor ASA (923609016)
    profile = await pipe.execute("923609016", force_refresh=True)

    assert isinstance(profile, CompanyProfile)
    assert profile.organisation_number == "923609016"
    assert "EQUINOR" in profile.name.upper()
    assert profile.legal_form == "ASA"
    assert profile.status == "Active"
    assert len(profile.facts) > 0
    assert "name" in profile.facts
    assert "address" in profile.facts

    # Verify fact provenance
    name_fact = profile.facts["name"]
    assert name_fact.verification_status == "VERIFIED"
    assert "data.brreg.no" in name_fact.source_domain


@pytest.mark.asyncio
async def test_change_history_preservation():
    pipe = ResearchPipeline(browser_provider_name="mock")
    # Run initial pipeline
    await pipe.execute("923609016", force_refresh=True)

    with get_db_session() as session:
        repo = CompanyRepository(session)
        company = repo.get_by_org_nr("923609016")
        assert company is not None

        # Simulate historical change: update status to 'In Liquidation'
        source = repo.get_or_create_source("https://test.brreg.no", "test.brreg.no")
        repo.save_or_update_fact(
            company=company,
            field_name="status",
            normalized_value="In Liquidation",
            raw_value="In Liquidation",
            source=source,
            excerpt="Simulated status update",
        )
        repo.record_change(
            company=company,
            field_name="status",
            old_val="Active",
            new_val="In Liquidation",
            explanation="Status changed from Active to In Liquidation",
        )

    # Re-fetch profile and verify history preservation
    with get_db_session() as session:
        repo = CompanyRepository(session)
        company = repo.get_by_org_nr("923609016")
        updated_profile = repo.build_profile_schema(company)

        assert updated_profile.status == "In Liquidation"
        # Provenance history should have the archived old fact
        assert len(updated_profile.provenance_history) >= 1
        assert any(p.field_name == "status" for p in updated_profile.provenance_history)


def test_export_import_roundtrip(tmp_path: Path):
    export_file = tmp_path / "profiles_export.json"

    with get_db_session() as session:
        repo = CompanyRepository(session)
        companies = session.query(Company).all()
        exported_data = [repo.build_profile_schema(c).model_dump(mode="json") for c in companies]

    export_file.write_text(json.dumps(exported_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Read back and parse
    reloaded = json.loads(export_file.read_text(encoding="utf-8"))
    assert len(reloaded) == len(exported_data)
    for item in reloaded:
        # Validate against strict Pydantic model
        validated = CompanyProfile(**item)
        assert len(validated.organisation_number) == 9
