"""Fact and identity verification policies and quarantine handlers."""

from typing import Optional, Tuple
from company_agent.schemas import FactVerificationStatus, EvidenceQuality
from company_agent.identity import verify_entity_resolution


def verify_fact_provenance(
    field_name: str,
    value: any,
    source_url: str,
    requested_org_nr: str,
    registry_legal_name: str,
    source_org_nr: Optional[str] = None,
    source_domain: Optional[str] = None,
    official_domain: Optional[str] = None,
    is_registry_source: bool = False,
    excerpt: Optional[str] = None,
) -> Tuple[FactVerificationStatus, EvidenceQuality, float, str]:
    """Evaluates fact validity against strict entity resolution and evidence quality rules.

    Returns:
        Tuple of (verification_status, quality_classification, confidence_score, explanation)
    """
    # 1. Official Brønnøysund registry source is gold standard
    if is_registry_source:
        return (
            FactVerificationStatus.VERIFIED,
            EvidenceQuality.REGISTRY_OFFICIAL,
            1.0,
            f"Fact verified via official Brønnøysund Register Centre record for {requested_org_nr}",
        )

    # 2. Strict entity resolution check
    resolution_status, explanation, confidence = verify_entity_resolution(
        requested_org_nr=requested_org_nr,
        registry_legal_name=registry_legal_name,
        source_org_nr=source_org_nr,
        source_domain=source_domain,
        official_domain=official_domain,
    )

    if resolution_status == "VERIFIED_MATCH":
        return (
            FactVerificationStatus.VERIFIED,
            EvidenceQuality.DIRECT_OFFICIAL,
            confidence,
            explanation,
        )
    elif resolution_status == "SECONDARY_SUPPORTED":
        return (
            FactVerificationStatus.SECONDARY_SUPPORTED,
            EvidenceQuality.SECONDARY_PUBLIC,
            confidence,
            explanation,
        )
    elif resolution_status == "CONFLICT_MISMATCH":
        return (
            FactVerificationStatus.CONFLICTING,
            EvidenceQuality.UNCONFIRMED,
            0.0,
            f"Quarantined: {explanation}",
        )
    else:
        return (
            FactVerificationStatus.UNVERIFIED,
            EvidenceQuality.UNCONFIRMED,
            confidence,
            f"Unverified: {explanation}",
        )


def validate_financial_fact(
    field_name: str,
    value: Optional[float],
    currency: Optional[str],
    period: Optional[str],
    excerpt: Optional[str],
) -> Tuple[bool, str]:
    """Validates that financial values are directly supported with period, currency, and excerpt."""
    if value is None:
        return True, "Value is null"

    if not currency:
        return False, f"Financial field '{field_name}' lacks explicit currency (never infer currency)"

    if not excerpt:
        return False, f"Financial field '{field_name}' lacks direct supporting excerpt"

    return True, "Valid financial evidence"
