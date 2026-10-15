"""Human-understandable explanations for company profile facts and historical changes."""

from typing import List, Optional
from company_agent.schemas import CompanyProfile


def generate_profile_summary_explanation(profile: CompanyProfile) -> str:
    """Generates a concise, evidence-based executive summary of the company profile."""
    parts = []

    # Legal identity
    parts.append(
        f"{profile.name} is a Norwegian {profile.legal_form or 'corporate entity'} "
        f"(Org Nr: {profile.organisation_number}) with status '{profile.status}'."
    )

    # Registration & incorporation
    if profile.incorporation_date:
        parts.append(f"Incorporated on {profile.incorporation_date}.")
    elif profile.registration_date:
        parts.append(f"Registered in the Norwegian Business Register on {profile.registration_date}.")

    # Address & location
    if profile.address and profile.municipality:
        parts.append(f"Located at {profile.address}, {profile.postal_code or ''} {profile.municipality}.")

    # Industry
    if profile.industry_description:
        parts.append(f"Primary industry: {profile.industry_description} (NACE: {profile.industry_code or 'N/A'}).")

    # Employees
    if profile.employee_count is not None:
        parts.append(f"Employs {profile.employee_count:,} registered personnel.")

    # Financials
    if profile.revenue is not None and profile.currency:
        parts.append(
            f"Latest financial statement ({profile.financial_period or 'recent'}) reports "
            f"revenue of {profile.currency} {profile.revenue:,.0f} and operating profit of "
            f"{profile.currency} {profile.operating_profit:,.0f}."
        )

    return " ".join(parts)


def format_change_explanation_list(changes: List[str]) -> str:
    """Formats a list of change explanation strings into a readable bulleted narrative."""
    if not changes:
        return "No material changes detected since previous profile revision."

    formatted = ["Material changes detected:"]
    for c in changes:
        formatted.append(f"• {c}")
    return "\n".join(formatted)
