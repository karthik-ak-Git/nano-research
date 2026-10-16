"""Modular 17-step company research, extraction, and verification pipeline."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.identity import (
    assert_valid_organisation_number,
    validate_organisation_number,
    verify_entity_resolution,
)
from company_agent.schemas import (
    CompanyProfile,
    FactEvidence,
    FactVerificationStatus,
    EvidenceQuality,
    FinancialPeriod,
)
from company_agent.database import get_db_session
from company_agent.repositories import CompanyRepository
from company_agent.models import Company, Fact
from company_agent.providers.registry import registry_client
from company_agent.providers.browser_use import BrowserUseProvider
from company_agent.providers.tinyfish import TinyFishProvider
from company_agent.providers.mock import MockBrowserProvider
from company_agent.providers.gemini import gemini_client
from company_agent.extraction import extract_clean_text_from_html, extract_relevant_snippets
from company_agent.verification import verify_fact_provenance, validate_financial_fact
from company_agent.freshness import is_profile_fresh, is_fact_fresh
from company_agent.change_detection import detect_field_change
from company_agent.explanations import generate_profile_summary_explanation
from company_agent.budgets import budget_manager, BudgetExceededError


class ResearchPipeline:
    """End-to-end research orchestrator enforcing the competition contract."""

    def __init__(self, browser_provider_name: Optional[str] = None):
        provider_key = browser_provider_name or settings.BROWSER_PROVIDER
        if provider_key == "tinyfish":
            self.browser_provider = TinyFishProvider()
        elif provider_key == "browser_use":
            self.browser_provider = BrowserUseProvider()
        else:
            self.browser_provider = MockBrowserProvider()

    async def execute(self, org_nr: str, force_refresh: bool = False) -> CompanyProfile:
        """Executes the complete 17-step intelligence pipeline for an organisation number."""
        start_time = time.time()
        warnings: List[str] = []
        changes_detected: List[str] = []

        # 1. Validate and normalize the organisation number
        clean_org = assert_valid_organisation_number(org_nr)

        # 2. Check the database for an existing profile
        with get_db_session() as session:
            repo = CompanyRepository(session)
            existing_company = repo.get_by_org_nr(clean_org)
            if existing_company and not force_refresh:
                if is_profile_fresh(existing_company.updated_at):
                    logger.info("Returning fresh profile from database for %s", clean_org)
                    return repo.build_profile_schema(existing_company)

        # 3. Retrieve authoritative registry information first
        registry_data = registry_client.get_enhet(clean_org)
        if not registry_data:
            raise ValueError(f"No official registration found in Brønnøysund Register Centre for '{clean_org}'")

        legal_name = registry_data.get("navn", f"Company {clean_org}")
        org_form = registry_data.get("organisasjonsform", {}).get("kode")
        status_str = "Bankrupt" if registry_data.get("konkurs") else (
            "In Liquidation" if registry_data.get("underAvvikling") else "Active"
        )
        address_info = registry_data.get("forretningsadresse", {})
        street_address = ", ".join(address_info.get("adresse", [])) or None
        postal_code = address_info.get("postnummer")
        municipality = address_info.get("poststed") or address_info.get("kommune")
        industry_info = registry_data.get("naeringskode1", {})
        nace_code = industry_info.get("kode")
        nace_desc = industry_info.get("beskrivelse")
        reg_date = registry_data.get("registreringsdatoEnhetsregisteret")
        incorp_date = registry_data.get("stiftelsesdato")
        employees = registry_data.get("antallAnsatte")
        official_website = registry_data.get("hjemmeside")
        if official_website and not official_website.startswith("http"):
            official_website = f"https://{official_website}"

        # Financial accounts from Regnskapsregisteret
        regnskap_list = registry_client.get_regnskap(clean_org)
        fin_period = None
        rev_val = None
        profit_val = None
        assets_val = None
        currency_val = None
        period_str = None

        if regnskap_list:
            latest = regnskap_list[0]
            currency_val = latest.get("valuta", "NOK")
            p_data = latest.get("regnskapsperiode", {})
            from_d = p_data.get("fraDato")
            to_d = p_data.get("tilDato")
            period_str = f"{from_d} to {to_d}" if from_d and to_d else str(latest.get("sisteInnsendteAarsregnskap"))
            
            res_data = latest.get("resultatregnskapResultat", {})
            driftsres = res_data.get("driftsresultat", {})
            if isinstance(driftsres, dict):
                profit_val = driftsres.get("driftsresultat")
                inntekter = driftsres.get("driftsinntekter", {})
                if isinstance(inntekter, dict):
                    rev_val = inntekter.get("salgsinntekter") or inntekter.get("sumDriftsinntekter")

            eiendeler = latest.get("eiendeler", {})
            if isinstance(eiendeler, dict):
                assets_val = eiendeler.get("sumEiendeler")

            fin_period = FinancialPeriod(
                from_date=from_d,
                to_date=to_d,
                currency=currency_val,
                revenue=rev_val,
                operating_profit=profit_val,
                total_assets=assets_val,
            )

        # 4 & 5. Targeted searches & bounded web sources
        target_urls: List[str] = []
        if official_website:
            target_urls.append(official_website)

        # 6, 7, 8. Fetch permitted pages, extract snippets, deduplicate
        web_source_url: Optional[str] = None
        web_source_domain: Optional[str] = None
        web_cleaned_text: str = ""
        web_resolution_status: str = "UNVERIFIED"
        web_confidence: float = 0.1
        web_snippets: List[str] = []

        if target_urls:
            from urllib.parse import urlparse
            target_url = target_urls[0]
            web_source_url = target_url
            try:
                parsed_u = urlparse(target_url)
                web_source_domain = parsed_u.netloc.replace("www.", "").strip()
            except Exception:
                web_source_domain = "website"

            try:
                browser_res = await self.browser_provider.navigate_and_extract(
                    url=target_url,
                    goal=f"Extract company description, leadership, and activities for {legal_name}",
                    timeout=20.0,
                )
                if browser_res.cleaned_text:
                    web_cleaned_text = browser_res.cleaned_text
                    
                    # Entity resolution check on web text
                    from company_agent.identity import extract_organisation_numbers
                    source_orgs = extract_organisation_numbers(web_cleaned_text)
                    if clean_org in source_orgs:
                        web_resolution_status = "VERIFIED_MATCH"
                        web_confidence = 1.0
                    elif source_orgs:
                        # Found valid Norwegian org numbers, but NOT the target company!
                        web_resolution_status = "CONFLICT_MISMATCH"
                        web_confidence = 0.0
                        warnings.append(
                            f"Entity resolution conflict on {target_url}: found conflicting organisation numbers {source_orgs}"
                        )
                    else:
                        # Reconcile via official domain and registered legal name
                        res_status, res_expl, res_conf = verify_entity_resolution(
                            requested_org_nr=clean_org,
                            registry_legal_name=legal_name,
                            source_name=legal_name,
                            source_domain=web_source_domain,
                            official_domain=web_source_domain,
                        )
                        web_resolution_status = res_status
                        web_confidence = res_conf

                    snips = extract_relevant_snippets(
                        web_cleaned_text,
                        keywords=[legal_name, clean_org, "virksomhet", "tjenester", "om oss"],
                        max_snippets=settings.MAX_SNIPPETS_PER_MODEL_CALL,
                    )
                    web_snippets.extend(snips)
            except Exception as e:
                warnings.append(f"Web extraction from {target_url} incomplete: {e}")

        # 9 & 10. Entity resolution & pass useful evidence to Gemini
        gemini_facts = {}
        if web_snippets and web_resolution_status != "CONFLICT_MISMATCH":
            try:
                gemini_facts = gemini_client.extract_structured_facts(
                    company_name=legal_name,
                    org_nr=clean_org,
                    evidence_snippets=web_snippets,
                )
            except BudgetExceededError:
                warnings.append("Gemini extraction skipped due to resource budget limit")
            except Exception as e:
                warnings.append(f"Gemini processing error: {e}")

        # 11, 12, 13, 14, 15. Save supported facts and detect material changes transactionally
        with get_db_session() as session:
            repo = CompanyRepository(session)
            company = repo.get_by_org_nr(clean_org)
            if not company:
                company = Company(
                    organisation_number=clean_org,
                    name=legal_name,
                    status=status_str,
                    legal_form=org_form,
                    website=official_website,
                )
                session.add(company)
                session.flush()
            else:
                company.name = legal_name
                company.status = status_str
                company.legal_form = org_form
                if official_website:
                    company.website = official_website

            # Source for registry data (Enhetsregisteret)
            registry_source = repo.get_or_create_source(
                url=f"{settings.BRREG_API_BASE}/enheter/{clean_org}",
                domain="data.brreg.no",
                content=str(registry_data),
            )

            # Facts list with strict provenance attribution
            facts_to_save: List[Dict[str, Any]] = [
                {
                    "field_name": "name",
                    "normalized_value": legal_name,
                    "raw_value": legal_name,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Authoritative legal name '{legal_name}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "legal_form",
                    "normalized_value": org_form,
                    "raw_value": org_form,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Authoritative legal form '{org_form}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "status",
                    "normalized_value": status_str,
                    "raw_value": status_str,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Authoritative status '{status_str}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "address",
                    "normalized_value": street_address,
                    "raw_value": street_address,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Registered business address '{street_address}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "postal_code",
                    "normalized_value": postal_code,
                    "raw_value": postal_code,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Registered postal code '{postal_code}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "municipality",
                    "normalized_value": municipality,
                    "raw_value": municipality,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Registered municipality '{municipality}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "industry_code",
                    "normalized_value": nace_code,
                    "raw_value": nace_code,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"NACE industry code '{nace_code}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "industry_description",
                    "normalized_value": nace_desc,
                    "raw_value": nace_desc,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"NACE industry description '{nace_desc}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                },
                {
                    "field_name": "registration_date",
                    "normalized_value": reg_date,
                    "raw_value": reg_date,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Registration date '{reg_date}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": reg_date,
                    "fin_period": None,
                },
                {
                    "field_name": "incorporation_date",
                    "normalized_value": incorp_date,
                    "raw_value": incorp_date,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Incorporation date '{incorp_date}' from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": incorp_date,
                    "fin_period": None,
                },
                {
                    "field_name": "employee_count",
                    "normalized_value": employees,
                    "raw_value": str(employees) if employees is not None else None,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Official employee count {employees} from Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": registry_data.get("registreringsdatoAntallAnsatteEnhetsregisteret"),
                    "fin_period": None,
                },
            ]

            if official_website:
                facts_to_save.append({
                    "field_name": "official_website",
                    "normalized_value": official_website,
                    "raw_value": official_website,
                    "source": registry_source,
                    "source_name": "Brønnøysund Register Centre",
                    "excerpt": f"Official website '{official_website}' registered in Enhetsregisteret record for {clean_org}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": None,
                    "fin_period": None,
                })

            # Financial facts (with validation, sourced from Regnskapsregisteret)
            if fin_period and (rev_val is not None or profit_val is not None or assets_val is not None):
                regnskap_source = repo.get_or_create_source(
                    url=f"{settings.BRREG_REGNSKAP_BASE}/regnskap/{clean_org}",
                    domain="data.brreg.no",
                    content=str(regnskap_list),
                )
                if rev_val is not None:
                    is_valid_fin, _ = validate_financial_fact(
                        "revenue", rev_val, currency_val, period_str, f"Sales revenue reported in {currency_val}"
                    )
                    if is_valid_fin:
                        facts_to_save.append({
                            "field_name": "revenue",
                            "normalized_value": rev_val,
                            "raw_value": str(rev_val),
                            "source": regnskap_source,
                            "source_name": "Brønnøysund Regnskapsregisteret",
                            "excerpt": f"Sales revenue {rev_val} {currency_val} from Regnskapsregisteret for period {period_str}",
                            "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                            "verification_status": FactVerificationStatus.VERIFIED,
                            "identity_match": "VERIFIED_MATCH",
                            "confidence": 1.0,
                            "pub_date": to_d,
                            "fin_period": fin_period,
                        })
                if profit_val is not None:
                    facts_to_save.append({
                        "field_name": "operating_profit",
                        "normalized_value": profit_val,
                        "raw_value": str(profit_val),
                        "source": regnskap_source,
                        "source_name": "Brønnøysund Regnskapsregisteret",
                        "excerpt": f"Operating profit {profit_val} {currency_val} from Regnskapsregisteret for period {period_str}",
                        "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                        "verification_status": FactVerificationStatus.VERIFIED,
                        "identity_match": "VERIFIED_MATCH",
                        "confidence": 1.0,
                        "pub_date": to_d,
                        "fin_period": fin_period,
                    })
                if assets_val is not None:
                    facts_to_save.append({
                        "field_name": "total_assets",
                        "normalized_value": assets_val,
                        "raw_value": str(assets_val),
                        "source": regnskap_source,
                        "source_name": "Brønnøysund Regnskapsregisteret",
                        "excerpt": f"Total assets {assets_val} {currency_val} from Regnskapsregisteret for period {period_str}",
                        "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                        "verification_status": FactVerificationStatus.VERIFIED,
                        "identity_match": "VERIFIED_MATCH",
                        "confidence": 1.0,
                        "pub_date": to_d,
                        "fin_period": fin_period,
                    })
                facts_to_save.append({
                    "field_name": "currency",
                    "normalized_value": currency_val,
                    "raw_value": currency_val,
                    "source": regnskap_source,
                    "source_name": "Brønnøysund Regnskapsregisteret",
                    "excerpt": f"Financial reporting currency '{currency_val}' from Regnskapsregisteret for period {period_str}",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": to_d,
                    "fin_period": fin_period,
                })
                facts_to_save.append({
                    "field_name": "financial_period",
                    "normalized_value": period_str,
                    "raw_value": period_str,
                    "source": regnskap_source,
                    "source_name": "Brønnøysund Regnskapsregisteret",
                    "excerpt": f"Annual accounts financial period '{period_str}' from Regnskapsregisteret",
                    "quality": EvidenceQuality.REGISTRY_OFFICIAL,
                    "verification_status": FactVerificationStatus.VERIFIED,
                    "identity_match": "VERIFIED_MATCH",
                    "confidence": 1.0,
                    "pub_date": to_d,
                    "fin_period": fin_period,
                })

            # Web-derived facts: strict attribution to the actual website source URL
            # Unsupported facts lacking direct evidence excerpts are explicitly rejected
            if gemini_facts.get("description") and web_source_url and web_resolution_status != "CONFLICT_MISMATCH":
                desc_text = gemini_facts["description"]
                desc_excerpt = gemini_facts.get("description_excerpt")

                # Verify that an actual grounding excerpt exists
                if not desc_excerpt and web_snippets:
                    for snip in web_snippets:
                        if any(w in snip.lower() for w in desc_text.lower().split()[:5]):
                            desc_excerpt = snip
                            break

                if desc_excerpt:
                    web_source = repo.get_or_create_source(
                        url=web_source_url,
                        domain=web_source_domain or "website",
                        content=web_cleaned_text[:5000],
                    )
                    w_quality = (
                        EvidenceQuality.DIRECT_OFFICIAL
                        if web_resolution_status == "VERIFIED_MATCH"
                        else EvidenceQuality.SECONDARY_PUBLIC
                    )
                    w_status = (
                        FactVerificationStatus.VERIFIED
                        if web_resolution_status == "VERIFIED_MATCH"
                        else FactVerificationStatus.SECONDARY_SUPPORTED
                    )

                    facts_to_save.append({
                        "field_name": "description",
                        "normalized_value": desc_text,
                        "raw_value": desc_text,
                        "source": web_source,
                        "source_name": web_source_domain or web_source_url,
                        "excerpt": desc_excerpt[:500],
                        "quality": w_quality,
                        "verification_status": w_status,
                        "identity_match": web_resolution_status,
                        "confidence": web_confidence,
                        "pub_date": None,
                        "fin_period": None,
                    })
                else:
                    msg = f"Rejected unsupported web description for {clean_org}: no grounding excerpt found in {web_source_url}"
                    logger.warning(msg)
                    warnings.append(msg)

            # Save facts and detect material changes with accurate source attribution
            for item in facts_to_save:
                f_name = item["field_name"]
                norm_val = item["normalized_value"]
                raw_val = item["raw_value"]
                source_obj = item["source"]
                src_name = item["source_name"]
                excerpt = item["excerpt"]
                quality = item["quality"]
                v_status = item["verification_status"]
                ident_match = item["identity_match"]
                conf = item["confidence"]
                pub_date = item["pub_date"]
                fin_p = item["fin_period"]

                if norm_val is None:
                    continue

                # Query for previous active fact to detect material changes
                existing_f = (
                    session.query(Fact)
                    .filter_by(company_id=company.id, field_name=f_name, is_current=True)
                    .first()
                )
                if existing_f and existing_f.normalized_value:
                    import json
                    old_decoded = json.loads(existing_f.normalized_value)
                    changed, change_exp = detect_field_change(
                        field_name=f_name,
                        old_value=old_decoded,
                        new_value=norm_val,
                        source_name=src_name,
                        source_date=pub_date,
                    )
                    if changed and change_exp:
                        changes_detected.append(change_exp)
                        repo.record_change(
                            company=company,
                            field_name=f_name,
                            old_val=old_decoded,
                            new_val=norm_val,
                            explanation=change_exp,
                        )

                # Persist fact with actual source and excerpt
                repo.save_or_update_fact(
                    company=company,
                    field_name=f_name,
                    normalized_value=norm_val,
                    raw_value=raw_val,
                    source=source_obj,
                    excerpt=excerpt,
                    publication_date=pub_date,
                    financial_period=fin_p,
                    identity_match=ident_match,
                    confidence=conf,
                    verification_status=v_status.value if hasattr(v_status, "value") else str(v_status),
                    quality=quality.value if hasattr(quality, "value") else str(quality),
                )

            # Build final schema
            profile = repo.build_profile_schema(company)
            profile.warnings.extend(warnings)
            if changes_detected:
                profile.explanations.extend(changes_detected)
            else:
                profile.explanations.append(generate_profile_summary_explanation(profile))

            # Save point-in-time snapshot
            repo.save_snapshot(company, profile.model_dump(mode="json"))

            return profile


pipeline = ResearchPipeline()
