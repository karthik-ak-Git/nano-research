"""Generates evaluation_report.json strictly calculated from actual database records and durable run logs.

No hardcoded runtimes, inferred success rates, or fabricated metrics are permitted.
Any metric that cannot be directly measured from records or logs is reported as unavailable.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import func

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_agent.database import get_db_session
from company_agent.models import (
    Company,
    Fact,
    EvidenceSource,
    FactEvidenceModel,
    ChangeEvent,
    RequestUsage,
    ModelUsage,
    CrawlRun,
)
from company_agent.config import settings
from company_agent.identity import validate_organisation_number


def _inspect_batch_results(file_path: Path, run_logs: list, mode_filter: str) -> dict:
    """Calculates success and failure counts from actual profile records in output JSON,

    and cross-references measured runtimes and request counts from durable run logs.
    """
    if not file_path.exists():
        return {
            "status": "unavailable (results file not found)",
            "results_file": file_path.as_posix(),
        }

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "status": f"error reading JSON: {e}",
            "results_file": file_path.as_posix(),
        }

    if not isinstance(data, list):
        return {
            "status": "invalid format (expected list of profiles)",
            "results_file": file_path.as_posix(),
        }

    evaluated_count = len(data)
    success_count = 0
    failed_count = 0

    for item in data:
        if not isinstance(item, dict):
            failed_count += 1
            continue

        org_nr = item.get("organisation_number")
        is_valid, _ = validate_organisation_number(str(org_nr)) if org_nr else (False, "")
        has_name = bool(item.get("name") and str(item.get("name")).strip())
        has_facts = bool(item.get("facts") and len(item.get("facts", {})) > 0)

        if is_valid and has_name and has_facts:
            success_count += 1
        else:
            failed_count += 1

    success_rate_pct = round(success_count / evaluated_count * 100.0, 2) if evaluated_count > 0 else 0.0

    # Cross-reference with durable run logs
    matching_log = None
    for entry in reversed(run_logs):
        if entry.get("mode") == mode_filter or file_path.name in entry.get("output_file", ""):
            matching_log = entry
            break

    if matching_log:
        runtime_sec = matching_log.get("duration_seconds")
        req_usage = matching_log.get("request_usage", {})
        model_usage = matching_log.get("model_usage", {})
        started_at = matching_log.get("started_at")
        completed_at = matching_log.get("completed_at")
        run_id = matching_log.get("run_id")
        total_requests = req_usage.get("total_outbound_requests")
        reg_requests = req_usage.get("registry_requests")
        browser_requests = req_usage.get("browser_requests")
        retry_count = req_usage.get("retry_count")
        model_calls = model_usage.get("model_calls")
        input_tokens = model_usage.get("input_tokens")
        output_tokens = model_usage.get("output_tokens")
        est_cost_usd = model_usage.get("estimated_cost_usd")
        meas_cost_usd = model_usage.get("measured_cost_usd")
        total_cost_usd = model_usage.get("total_cost_usd")
    else:
        runtime_sec = "unavailable (unmeasured; run log entry not found)"
        total_requests = "unavailable (unmeasured; run log entry not found)"
        reg_requests = "unavailable (unmeasured)"
        browser_requests = "unavailable (unmeasured)"
        retry_count = "unavailable (unmeasured)"
        model_calls = "unavailable (unmeasured)"
        input_tokens = "unavailable (unmeasured)"
        output_tokens = "unavailable (unmeasured)"
        est_cost_usd = "unavailable (unmeasured)"
        meas_cost_usd = "unavailable (unmeasured)"
        total_cost_usd = "unavailable (unmeasured)"
        started_at = "unavailable"
        completed_at = "unavailable"
        run_id = "unavailable"

    repo_root = Path(__file__).resolve().parent.parent
    rel_path = file_path.relative_to(repo_root).as_posix() if file_path.is_relative_to(repo_root) else file_path.as_posix()

    return {
        "results_file": rel_path,
        "run_id": run_id,
        "mode": mode_filter,
        "evaluated_companies": evaluated_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_rate_pct": success_rate_pct,
        "started_at": started_at,
        "completed_at": completed_at,
        "runtime_seconds": runtime_sec,
        "request_usage": {
            "total_outbound_requests": total_requests,
            "registry_requests": reg_requests,
            "browser_requests": browser_requests,
            "retry_count": retry_count,
        },
        "model_usage": {
            "model_calls": model_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": est_cost_usd,
            "measured_cost_usd": meas_cost_usd,
            "total_cost_usd": total_cost_usd,
        },
    }


def compute_metrics() -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Load durable run logs if present
    run_logs_path = reports_dir / "run_logs.json"
    run_logs = []
    if run_logs_path.exists():
        try:
            parsed = json.loads(run_logs_path.read_text(encoding="utf-8"))
            if isinstance(parsed, list):
                run_logs = parsed
        except Exception:
            pass

    with get_db_session() as session:
        companies = session.query(Company).all()
        total_companies = len(companies)

        # Mod11 validation dynamically calculated across all actual database identifiers
        mod11_valid_count = 0
        mod11_invalid_count = 0
        for c in companies:
            is_valid, _ = validate_organisation_number(c.organisation_number)
            if is_valid:
                mod11_valid_count += 1
            else:
                mod11_invalid_count += 1
        mod11_valid_pct = round(mod11_valid_count / total_companies * 100.0, 2) if total_companies > 0 else 0.0

        # Profile freshness calculated using stored timestamps and configured TTLs
        now = datetime.now(timezone.utc)
        identity_ttl = timedelta(days=settings.IDENTITY_FRESHNESS_DAYS)
        fresh_profiles_count = 0
        stale_profiles_count = 0
        for c in companies:
            ts = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=timezone.utc)
            if (now - ts) <= identity_ttl:
                fresh_profiles_count += 1
            else:
                stale_profiles_count += 1
        freshness_rate_pct = round(fresh_profiles_count / total_companies * 100.0, 2) if total_companies > 0 else 0.0

        # Facts metrics
        total_facts = session.query(Fact).count()
        current_facts = session.query(Fact).filter_by(is_current=True).count()
        historical_facts = total_facts - current_facts
        facts_per_company = round(total_facts / total_companies, 2) if total_companies > 0 else 0.0

        # Evidence records and verification
        total_evidence = session.query(FactEvidenceModel).count()
        verified_evidence = session.query(FactEvidenceModel).filter_by(verification_status="VERIFIED").count()
        verified_evidence_rate = round((verified_evidence / total_evidence * 100.0), 2) if total_evidence > 0 else 0.0

        # Facts with evidence
        facts_with_ev = (
            session.query(Fact.id)
            .join(FactEvidenceModel, Fact.id == FactEvidenceModel.fact_id)
            .distinct()
            .count()
        )
        evidence_backed_pct = round((facts_with_ev / total_facts * 100.0), 2) if total_facts > 0 else 0.0

        # Identity mismatches measured
        mismatches = session.query(FactEvidenceModel).filter_by(identity_match="MISMATCH").count()
        mismatch_rate = round((mismatches / total_evidence * 100.0), 2) if total_evidence > 0 else 0.0

        # Source URLs
        total_sources = session.query(EvidenceSource).count()
        valid_urls = session.query(EvidenceSource).filter(
            EvidenceSource.url.isnot(None), EvidenceSource.url != ""
        ).count()
        source_url_avail = round((valid_urls / total_sources * 100.0), 2) if total_sources > 0 else 0.0

        # Changes recorded
        total_changes = session.query(ChangeEvent).count()

        # Cumulative Outbound requests & Model usage
        total_requests = (
            session.query(func.count(RequestUsage.id))
            .filter(~RequestUsage.run_id.like("test%"))
            .scalar()
            or 0
        )
        reg_requests = (
            session.query(func.count(RequestUsage.id))
            .filter(~RequestUsage.run_id.like("test%"), RequestUsage.provider.like("%registry%"))
            .scalar()
            or 0
        )
        browser_requests = (
            session.query(func.count(RequestUsage.id))
            .filter(~RequestUsage.run_id.like("test%"), ~RequestUsage.provider.like("%registry%"))
            .scalar()
            or 0
        )
        retry_count = (
            session.query(func.sum(RequestUsage.retries))
            .filter(~RequestUsage.run_id.like("test%"))
            .scalar()
            or 0
        )
        gemini_calls = (
            session.query(func.count(ModelUsage.id))
            .filter(~ModelUsage.run_id.like("test%"))
            .scalar()
            or 0
        )
        input_tokens = (
            session.query(func.sum(ModelUsage.input_tokens))
            .filter(~ModelUsage.run_id.like("test%"))
            .scalar()
            or 0
        )
        output_tokens = (
            session.query(func.sum(ModelUsage.output_tokens))
            .filter(~ModelUsage.run_id.like("test%"))
            .scalar()
            or 0
        )
        estimated_gemini_cost = float(
            session.query(func.sum(ModelUsage.estimated_cost))
            .filter(~ModelUsage.run_id.like("test%"))
            .scalar()
            or 0.0
        )
        measured_cost = float(
            session.query(func.sum(ModelUsage.measured_cost))
            .filter(~ModelUsage.run_id.like("test%"))
            .scalar()
            or 0.0
        )
        total_cost = estimated_gemini_cost + measured_cost

    # Batch evaluation inspection (cached and live)
    cached_metrics = _inspect_batch_results(
        reports_dir / "batch_100_cached.json",
        run_logs,
        "verified_database_cache",
    )
    live_metrics = _inspect_batch_results(
        reports_dir / "batch_100_live.json",
        run_logs,
        "live_provider_refresh",
    )

    report = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "database_records": {
            "distinct_valid_companies": total_companies,
            "mod11_valid_checksum_count": mod11_valid_count,
            "mod11_invalid_checksum_count": mod11_invalid_count,
            "mod11_valid_checksum_pct": mod11_valid_pct,
            "total_facts": total_facts,
            "current_active_facts": current_facts,
            "historical_archived_facts": historical_facts,
            "facts_per_company_average": facts_per_company,
            "total_evidence_records": total_evidence,
            "verified_evidence_records": verified_evidence,
            "verified_evidence_rate_pct": verified_evidence_rate,
            "evidence_backed_fact_percentage": evidence_backed_pct,
            "identity_mismatch_count": mismatches,
            "identity_mismatch_rate_pct": mismatch_rate,
            "total_sources": total_sources,
            "sources_with_valid_url": valid_urls,
            "source_url_availability_pct": source_url_avail,
            "total_historical_changes_recorded": total_changes,
            "freshness": {
                "fresh_profiles_count": fresh_profiles_count,
                "stale_profiles_count": stale_profiles_count,
                "freshness_rate_pct": freshness_rate_pct,
                "configured_identity_ttl_days": settings.IDENTITY_FRESHNESS_DAYS,
                "configured_dynamic_ttl_days": settings.DYNAMIC_FRESHNESS_DAYS,
            },
            "unsupported_value_rejection": {
                "measured": False,
                "status": "unavailable (unmeasured)",
                "enforcement_mechanism": "Enforced by ingestion logic: ungrounded candidate facts are quarantined prior to database storage; rejection counter is not stored in DB tables.",
            },
        },
        "cumulative_resource_and_cost_accounting": {
            "total_outbound_requests": total_requests,
            "registry_requests": reg_requests,
            "browser_requests": browser_requests,
            "retry_count": retry_count,
            "request_budget_ceiling": settings.MAX_DAILY_REQUESTS,
            "request_budget_utilization_pct": round(total_requests / settings.MAX_DAILY_REQUESTS * 100.0, 2),
            "gemini_model_calls": gemini_calls,
            "gemini_input_tokens": input_tokens,
            "gemini_output_tokens": output_tokens,
            "estimated_gemini_cost_usd": round(estimated_gemini_cost, 5),
            "measured_api_cost_usd": round(measured_cost, 5),
            "total_evaluated_cost_usd": round(total_cost, 5),
            "hard_cost_limit_usd": settings.MAX_DAILY_COST_USD,
            "cost_budget_headroom_usd": round(settings.MAX_DAILY_COST_USD - total_cost, 5),
        },
        "evaluations": {
            "cached_100_company_run": cached_metrics,
            "live_100_company_run": live_metrics,
        },
    }

    report_path = reports_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {report_path}")
    return report


if __name__ == "__main__":
    rep = compute_metrics()
    print(json.dumps(rep, indent=2))
