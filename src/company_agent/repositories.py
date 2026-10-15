"""Data access repository for transactional profile persistence, versioning, and export."""

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from company_agent.models import (
    Company,
    Fact,
    EvidenceSource,
    FactEvidenceModel,
    ProfileSnapshot,
    ChangeEvent,
    SchemaVersion,
)
from company_agent.schemas import (
    CompanyProfile,
    FactEvidence,
    FactVerificationStatus,
    EvidenceQuality,
    FinancialPeriod,
)
from company_agent.cache import hash_content
from company_agent.logging_config import logger


class CompanyRepository:
    """Manages transactional database persistence for company intelligence entities."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_org_nr(self, org_nr: str) -> Optional[Company]:
        """Looks up company record by 9-digit organisation number."""
        return self.session.query(Company).filter_by(organisation_number=org_nr).first()

    def get_or_create_source(self, url: str, domain: str, content: Optional[str] = None, status_code: int = 200) -> EvidenceSource:
        """Finds or creates an evidence source record."""
        chash = hash_content(content) if content else None
        source = self.session.query(EvidenceSource).filter_by(url=url).first()
        if not source:
            source = EvidenceSource(
                url=url,
                domain=domain,
                content_hash=chash,
                status_code=status_code,
            )
            self.session.add(source)
            self.session.flush()
        return source

    def save_or_update_fact(
        self,
        company: Company,
        field_name: str,
        normalized_value: Any,
        raw_value: Optional[str],
        source: EvidenceSource,
        excerpt: str,
        publication_date: Optional[str] = None,
        financial_period: Optional[FinancialPeriod] = None,
        identity_match: str = "VERIFIED_MATCH",
        confidence: float = 1.0,
        verification_status: str = "VERIFIED",
        quality: str = "REGISTRY_OFFICIAL",
    ) -> Fact:
        """Saves a fact, maintaining history if value changes."""
        json_val = json.dumps(normalized_value, ensure_ascii=False) if normalized_value is not None else None

        # Look for existing active fact
        existing_fact = (
            self.session.query(Fact)
            .filter_by(company_id=company.id, field_name=field_name, is_current=True)
            .first()
        )

        now = datetime.now(timezone.utc)

        if existing_fact:
            if existing_fact.normalized_value == json_val:
                # Value unchanged: update last_seen_at on its latest evidence record
                for ev in existing_fact.evidence_records:
                    ev.last_seen_at = now
                existing_fact.updated_at = now
                return existing_fact
            else:
                # Value changed materially: archive current fact (history preservation)
                existing_fact.is_current = False
                existing_fact.updated_at = now
                new_version = existing_fact.version + 1
        else:
            new_version = 1

        # Create new active fact
        new_fact = Fact(
            company_id=company.id,
            field_name=field_name,
            normalized_value=json_val,
            raw_value=str(raw_value) if raw_value is not None else None,
            is_current=True,
            version=new_version,
            created_at=now,
            updated_at=now,
        )
        self.session.add(new_fact)
        self.session.flush()

        # Attach evidence record
        fin_json = financial_period.model_dump_json() if financial_period else None
        evidence_record = FactEvidenceModel(
            fact_id=new_fact.id,
            source_id=source.id,
            excerpt=excerpt,
            publication_date=publication_date,
            financial_period_json=fin_json,
            identity_match=identity_match,
            confidence=confidence,
            verification_status=verification_status,
            quality=quality,
            retrieved_at=now,
            last_seen_at=now,
        )
        self.session.add(evidence_record)
        self.session.flush()

        return new_fact

    def record_change(
        self,
        company: Company,
        field_name: str,
        old_val: Any,
        new_val: Any,
        explanation: str,
        old_evidence_id: Optional[int] = None,
        new_evidence_id: Optional[int] = None,
    ) -> ChangeEvent:
        """Records a detected material change event with explanation."""
        evt = ChangeEvent(
            company_id=company.id,
            field_name=field_name,
            old_value=str(old_val) if old_val is not None else None,
            new_value=str(new_val) if new_val is not None else None,
            old_evidence_id=old_evidence_id,
            new_evidence_id=new_evidence_id,
            explanation=explanation,
            detected_at=datetime.now(timezone.utc),
        )
        self.session.add(evt)
        return evt

    def save_snapshot(self, company: Company, profile_data: Dict[str, Any]) -> ProfileSnapshot:
        """Saves a JSON snapshot of the full profile state."""
        raw_json = json.dumps(profile_data, ensure_ascii=False)
        shash = hash_content(raw_json)
        snapshot = ProfileSnapshot(
            company_id=company.id,
            snapshot_json=raw_json,
            snapshot_hash=shash,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(snapshot)
        return snapshot

    def build_profile_schema(self, company: Company) -> CompanyProfile:
        """Reconstructs a strict CompanyProfile schema object from database entities."""
        facts_map: Dict[str, FactEvidence] = {}
        provenance_history: List[FactEvidence] = []

        all_facts = self.session.query(Fact).filter_by(company_id=company.id).all()
        for f in all_facts:
            parsed_val = json.loads(f.normalized_value) if f.normalized_value else None
            for ev in f.evidence_records:
                fin_per = None
                if ev.financial_period_json:
                    try:
                        fin_per = FinancialPeriod(**json.loads(ev.financial_period_json))
                    except Exception:
                        pass

                fe = FactEvidence(
                    field_name=f.field_name,
                    normalized_value=parsed_val,
                    raw_value=f.raw_value,
                    source_url=ev.source.url if ev.source else "",
                    source_domain=ev.source.domain if ev.source else "",
                    excerpt=ev.excerpt,
                    publication_date=ev.publication_date,
                    financial_period=fin_per,
                    retrieval_timestamp=ev.retrieved_at,
                    identity_verification_result=ev.identity_match,
                    confidence_score=ev.confidence,
                    quality_classification=EvidenceQuality(ev.quality) if ev.quality in EvidenceQuality.__members__ else EvidenceQuality.REGISTRY_OFFICIAL,
                    verification_status=FactVerificationStatus(ev.verification_status) if ev.verification_status in FactVerificationStatus.__members__ else FactVerificationStatus.VERIFIED,
                    last_seen_timestamp=ev.last_seen_at,
                )

                if f.is_current:
                    facts_map[f.field_name] = fe
                else:
                    provenance_history.append(fe)

        def get_val(key: str, default=None):
            return facts_map[key].normalized_value if key in facts_map else default

        # Fetch recent explanations
        recent_changes = (
            self.session.query(ChangeEvent)
            .filter_by(company_id=company.id)
            .order_by(ChangeEvent.detected_at.desc())
            .limit(10)
            .all()
        )
        explanations = [c.explanation for c in recent_changes]

        return CompanyProfile(
            organisation_number=company.organisation_number,
            name=company.name,
            legal_form=get_val("legal_form", company.legal_form),
            status=get_val("status", company.status),
            address=get_val("address"),
            postal_code=get_val("postal_code"),
            municipality=get_val("municipality"),
            country="Norway",
            industry_code=get_val("industry_code"),
            industry_description=get_val("industry_description"),
            registration_date=get_val("registration_date"),
            incorporation_date=get_val("incorporation_date"),
            official_website=get_val("official_website", company.website),
            employee_count=get_val("employee_count"),
            employee_count_date=get_val("employee_count_date"),
            financial_period=get_val("financial_period"),
            currency=get_val("currency"),
            revenue=get_val("revenue"),
            operating_profit=get_val("operating_profit"),
            total_assets=get_val("total_assets"),
            business_activities=get_val("business_activities", []),
            description=get_val("description"),
            facts=facts_map,
            provenance_history=provenance_history,
            explanations=explanations,
            created_at=company.created_at,
            updated_at=company.updated_at,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Returns database profile counts, fact totals, and evidence metrics."""
        total_companies = self.session.query(Company).count()
        total_facts = self.session.query(Fact).count()
        current_facts = self.session.query(Fact).filter_by(is_current=True).count()
        total_sources = self.session.query(EvidenceSource).count()
        total_changes = self.session.query(ChangeEvent).count()

        verified_evidence = (
            self.session.query(FactEvidenceModel)
            .filter_by(verification_status="VERIFIED")
            .count()
        )
        total_evidence = self.session.query(FactEvidenceModel).count()
        verified_pct = (verified_evidence / total_evidence * 100.0) if total_evidence > 0 else 0.0

        return {
            "total_companies": total_companies,
            "total_facts": total_facts,
            "current_facts": current_facts,
            "total_sources": total_sources,
            "total_changes_recorded": total_changes,
            "total_evidence_records": total_evidence,
            "verified_evidence_records": verified_evidence,
            "verified_rate_pct": round(verified_pct, 2),
        }
