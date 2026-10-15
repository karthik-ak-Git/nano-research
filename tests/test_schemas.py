"""Tests for JSON schemas, provenance records, and financial evidence constraints."""

import pytest
from pydantic import ValidationError
from company_agent.schemas import (
    CompanyProfile,
    FactEvidence,
    FactVerificationStatus,
    EvidenceQuality,
    FinancialPeriod,
)
from company_agent.verification import validate_financial_fact


def test_valid_company_profile_schema():
    profile = CompanyProfile(
        organisation_number="923609016",
        name="EQUINOR ASA",
        legal_form="ASA",
        status="Active",
        country="Norway",
        employee_count=21000,
    )
    assert profile.organisation_number == "923609016"
    assert profile.name == "EQUINOR ASA"
    assert profile.schema_version == "1.0.0"


def test_profile_rejects_invalid_organisation_number():
    with pytest.raises(ValidationError):
        CompanyProfile(
            organisation_number="923609017",  # Checksum mismatch
            name="INVALID AS",
        )


def test_missing_dates_are_null_never_fabricated():
    evidence = FactEvidence(
        field_name="employee_count",
        normalized_value=150,
        source_url="https://example.com/about",
        source_domain="example.com",
        excerpt="We employ 150 dedicated specialists.",
        publication_date=None,  # Unknown publication date
    )
    assert evidence.publication_date is None
    assert evidence.retrieval_timestamp is not None


def test_financial_values_require_currency_and_evidence():
    # Valid financial evidence
    is_valid, msg = validate_financial_fact(
        field_name="revenue",
        value=5000000.0,
        currency="NOK",
        period="2024-01-01 to 2024-12-31",
        excerpt="Annual revenue for 2024 reached NOK 5,000,000.",
    )
    assert is_valid is True

    # Missing currency -> must reject
    is_valid_no_curr, msg_curr = validate_financial_fact(
        field_name="revenue",
        value=5000000.0,
        currency=None,
        period="2024-01-01 to 2024-12-31",
        excerpt="Revenue reached 5,000,000.",
    )
    assert is_valid_no_curr is False
    assert "lacks explicit currency" in msg_curr

    # Missing excerpt -> must reject
    is_valid_no_exc, msg_exc = validate_financial_fact(
        field_name="revenue",
        value=5000000.0,
        currency="NOK",
        period="2024",
        excerpt=None,
    )
    assert is_valid_no_exc is False
    assert "lacks direct supporting excerpt" in msg_exc
