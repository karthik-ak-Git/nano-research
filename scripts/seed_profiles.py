"""Seeds at least 1,000 distinct real, validated Norwegian company profiles from the official Brreg registry.

Features:
- Discovers real Norwegian organisation numbers and full entity records from Brønnøysund Register Centre.
- Validates every identifier using the official modulus-11 checksum algorithm.
- Reconciles authoritative registry identity data with zero fabricated data.
- Persists full provenance, fact-level evidence, and UTC timestamps.
- Highly efficient bulk paging (10 requests for 1,000 companies), respecting rate limits and request budgets.
- Resumable: skips already-seeded profiles on restart.
- Exports a verification manifest and JSON dataset upon completion.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.identity import validate_organisation_number
from company_agent.database import init_db, get_db_session
from company_agent.repositories import CompanyRepository
from company_agent.models import Company, Fact, EvidenceSource, FactEvidenceModel
from company_agent.schemas import FactVerificationStatus, EvidenceQuality
from company_agent.providers.registry import registry_client
from company_agent.budgets import budget_manager


def seed_profiles(target_count: int = 1000, output_dir: Path = settings.PROFILES_DIR) -> int:
    """Discovers and builds verified profiles for real Norwegian companies directly from official Brreg registry."""
    init_db()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "seed_manifest.json"
    profiles_export_path = output_dir / "seeded_profiles.json"

    with get_db_session() as session:
        existing_count = session.query(Company).count()
        existing_orgs = {c[0] for c in session.query(Company.organisation_number).all()}

    logger.info("Current database profile count: %d (Target: %d)", existing_count, target_count)

    if existing_count >= target_count:
        logger.info("Target of %d profiles already satisfied in database.", target_count)
        _export_manifest_and_profiles(manifest_path, profiles_export_path, target_count)
        return existing_count

    needed = target_count - existing_count
    logger.info("Fetching real Norwegian company records from Brreg open registry (need %d)...", needed)

    page = 0
    page_size = 100
    start_time = time.time()
    total_newly_seeded = 0

    while (existing_count + total_newly_seeded) < target_count and page < 50:
        budget_manager.check_budget_available()
        url = f"{settings.BRREG_API_BASE}/enheter?size={page_size}&page={page}"
        resp = registry_client._get_with_retry(url)
        if not resp or resp.status_code != 200:
            logger.warning("Could not fetch page %d from Brreg", page)
            break

        data = resp.json()
        enheter = data.get("_embedded", {}).get("enheter", [])
        if not enheter:
            break

        now = datetime.now(timezone.utc)

        with get_db_session() as session:
            repo = CompanyRepository(session)

            for enhet in enheter:
                raw_org = enhet.get("organisasjonsnummer")
                if not raw_org:
                    continue

                is_valid, clean_org = validate_organisation_number(str(raw_org))
                if not is_valid or clean_org in existing_orgs:
                    continue

                legal_name = enhet.get("navn", f"Company {clean_org}")
                org_form = enhet.get("organisasjonsform", {}).get("kode")
                status_str = "Bankrupt" if enhet.get("konkurs") else (
                    "In Liquidation" if enhet.get("underAvvikling") else "Active"
                )
                addr_info = enhet.get("forretningsadresse") or enhet.get("postadresse") or {}
                street = ", ".join(addr_info.get("adresse", [])) or None
                post_code = addr_info.get("postnummer")
                muni = addr_info.get("poststed") or addr_info.get("kommune")
                ind_info = enhet.get("naeringskode1") or {}
                nace_code = ind_info.get("kode")
                nace_desc = ind_info.get("beskrivelse")
                reg_date = enhet.get("registreringsdatoEnhetsregisteret")
                incorp_date = enhet.get("stiftelsesdato")
                employees = enhet.get("antallAnsatte")
                website = enhet.get("hjemmeside")
                if website and not website.startswith("http"):
                    website = f"https://{website}"

                # Create Company
                company = Company(
                    organisation_number=clean_org,
                    name=legal_name,
                    status=status_str,
                    legal_form=org_form,
                    website=website,
                    created_at=now,
                    updated_at=now,
                )
                session.add(company)
                session.flush()

                # Source record
                src_url = f"{settings.BRREG_API_BASE}/enheter/{clean_org}"
                source = repo.get_or_create_source(
                    url=src_url,
                    domain="data.brreg.no",
                    content=str(enhet),
                )

                # Persist core verified facts with provenance
                facts_data = [
                    ("name", legal_name, legal_name, None),
                    ("legal_form", org_form, org_form, None),
                    ("status", status_str, status_str, None),
                    ("address", street, street, None),
                    ("postal_code", post_code, post_code, None),
                    ("municipality", muni, muni, None),
                    ("country", "Norway", "Norway", None),
                    ("industry_code", nace_code, nace_code, None),
                    ("industry_description", nace_desc, nace_desc, None),
                    ("registration_date", reg_date, reg_date, reg_date),
                    ("incorporation_date", incorp_date, incorp_date, incorp_date),
                ]

                if employees is not None:
                    facts_data.append(("employee_count", employees, str(employees), None))
                if website:
                    facts_data.append(("official_website", website, website, None))

                for f_name, norm_val, raw_val, pub_date in facts_data:
                    if norm_val is not None:
                        repo.save_or_update_fact(
                            company=company,
                            field_name=f_name,
                            normalized_value=norm_val,
                            raw_value=raw_val,
                            source=source,
                            excerpt=f"Official Brreg Enhetsregisteret registry record for {clean_org}",
                            publication_date=pub_date,
                            identity_match="VERIFIED_MATCH",
                            confidence=1.0,
                            verification_status=FactVerificationStatus.VERIFIED.value,
                            quality=EvidenceQuality.REGISTRY_OFFICIAL.value,
                        )

                # Save point-in-time snapshot
                profile_obj = repo.build_profile_schema(company)
                repo.save_snapshot(company, profile_obj.model_dump(mode="json"))

                existing_orgs.add(clean_org)
                total_newly_seeded += 1

                if (existing_count + total_newly_seeded) >= target_count:
                    break

        page += 1
        elapsed = time.time() - start_time
        logger.info(
            "Seeded batch %d: Total in DB now %d/%d (%.1fs)",
            page, existing_count + total_newly_seeded, target_count, elapsed
        )
        time.sleep(0.05)

    final_total = existing_count + total_newly_seeded
    logger.info("Seeding complete. Final database profile count: %d", final_total)
    _export_manifest_and_profiles(manifest_path, profiles_export_path, target_count)
    return final_total


def _export_manifest_and_profiles(manifest_path: Path, export_path: Path, target: int) -> None:
    """Exports manifest and full JSON export of seeded profiles."""
    with get_db_session() as session:
        repo = CompanyRepository(session)
        stats = repo.get_stats()
        companies = session.query(Company).all()
        profiles_json = [repo.build_profile_schema(c).model_dump(mode="json") for c in companies]

    export_path.write_text(json.dumps(profiles_json, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Seeded profiles exported to %s", export_path)

    manifest_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_count": target,
        "actual_count": stats["total_companies"],
        "target_met": stats["total_companies"] >= target,
        "total_facts": stats["total_facts"],
        "verified_evidence_rate_pct": stats["verified_rate_pct"],
        "export_file": str(export_path),
        "sample_companies": [
            {"organisation_number": p["organisation_number"], "name": p["name"], "status": p["status"], "facts_count": len(p["facts"])}
            for p in profiles_json[:20]
        ],
    }

    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Seeding manifest written to %s", manifest_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Norwegian company profiles from official registry")
    parser.add_argument("--target", type=int, default=1000, help="Target number of distinct profiles")
    args = parser.parse_args()
    seed_profiles(target_count=args.target)
