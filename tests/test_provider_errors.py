"""Tests for provider error handling, timeouts, retries, and missing credentials."""

import pytest
from company_agent.providers.gemini import gemini_client
from company_agent.providers.tinyfish import TinyFishProvider
from company_agent.providers.browser_use import BrowserUseProvider
from company_agent.providers.registry import registry_client


def test_malformed_gemini_json_handling():
    # Should safely clean markdown codeblocks or extract inner JSON
    raw_markdown = '```json\n{"website": "https://example.com", "employee_count": 50}\n```'
    parsed = gemini_client._clean_and_parse_json(raw_markdown)
    assert parsed.get("website") == "https://example.com"
    assert parsed.get("employee_count") == 50

    # Totally broken text should return empty dict, never raise
    broken = "This is not json at all."
    parsed_broken = gemini_client._clean_and_parse_json(broken)
    assert parsed_broken == {}


def test_tinyfish_missing_credentials_graceful_handling():
    # When api key is missing, is_available must be False and error returned cleanly
    tf = TinyFishProvider(api_key=None)
    assert tf.is_available() is False


@pytest.mark.asyncio
async def test_tinyfish_navigate_without_credentials():
    tf = TinyFishProvider(api_key=None)
    res = await tf.navigate_and_extract("https://example.com", "test goal")
    assert res.error is not None
    assert "TINYFISH_API_KEY not configured" in res.error


def test_browser_use_provider_availability():
    bu = BrowserUseProvider()
    assert bu.name == "browser_use"
    assert bu.is_available() is True


def test_registry_404_not_retried_indefinitely():
    # Query a non-existent 9-digit org nr (with valid checksum)
    # 999999999 is invalid checksum; let's use a valid checksum that doesn't exist
    from company_agent.identity import calculate_mod11_control_digit
    ctrl = calculate_mod11_control_digit("99999999")
    test_org = f"99999999{ctrl}" if ctrl is not None else "999999981"
    
    # 404 should return immediately, not loop forever
    res = registry_client.get_enhet(test_org)
    assert res is None
