"""Tests for incremental freshness and TTL expiration."""

from datetime import datetime, timezone, timedelta
from company_agent.freshness import is_fact_fresh, is_profile_fresh


def test_fact_freshness_stable_vs_dynamic():
    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=10)

    # 'name' is a stable identity field (30 days TTL) -> 10 days ago is still FRESH
    assert is_fact_fresh("name", ten_days_ago, identity_ttl_days=30, dynamic_ttl_days=7) is True

    # 'employee_count' is a dynamic field (7 days TTL) -> 10 days ago is EXPIRED
    assert is_fact_fresh("employee_count", ten_days_ago, identity_ttl_days=30, dynamic_ttl_days=7) is False


def test_profile_freshness():
    now = datetime.now(timezone.utc)
    assert is_profile_fresh(now - timedelta(days=2), max_age_days=7) is True
    assert is_profile_fresh(now - timedelta(days=10), max_age_days=7) is False
    assert is_profile_fresh(None) is False
