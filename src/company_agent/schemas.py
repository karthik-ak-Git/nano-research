"""Versioned JSON schemas and Pydantic models for company profiles and fact provenance."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class FactVerificationStatus(str, Enum):
    """Verification classification for an extracted fact."""
    VERIFIED = "VERIFIED"
    SECONDARY_SUPPORTED = "SECONDARY_SUPPORTED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"
    QUARANTINED = "QUARANTINED"


class EvidenceQuality(str, Enum):
    """Quality classification of the evidence source."""
    REGISTRY_OFFICIAL = "REGISTRY_OFFICIAL"
    DIRECT_OFFICIAL = "DIRECT_OFFICIAL"
    SECONDARY_PUBLIC = "SECONDARY_PUBLIC"
    UNCONFIRMED = "UNCONFIRMED"


class FinancialPeriod(BaseModel):
    """Directly evidenced financial accounting period and figures."""
    from_date: Optional[str] = Field(default=None, description="Start date of period (YYYY-MM-DD)")
    to_date: Optional[str] = Field(default=None, description="End date of period (YYYY-MM-DD)")
    year: Optional[int] = Field(default=None, description="Fiscal year")
    currency: str = Field(default="NOK", description="ISO currency code (e.g. NOK, USD, EUR)")
    revenue: Optional[float] = Field(default=None, description="Operating revenue / sales")
    operating_profit: Optional[float] = Field(default=None, description="Operating profit / driftsresultat")
    total_assets: Optional[float] = Field(default=None, description="Total balance assets / sum eiendeler")
    accounting_standard: Optional[str] = Field(default=None, description="e.g. IFRS, NGAAP, Forenklet IFRS")


class FactEvidence(BaseModel):
    """Detailed provenance and evidence record attached to each individual company fact."""
    field_name: str = Field(description="Name of the profile field this evidence supports")
    normalized_value: Any = Field(description="Normalized typed value")
    raw_value: Optional[str] = Field(default=None, description="Original source string representation")
    source_url: str = Field(description="Exact source URL where the fact was obtained")
    source_domain: str = Field(description="Source organization or domain name")
    excerpt: str = Field(description="Supporting text passage or structured JSON path")
    publication_date: Optional[str] = Field(
        default=None,
        description="Source publication date (YYYY-MM-DD), null if unknown (never fabricated)",
    )
    financial_period: Optional[FinancialPeriod] = Field(
        default=None,
        description="Applicable financial period details if this is a financial fact",
    )
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of retrieval",
    )
    identity_verification_result: str = Field(
        default="VERIFIED_MATCH",
        description="Entity resolution outcome (e.g. VERIFIED_MATCH, SECONDARY_SUPPORTED)",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )
    quality_classification: EvidenceQuality = Field(
        default=EvidenceQuality.REGISTRY_OFFICIAL,
        description="Evidence quality classification",
    )
    verification_status: FactVerificationStatus = Field(
        default=FactVerificationStatus.VERIFIED,
        description="Final verification status",
    )
    last_seen_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last UTC timestamp when this fact was verified in sources",
    )


class CompanyProfile(BaseModel):
    """Complete, strict, versioned profile of a Norwegian corporate entity."""
    schema_version: str = Field(default="1.0.0", description="Profile schema version")
    organisation_number: str = Field(
        description="Official 9-digit Norwegian organisation number (Primary Identity Key)"
    )
    name: str = Field(description="Registered legal business name")
    legal_form: Optional[str] = Field(default=None, description="Corporate legal form (e.g. AS, ASA, ENK)")
    status: str = Field(default="Active", description="Registration status (Active, In Liquidation, Bankrupt)")
    address: Optional[str] = Field(default=None, description="Registered business street address")
    postal_code: Optional[str] = Field(default=None, description="Postal code")
    municipality: Optional[str] = Field(default=None, description="Municipality name")
    country: str = Field(default="Norway", description="Registered country")
    industry_code: Optional[str] = Field(default=None, description="NACE industry code (e.g. 06.100)")
    industry_description: Optional[str] = Field(default=None, description="NACE industry description")
    registration_date: Optional[str] = Field(
        default=None,
        description="Date registered in Enhetsregisteret (YYYY-MM-DD)",
    )
    incorporation_date: Optional[str] = Field(
        default=None,
        description="Date of incorporation/foundation (stiftelsesdato) (YYYY-MM-DD)",
    )
    official_website: Optional[str] = Field(default=None, description="Official company website URL")
    employee_count: Optional[int] = Field(default=None, description="Registered employee count")
    employee_count_date: Optional[str] = Field(default=None, description="Date of employee count reporting")
    
    # Financial statements (Directly evidenced only)
    financial_period: Optional[str] = Field(default=None, description="Most recent reported fiscal period")
    currency: Optional[str] = Field(default=None, description="Currency for financial figures (NOK, USD, EUR)")
    revenue: Optional[float] = Field(default=None, description="Annual operating revenue / sales")
    operating_profit: Optional[float] = Field(default=None, description="Operating profit / loss")
    total_assets: Optional[float] = Field(default=None, description="Total balance sheet assets")
    
    # Activities & descriptions
    business_activities: List[str] = Field(default_factory=list, description="Verified business activity statements")
    description: Optional[str] = Field(default=None, description="Company overview / summary")

    # Provenance and evidence at fact-level
    facts: Dict[str, FactEvidence] = Field(
        default_factory=dict,
        description="Mapping from field name to its supporting evidence record",
    )
    provenance_history: List[FactEvidence] = Field(
        default_factory=list,
        description="Historical or superseded evidence records preserved for audit",
    )
    explanations: List[str] = Field(
        default_factory=list,
        description="Human-understandable explanations of profile state and recent updates",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Data-quality warnings, unresolved conflicts, or quarantined items",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Profile creation timestamp UTC",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Profile last update timestamp UTC",
    )

    @field_validator("organisation_number")
    @classmethod
    def validate_org_nr(cls, v: str) -> str:
        from company_agent.identity import assert_valid_organisation_number
        return assert_valid_organisation_number(v)


class BatchItemResult(BaseModel):
    """Result for a single company in a batch execution."""
    organisation_number: str
    name: Optional[str] = None
    success: bool
    status: str
    facts_count: int = 0
    warnings: List[str] = Field(default_factory=list)
    explanations: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0


class BatchRunSummary(BaseModel):
    """Aggregate summary of a batch evaluation run."""
    run_id: str
    started_at: datetime
    completed_at: datetime
    total_companies: int
    successful_companies: int
    failed_companies: int
    total_facts_extracted: int
    outbound_requests: int
    total_cost_usd: float
    elapsed_seconds: float
    items: List[BatchItemResult] = Field(default_factory=list)


class CostReport(BaseModel):
    """Cost and resource utilization audit report."""
    run_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    browser_requests: int = 0
    search_and_fetch_requests: int = 0
    registry_requests: int = 0
    total_outbound_requests: int = 0
    gemini_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate_pct: float = 0.0
    estimated_gemini_cost_usd: float = 0.0
    measured_api_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    cost_per_company_usd: float = 0.0
    errors_and_retries: int = 0
    budget_exhausted: bool = False
