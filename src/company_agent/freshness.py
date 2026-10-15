"""Profile freshness evaluation and incremental refresh intervals."""

from datetime import datetime, timezone, timedelta
from typing import Optional, Set
from company_agent.config import settings

# Fields considered stable corporate identity (longer TTL)
STABLE_IDENTITY_FIELDS: Set[str] = {
    "name",
    "legal_form",
    "registration_date",
    "incorporation_date",
    "industry_code",
    "industry_description",
    "country",
}

# Fields considered dynamic (shorter TTL)
DYNAMIC_FIELDS: Set[str] = {
    "status",
    "address",
    "postal_code",
    "municipality",
    "official_website",
    "employee_count",
    "revenue",
    "operating_profit",
    "total_assets",
    "financial_period",
    "currency",
    "description",
}


def is_fact_fresh(
    field_name: str,
    last_updated: Optional[datetime],
    identity_ttl_days: Optional[int] = None,
    dynamic_ttl_days: Optional[int] = None,
) -> bool:
    """Evaluates whether an individual fact remains within its validity TTL."""
    if last_updated is None:
        return False

    now = datetime.now(timezone.utc)
    # Ensure timezone awareness
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)

    id_ttl = timedelta(days=identity_ttl_days or settings.IDENTITY_FRESHNESS_DAYS)
    dyn_ttl = timedelta(days=dynamic_ttl_days or settings.DYNAMIC_FRESHNESS_DAYS)

    if field_name in STABLE_IDENTITY_FIELDS:
        return (now - last_updated) < id_ttl
    else:
        return (now - last_updated) < dyn_ttl


def is_profile_fresh(
    profile_updated_at: Optional[datetime],
    max_age_days: Optional[int] = None,
) -> bool:
    """Evaluates whether an entire company profile is fresh enough to skip re-crawling."""
    if profile_updated_at is None:
        return False

    now = datetime.now(timezone.utc)
    if profile_updated_at.tzinfo is None:
        profile_updated_at = profile_updated_at.replace(tzinfo=timezone.utc)

    ttl = timedelta(days=max_age_days or settings.DYNAMIC_FRESHNESS_DAYS)
    return (now - profile_updated_at) < ttl
