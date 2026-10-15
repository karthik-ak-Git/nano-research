"""Authoritative Brønnøysund Register Centre (Brreg) client.

Provides lawful, direct, open access to Enhetsregisteret (company registry)
and Regnskapsregisteret (annual financial statements) with IPv4 safety,
budget tracking, and exponential backoff.
"""

import socket
import time
from typing import Optional, Dict, Any, List
import httpx
from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.budgets import budget_manager, BudgetExceededError
from company_agent.identity import assert_valid_organisation_number, validate_organisation_number
from company_agent.cache import cache


def _ensure_ipv4_preferred():
    """Forces getaddrinfo to prefer IPv4 if dual-stack network causes TLS handshake timeout."""
    try:
        orig_getaddrinfo = socket.getaddrinfo

        def ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            try:
                # Attempt IPv4 explicitly first
                return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            except Exception:
                return orig_getaddrinfo(host, port, family, type, proto, flags)

        socket.getaddrinfo = ipv4_first_getaddrinfo
    except Exception as e:
        logger.debug("IPv4 preference patch skipped: %s", e)


_ensure_ipv4_preferred()


class BrregRegistryClient:
    """Client for authoritative Norwegian public company registries."""

    def __init__(self):
        self.enhet_base = settings.BRREG_API_BASE.rstrip("/")
        self.regnskap_base = settings.BRREG_REGNSKAP_BASE.rstrip("/")
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "application/json",
        }
        self.timeout = settings.HTTP_TIMEOUT_SECONDS

    def _get_with_retry(self, url: str, max_retries: Optional[int] = None) -> Optional[httpx.Response]:
        """Performs HTTP GET with budget checking, exponential backoff, and caching."""
        retries = max_retries if max_retries is not None else settings.HTTP_MAX_RETRIES

        # Check budget availability first
        budget_manager.check_budget_available()

        delay = 1.0
        last_error = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                    resp = client.get(url)
                    budget_manager.record_request(
                        provider="brreg_registry",
                        endpoint=url,
                        status_code=resp.status_code,
                        retries=attempt,
                    )

                    if resp.status_code in (200, 404):
                        return resp
                    elif resp.status_code in (429, 500, 502, 503, 504):
                        logger.warning(
                            "Transient HTTP %d from %s (attempt %d/%d). Retrying in %.1fs...",
                            resp.status_code, url, attempt + 1, retries, delay
                        )
                        time.sleep(delay)
                        delay *= 2.0
                    else:
                        logger.error("HTTP error %d for %s", resp.status_code, url)
                        return resp
            except Exception as e:
                last_error = e
                logger.warning(
                    "Network error connecting to %s (attempt %d/%d): %s",
                    url, attempt + 1, retries, e
                )
                time.sleep(delay)
                delay *= 2.0

        logger.error("Failed to fetch %s after %d retries: %s", url, retries, last_error)
        return None

    def get_enhet(self, org_nr: str) -> Optional[Dict[str, Any]]:
        """Retrieves official registration details for an organisation number from Enhetsregisteret."""
        clean_org = assert_valid_organisation_number(org_nr)
        cache_key = f"brreg:enhet:{clean_org}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.enhet_base}/enheter/{clean_org}"
        resp = self._get_with_retry(url)

        if resp is None or resp.status_code == 404:
            return None

        if resp.status_code == 200:
            data = resp.json()
            cache.set(cache_key, data, ttl_seconds=86400 * settings.IDENTITY_FRESHNESS_DAYS)
            return data

        return None

    def get_regnskap(self, org_nr: str) -> List[Dict[str, Any]]:
        """Retrieves verified annual accounts from Regnskapsregisteret."""
        clean_org = assert_valid_organisation_number(org_nr)
        cache_key = f"brreg:regnskap:{clean_org}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.regnskap_base}/regnskap/{clean_org}"
        resp = self._get_with_retry(url)

        if resp is None or resp.status_code == 404:
            return []

        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, list):
                    cache.set(cache_key, data, ttl_seconds=86400 * settings.DYNAMIC_FRESHNESS_DAYS)
                    return data
            except Exception as e:
                logger.debug("Failed parsing regnskap JSON for %s: %s", clean_org, e)

        return []

    def fetch_registered_org_numbers(self, count: int = 1000) -> List[str]:
        """Fetches distinct, valid registered organisation numbers from the live open registry.

        Used to discover real Norwegian companies for seeding the required 1,000+ profiles.
        """
        results: List[str] = []
        page = 0
        page_size = min(100, count)

        while len(results) < count:
            url = f"{self.enhet_base}/enheter?size={page_size}&page={page}"
            resp = self._get_with_retry(url)
            if not resp or resp.status_code != 200:
                break

            data = resp.json()
            embedded = data.get("_embedded", {})
            enheter = embedded.get("enheter", [])
            if not enheter:
                break

            for enhet in enheter:
                org_nr = enhet.get("organisasjonsnummer")
                if org_nr:
                    is_valid, clean = validate_organisation_number(str(org_nr))
                    if is_valid and clean not in results:
                        results.append(clean)
                        if len(results) >= count:
                            break

            page += 1
            # Respect polite crawling rate
            time.sleep(0.05)

        return results


# Global singleton registry client
registry_client = BrregRegistryClient()
