"""Tests for identity verification, entity resolution, and quarantine rules."""

from company_agent.identity import verify_entity_resolution
from company_agent.verification import verify_fact_provenance
from company_agent.schemas import FactVerificationStatus, EvidenceQuality


def test_entity_resolution_direct_match():
    status, expl, conf = verify_entity_resolution(
        requested_org_nr="923609016",
        registry_legal_name="EQUINOR ASA",
        source_org_nr="923609016",
    )
    assert status == "VERIFIED_MATCH"
    assert conf == 1.0


def test_entity_resolution_conflict_mismatch():
    status, expl, conf = verify_entity_resolution(
        requested_org_nr="923609016",
        registry_legal_name="EQUINOR ASA",
        source_org_nr="976633408",  # Telenor's org nr
    )
    assert status == "CONFLICT_MISMATCH"
    assert conf == 0.0
    assert "Conflict" in expl


def test_entity_resolution_secondary_supported():
    status, expl, conf = verify_entity_resolution(
        requested_org_nr="923609016",
        registry_legal_name="EQUINOR ASA",
        source_name="Equinor",
        source_domain="equinor.com",
        official_domain="www.equinor.com",
    )
    assert status == "SECONDARY_SUPPORTED"
    assert conf > 0.8


def test_entity_resolution_unverified():
    status, expl, conf = verify_entity_resolution(
        requested_org_nr="923609016",
        registry_legal_name="EQUINOR ASA",
        source_name="Unrelated Company AS",
        source_domain="random-site.com",
    )
    assert status == "UNVERIFIED"
    assert conf < 0.5


def test_verify_fact_provenance_registry():
    status, quality, conf, expl = verify_fact_provenance(
        field_name="legal_form",
        value="ASA",
        source_url="https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
        requested_org_nr="923609016",
        registry_legal_name="EQUINOR ASA",
        is_registry_source=True,
    )
    assert status == FactVerificationStatus.VERIFIED
    assert quality == EvidenceQuality.REGISTRY_OFFICIAL
    assert conf == 1.0


def test_validate_financial_fact_rules():
    from company_agent.verification import validate_financial_fact

    # Valid
    ok, msg = validate_financial_fact("revenue", 1000000.0, "NOK", "2024", "Revenue 1000000 NOK")
    assert ok is True

    # Missing currency (never infer currency)
    ok, msg = validate_financial_fact("revenue", 1000000.0, None, "2024", "Revenue 1000000")
    assert ok is False
    assert "currency" in msg

    # Missing excerpt
    ok, msg = validate_financial_fact("revenue", 1000000.0, "NOK", "2024", None)
    assert ok is False
    assert "excerpt" in msg


def test_verify_fact_provenance_conflict_quarantined():
    status, quality, conf, expl = verify_fact_provenance(
        field_name="description",
        value="A telecommunications provider",
        source_url="https://www.telenor.com",
        requested_org_nr="923609016",  # Equinor
        registry_legal_name="EQUINOR ASA",
        source_org_nr="976633408",    # Telenor
        source_domain="telenor.com",
        official_domain="equinor.com",
    )
    assert status == FactVerificationStatus.CONFLICTING
    assert quality == EvidenceQuality.UNCONFIRMED
    assert conf == 0.0
    assert "Quarantined" in expl
