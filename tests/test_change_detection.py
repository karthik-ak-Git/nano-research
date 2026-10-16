"""Tests for material change detection and history preservation."""

from company_agent.change_detection import is_material_difference, detect_field_change


def test_is_material_difference():
    # Null cases
    assert is_material_difference(None, None) is False
    assert is_material_difference(None, "Active") is True
    assert is_material_difference("Active", None) is True

    # Case / whitespace insensitivity
    assert is_material_difference("Active", "active") is False
    assert is_material_difference(" Forusbeen 50 ", "Forusbeen 50") is False

    # Meaningful change
    assert is_material_difference("Active", "In Liquidation") is True
    assert is_material_difference(21000, 21231) is True
    assert is_material_difference(5000000.0, 5000000.0) is False

    # Formatting, newlines, HTML entities, and non-breaking space invariance
    assert is_material_difference("Equinor ASA\nForusbeen 50", "Equinor ASA  Forusbeen 50") is False
    assert is_material_difference("Oil &amp; Gas", "Oil & Gas") is False
    assert is_material_difference("Stavanger\xa0Norway", "Stavanger Norway") is False

    # Navigational boilerplate invariance
    desc1 = "Skip to main content. Equinor is a leading broad international energy company."
    desc2 = "Equinor is a leading broad international energy company"
    assert is_material_difference(desc1, desc2) is False

    # Meaningful description change
    desc_diff = "Equinor is a commercial retail fashion outlet in Oslo."
    assert is_material_difference(desc1, desc_diff) is True

    # List invariance
    assert is_material_difference(["Oil", "Energy"], ["energy", "oil"]) is False
    assert is_material_difference(["Oil", "Energy"], ["Renewables", "Wind"]) is True


def test_detect_field_change_explanation():
    # Employee change
    changed, exp = detect_field_change(
        field_name="employee_count",
        old_value=21000,
        new_value=21231,
        source_name="Brønnøysund Register Centre",
        source_date="2026-10-13",
    )
    assert changed is True
    assert "Registered employee count changed from 21000 to 21231" in exp
    assert "2026-10-13" in exp

    # Address change
    changed, exp = detect_field_change(
        field_name="address",
        old_value="Storgata 1",
        new_value="Karl Johans gate 10",
        source_name="Brønnøysund Register Centre",
    )
    assert changed is True
    assert "relocated from 'Storgata 1' to 'Karl Johans gate 10'" in exp
