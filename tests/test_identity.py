"""Tests for Norwegian organisation number validation and entity resolution."""

import pytest
from company_agent.identity import (
    normalize_organisation_number,
    calculate_mod11_control_digit,
    validate_organisation_number,
    assert_valid_organisation_number,
    InvalidOrganisationNumberError,
    extract_organisation_numbers,
    normalize_company_name,
    verify_entity_resolution,
)


def test_normalize_organisation_number():
    assert normalize_organisation_number("923 609 016") == "923609016"
    assert normalize_organisation_number(" 923-609-016 ") == "923609016"
    assert normalize_organisation_number("923.609.016") == "923609016"
    assert normalize_organisation_number(923609016) == "923609016"

    with pytest.raises(InvalidOrganisationNumberError):
        normalize_organisation_number(None)


def test_mod11_checksum_calculation():
    # Equinor: first 8 digits '92360901' -> control digit should be 6
    assert calculate_mod11_control_digit("92360901") == 6
    # Telenor: '97663340' -> control digit 7
    assert calculate_mod11_control_digit("97663340") == 7
    # DNB: '98485100' -> control digit 6
    assert calculate_mod11_control_digit("98485100") == 6


def test_valid_organisation_numbers():
    valid_orgs = [
        "923609016",  # Equinor ASA
        "976633407",  # Telenor ASA
        "984851006",  # DNB Bank ASA
        "943752907",  # Kongsberg Gruppen ASA
        "910747711",  # Orkla ASA
    ]
    for org in valid_orgs:
        is_valid, clean = validate_organisation_number(org)
        assert is_valid is True
        assert clean == org
        assert assert_valid_organisation_number(org) == org


def test_invalid_organisation_numbers():
    # Wrong lengths
    assert validate_organisation_number("12345678")[0] is False
    assert validate_organisation_number("1234567890")[0] is False

    # Non-numeric
    assert validate_organisation_number("92360901A")[0] is False

    # Corrupted checksum
    # 923609016 is valid -> 923609017 has wrong control digit
    is_valid, msg = validate_organisation_number("923609017")
    assert is_valid is False
    assert "Checksum mismatch" in msg

    with pytest.raises(InvalidOrganisationNumberError):
        assert_valid_organisation_number("923609017")


def test_extract_organisation_numbers():
    sample_text = (
        "Welcome to Equinor ASA. Org.nr: 923 609 016. In partnership with "
        "Telenor (976-633-407) and an invalid sequence 123456789."
    )
    found = extract_organisation_numbers(sample_text)
    assert "923609016" in found
    assert "976633407" in found
    assert "123456789" not in found  # Fails checksum


def test_company_name_collision_and_never_merge_policy():
    """Verify that similar or identical company names with different org numbers are NEVER merged."""
    name_a = "Nordic Solutions AS"
    name_b = "Nordic Solutions ASA"
    org_a = "923609016"
    org_b = "976633407"

    # Even if names look similar, different org number must report CONFLICT
    status, expl, conf = verify_entity_resolution(
        requested_org_nr=org_a,
        registry_legal_name=name_a,
        source_org_nr=org_b,
        source_name=name_b,
    )
    assert status == "CONFLICT_MISMATCH"
    assert conf == 0.0
    assert "Conflict" in expl
