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
