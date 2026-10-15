"""Tests for the Resource Budget Manager and hard execution limits."""

import pytest
import time
from company_agent.budgets import ResourceBudgetManager, BudgetExceededError, budget_manager
from company_agent.costs import calculate_gemini_cost, generate_cost_report
from company_agent.config import settings


@pytest.fixture(autouse=True)
def reset_budget_state():
    budget_manager.reset()
    budget_manager.max_requests = settings.MAX_DAILY_REQUESTS
    budget_manager.internal_cost_ceiling = settings.INTERNAL_COST_CEILING_USD
    yield
    budget_manager.reset()
    budget_manager.max_requests = settings.MAX_DAILY_REQUESTS
    budget_manager.internal_cost_ceiling = settings.INTERNAL_COST_CEILING_USD


def test_budget_manager_request_ceiling():
    mgr = ResourceBudgetManager(max_requests=5, max_cost_usd=10.0, internal_cost_ceiling_usd=8.0)
    mgr.reset()
    mgr.max_requests = 5

    # Record 4 requests -> within budget
    for i in range(4):
        mgr.check_budget_available()
        mgr.record_request("test_provider", f"https://example.com/{i}", status_code=200)

    assert mgr.request_count == 4

    # Record 5th request
    mgr.record_request("test_provider", "https://example.com/5", status_code=200)

    # 6th check -> should raise BudgetExceededError
    with pytest.raises(BudgetExceededError) as exc_info:
        mgr.check_budget_available()

    assert "Request budget exhausted" in str(exc_info.value)


def test_budget_manager_cost_ceiling():
    mgr = ResourceBudgetManager(max_requests=100, max_cost_usd=10.0, internal_cost_ceiling_usd=8.0)
    mgr.reset()
    mgr.internal_cost_ceiling = 8.0

    # Record spend below ceiling
    mgr.record_gemini_usage("gemini-2.5-flash-lite", 1000, 200, estimated_cost=4.0)
    mgr.check_budget_available()

    # Record spend exceeding safety ceiling of $8.00
    mgr.record_gemini_usage("gemini-2.5-flash-lite", 1000, 200, estimated_cost=4.5)

    with pytest.raises(BudgetExceededError) as exc_info:
        mgr.check_budget_available()

    assert "Cost budget safety ceiling reached" in str(exc_info.value)


def test_calculate_gemini_pricing():
    # 1M input tokens at $0.075 + 1M output tokens at $0.30 = $0.375
    cost = calculate_gemini_cost("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert abs(cost - 0.375) < 1e-4

    # 10,000 input + 1,000 output
    small_cost = calculate_gemini_cost("gemini-2.5-flash-lite", 10_000, 1_000)
    assert small_cost < 0.01


def test_cost_report_generation():
    mgr = ResourceBudgetManager()
    mgr.reset()
    mgr.record_request("test", "https://example.com", status_code=200)
    mgr.record_gemini_usage("gemini-2.5-flash-lite", 500, 100, estimated_cost=0.0001)

    report = generate_cost_report(companies_processed=1)
    assert report.total_outbound_requests >= 1
    assert report.gemini_calls >= 1
    assert report.total_cost_usd > 0.0
