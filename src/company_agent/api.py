"""FastAPI web service providing REST endpoints for company intelligence."""

from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Query
from company_agent.identity import validate_organisation_number
from company_agent.pipeline import pipeline
from company_agent.schemas import CompanyProfile, CostReport
from company_agent.database import get_db_session, init_db
from company_agent.repositories import CompanyRepository
from company_agent.models import Company
from company_agent.costs import generate_cost_report

app = FastAPI(
    title="Norwegian Company Intelligence API",
    description="Competition-ready REST API for Norwegian corporate research, verification, and change tracking.",
    version="0.1.0",
)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/health", tags=["System"])
def health_check() -> Dict[str, Any]:
    """Health check endpoint confirming API and database readiness."""
    with get_db_session() as session:
        count = session.query(Company).count()
    return {
        "status": "healthy",
        "database": "connected",
        "companies_stored": count,
    }


@app.get("/companies/{org_nr}", response_model=CompanyProfile, tags=["Companies"])
async def get_company(org_nr: str):
    """Retrieve or research a Norwegian company by organisation number."""
    is_valid, clean_or_err = validate_organisation_number(org_nr)
    if not is_valid:
        raise HTTPException(status_code=400, detail=clean_or_err)

    try:
        profile = await pipeline.execute(clean_or_err, force_refresh=False)
        return profile
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.post("/companies/{org_nr}/refresh", response_model=CompanyProfile, tags=["Companies"])
async def refresh_company(org_nr: str):
    """Force an incremental refresh of a Norwegian company profile."""
    is_valid, clean_or_err = validate_organisation_number(org_nr)
    if not is_valid:
        raise HTTPException(status_code=400, detail=clean_or_err)

    try:
        profile = await pipeline.execute(clean_or_err, force_refresh=True)
        return profile
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline refresh error: {str(e)}")


@app.get("/stats", tags=["Audit"])
def get_stats() -> Dict[str, Any]:
    """Retrieve database profile and fact verification metrics."""
    with get_db_session() as session:
        repo = CompanyRepository(session)
        return repo.get_stats()


@app.get("/cost-report", response_model=CostReport, tags=["Audit"])
def get_costs():
    """Retrieve current outbound request and API cost audit report."""
    with get_db_session() as session:
        count = session.query(Company).count()
    return generate_cost_report(companies_processed=count)
