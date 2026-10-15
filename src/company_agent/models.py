"""SQLAlchemy ORM models supporting versioned company profiles and provenance."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from company_agent.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SchemaVersion(Base):
    """Tracks applied schema migrations and version numbers."""
    __tablename__ = "schema_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    applied_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class Company(Base):
    """Primary company entity keyed by 9-digit Norwegian organisation number."""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organisation_number = Column(String(9), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    status = Column(String(50), default="Active", nullable=False)
    legal_form = Column(String(50), nullable=True)
    website = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    facts = relationship("Fact", back_populates="company", cascade="all, delete-orphan")
    snapshots = relationship("ProfileSnapshot", back_populates="company", cascade="all, delete-orphan")
    change_events = relationship("ChangeEvent", back_populates="company", cascade="all, delete-orphan")


class EvidenceSource(Base):
    """Source documents, URLs, and pages fetched during research."""
    __tablename__ = "evidence_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(Text, nullable=False, index=True)
    domain = Column(String(255), nullable=False, index=True)
    content_hash = Column(String(64), nullable=True, index=True)
    status_code = Column(Integer, nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    evidence_records = relationship("FactEvidenceModel", back_populates="source")


class Fact(Base):
    """Individual extracted facts with history preservation."""
    __tablename__ = "facts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False, index=True)
    normalized_value = Column(Text, nullable=True)  # JSON-encoded value
    raw_value = Column(Text, nullable=True)
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    company = relationship("Company", back_populates="facts")
    evidence_records = relationship("FactEvidenceModel", back_populates="fact", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_fact_company_field_current", "company_id", "field_name", "is_current"),
    )


class FactEvidenceModel(Base):
    """Detailed evidence and provenance for an individual fact."""
    __tablename__ = "fact_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fact_id = Column(Integer, ForeignKey("facts.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("evidence_sources.id"), nullable=False, index=True)
    excerpt = Column(Text, nullable=False)
    publication_date = Column(String(50), nullable=True)
    financial_period_json = Column(Text, nullable=True)
    identity_match = Column(String(50), default="VERIFIED_MATCH", nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    verification_status = Column(String(50), default="VERIFIED", nullable=False)
    quality = Column(String(50), default="REGISTRY_OFFICIAL", nullable=False)
    retrieved_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    fact = relationship("Fact", back_populates="evidence_records")
    source = relationship("EvidenceSource", back_populates="evidence_records")


class ProfileSnapshot(Base):
    """Point-in-time full JSON snapshots of company profiles."""
    __tablename__ = "profile_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False)
    snapshot_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    company = relationship("Company", back_populates="snapshots")


class ChangeEvent(Base):
    """Historical record of material changes between old and new facts with explanations."""
    __tablename__ = "change_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False, index=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    old_evidence_id = Column(Integer, ForeignKey("fact_evidence.id", ondelete="SET NULL"), nullable=True)
    new_evidence_id = Column(Integer, ForeignKey("fact_evidence.id", ondelete="SET NULL"), nullable=True)
    explanation = Column(Text, nullable=False)
    detected_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    company = relationship("Company", back_populates="change_events")


class CrawlRun(Base):
    """Metadata and execution tracking for evaluation runs."""
    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), unique=True, nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="RUNNING", nullable=False)
    total_companies = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)


class RequestUsage(Base):
    """Audit log of outbound network requests."""
    __tablename__ = "request_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=True, index=True)
    provider = Column(String(50), nullable=False)
    endpoint = Column(Text, nullable=False)
    status_code = Column(Integer, nullable=True)
    retries = Column(Integer, default=0, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ModelUsage(Base):
    """Audit log of LLM model invocations and token usage."""
    __tablename__ = "model_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    estimated_cost = Column(Float, default=0.0, nullable=False)
    measured_cost = Column(Float, default=0.0, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)
