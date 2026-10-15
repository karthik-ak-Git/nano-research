"""Token pricing calculations, cost estimations, and audit report generation."""

from typing import Dict, Any, Optional
from company_agent.budgets import budget_manager
from company_agent.schemas import CostReport


# Pricing per 1,000,000 tokens (USD)
# Source: Google AI Studio Gemini API pricing
GEMINI_PRICING: Dict[str, Dict[str, float]] = {
    "gemini-2.5-flash-lite": {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
    },
    "gemini-2.0-flash-lite": {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
    },
    "gemini-2.0-flash": {
        "input_per_million": 0.10,
        "output_per_million": 0.40,
    },
    "gemini-1.5-flash": {
        "input_per_million": 0.075,
        "output_per_million": 0.30,
    },
}

DEFAULT_PRICING = {
    "input_per_million": 0.10,
    "output_per_million": 0.40,
}


def calculate_gemini_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculates estimated Gemini API cost in USD based on input and output tokens."""
    model_key = model_name.lower().replace("models/", "")
    pricing = GEMINI_PRICING.get(model_key, DEFAULT_PRICING)
    
    in_cost = (input_tokens / 1_000_000.0) * pricing["input_per_million"]
    out_cost = (output_tokens / 1_000_000.0) * pricing["output_per_million"]
    return in_cost + out_cost


def generate_cost_report(companies_processed: int = 1) -> CostReport:
    """Generates a detailed CostReport from the central budget manager or database audit logs."""
    metrics = budget_manager.get_metrics()
    total_companies = max(1, companies_processed)
    
    req_count = metrics["request_count"]
    retry_count = metrics["retry_count"]
    gemini_calls = metrics["gemini_call_count"]
    in_tokens = metrics["input_tokens"]
    out_tokens = metrics["output_tokens"]
    est_cost = metrics["estimated_cost_usd"]
    meas_cost = metrics["measured_cost_usd"]

    # If in-memory is zero (fresh CLI process), aggregate from database audit logs
    if req_count == 0 and gemini_calls == 0:
        try:
            from company_agent.database import get_db_session
            from company_agent.models import RequestUsage, ModelUsage
            from sqlalchemy import func
            with get_db_session() as session:
                req_count = session.query(func.count(RequestUsage.id)).scalar() or 0
                retry_count = session.query(func.sum(RequestUsage.retries)).scalar() or 0
                gemini_calls = session.query(func.count(ModelUsage.id)).scalar() or 0
                in_tokens = session.query(func.sum(ModelUsage.input_tokens)).scalar() or 0
                out_tokens = session.query(func.sum(ModelUsage.output_tokens)).scalar() or 0
                est_cost = session.query(func.sum(ModelUsage.estimated_cost)).scalar() or 0.0
                meas_cost = session.query(func.sum(ModelUsage.measured_cost)).scalar() or 0.0
        except Exception:
            pass

    total_cost = est_cost + meas_cost
    cost_per_company = total_cost / total_companies

    return CostReport(
        run_id=metrics["run_id"],
        browser_requests=0,
        search_and_fetch_requests=0,
        registry_requests=req_count,
        total_outbound_requests=req_count,
        gemini_calls=gemini_calls,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cache_hits=metrics["cache_hits"],
        cache_misses=metrics["cache_misses"],
        cache_hit_rate_pct=metrics["cache_hit_rate_pct"],
        estimated_gemini_cost_usd=round(est_cost, 5),
        measured_api_cost_usd=round(meas_cost, 5),
        total_cost_usd=round(total_cost, 5),
        cost_per_company_usd=round(cost_per_company, 5),
        errors_and_retries=retry_count,
        budget_exhausted=metrics["is_stopped"],
    )
