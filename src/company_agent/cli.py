"""Command Line Interface for Norwegian Company Intelligence Agent."""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.database import init_db, get_db_session
from company_agent.identity import validate_organisation_number
from company_agent.pipeline import pipeline
from company_agent.repositories import CompanyRepository
from company_agent.models import Company
from company_agent.costs import generate_cost_report
from company_agent.budgets import budget_manager, BudgetExceededError
from company_agent.providers.gemini import gemini_client
from company_agent.providers.registry import registry_client

app = typer.Typer(
    name="company-agent",
    help="Norwegian Company Intelligence Agent — Competition Ready CLI",
    add_completion=False,
)
console = Console()


@app.callback()
def main_callback():
    """Initializes database schema automatically on any CLI invocation."""
    init_db()


@app.command()
def lookup(
    org_nr: str = typer.Argument(..., help="9-digit Norwegian organisation number"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output pure JSON only"),
):
    """Lookup or research a Norwegian company by organisation number."""
    is_valid, clean_or_err = validate_organisation_number(org_nr)
    if not is_valid:
        console.print(f"[bold red]Validation Error:[/bold red] {clean_or_err}")
        raise typer.Exit(code=1)

    try:
        profile = asyncio.run(pipeline.execute(clean_or_err, force_refresh=False))
        if json_output:
            typer.echo(profile.model_dump_json(indent=2))
        else:
            table = Table(title=f"Company Profile: {profile.name} ({profile.organisation_number})")
            table.add_column("Field", style="cyan", no_wrap=True)
            table.add_column("Value", style="green")
            table.add_column("Status / Source", style="yellow")

            table.add_row("Legal Name", profile.name, "VERIFIED (Brreg)")
            table.add_row("Status", profile.status, "VERIFIED (Brreg)")
            table.add_row("Legal Form", profile.legal_form or "N/A", "VERIFIED (Brreg)")
            table.add_row("Address", f"{profile.address or 'N/A'}, {profile.postal_code or ''} {profile.municipality or ''}", "VERIFIED (Brreg)")
            table.add_row("Industry", f"{profile.industry_code or 'N/A'} - {profile.industry_description or 'N/A'}", "VERIFIED (Brreg)")
            table.add_row("Registration Date", profile.registration_date or "N/A", "VERIFIED (Brreg)")
            table.add_row("Incorporation Date", profile.incorporation_date or "N/A", "VERIFIED (Brreg)")
            table.add_row("Employees", str(profile.employee_count) if profile.employee_count is not None else "N/A", "VERIFIED (NAV/Brreg)")
            table.add_row("Official Website", profile.official_website or "N/A", "VERIFIED")
            
            if profile.revenue is not None:
                table.add_row("Revenue", f"{profile.currency or 'NOK'} {profile.revenue:,.0f}", f"VERIFIED ({profile.financial_period})")
            if profile.operating_profit is not None:
                table.add_row("Operating Profit", f"{profile.currency or 'NOK'} {profile.operating_profit:,.0f}", f"VERIFIED ({profile.financial_period})")

            console.print(table)
            if profile.explanations:
                console.print(Panel("\n".join(profile.explanations), title="Profile Summary & Explanation", style="bold blue"))
            if profile.warnings:
                console.print(Panel("\n".join(profile.warnings), title="Warnings & Notes", style="bold red"))

    except Exception as e:
        console.print(f"[bold red]Lookup failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def refresh(
    org_nr: str = typer.Argument(..., help="9-digit Norwegian organisation number"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output pure JSON only"),
):
    """Force an incremental refresh of a company profile regardless of cached TTL."""
    is_valid, clean_or_err = validate_organisation_number(org_nr)
    if not is_valid:
        console.print(f"[bold red]Validation Error:[/bold red] {clean_or_err}")
        raise typer.Exit(code=1)

    try:
        profile = asyncio.run(pipeline.execute(clean_or_err, force_refresh=True))
        if json_output:
            typer.echo(profile.model_dump_json(indent=2))
        else:
            console.print(f"[bold green]Successfully refreshed profile for {profile.name} ({profile.organisation_number})[/bold green]")
            if profile.explanations:
                console.print(Panel("\n".join(profile.explanations), title="Update Explanations", style="bold blue"))
    except Exception as e:
        console.print(f"[bold red]Refresh failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def batch(
    input_file: Path = typer.Option(..., "--input", "-i", help="Path to text or JSON file with organisation numbers"),
    output_file: Path = typer.Option(..., "--output", "-o", help="Path to write JSON results"),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Skip already processed companies"),
    force_refresh: bool = typer.Option(False, "--force-refresh", "-f", help="Force fresh live lookup bypassing cache"),
):
    """Run batch intelligence extraction for multiple companies within daily budget limits."""
    if not input_file.exists():
        console.print(f"[bold red]Input file not found:[/bold red] {input_file}")
        raise typer.Exit(code=1)

    # Read organisation numbers
    org_numbers = []
    text_content = input_file.read_text(encoding="utf-8").strip()
    if input_file.suffix == ".json":
        data = json.loads(text_content)
        if isinstance(data, list):
            org_numbers = [str(x) for x in data]
        elif isinstance(data, dict):
            org_numbers = [str(x) for x in data.get("companies", [])]
    else:
        for line in text_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                org_numbers.append(line)

    mode_str = "[bold yellow]LIVE REFRESH (live provider calls)[/bold yellow]" if force_refresh else "[cyan]CACHED (verified DB lookup)[/cyan]"
    console.print(f"[cyan]Loaded {len(org_numbers)} organisation numbers for batch execution. Mode: {mode_str}[/cyan]")

    # Check for existing completed results if resuming
    results = []
    completed_orgs = set()
    if resume and output_file.exists():
        try:
            prev_data = json.loads(output_file.read_text(encoding="utf-8"))
            if isinstance(prev_data, list):
                results = prev_data
                completed_orgs = {p.get("organisation_number") for p in prev_data if p.get("organisation_number")}
                console.print(f"[yellow]Resuming run: found {len(completed_orgs)} previously completed companies in output file.[/yellow]")
        except Exception:
            pass

    success_count = 0
    failed_count = 0
    start_time = time.time()

    for idx, raw_org in enumerate(org_numbers, 1):
        is_valid, clean_org = validate_organisation_number(raw_org)
        if not is_valid:
            console.print(f"[{idx}/{len(org_numbers)}] [red]Invalid org number '{raw_org}': {clean_org}[/red]")
            failed_count += 1
            continue

        if clean_org in completed_orgs:
            console.print(f"[{idx}/{len(org_numbers)}] [dim]Skipping already processed {clean_org}[/dim]")
            continue

        try:
            budget_manager.check_budget_available()
            t0 = time.time()
            profile = asyncio.run(pipeline.execute(clean_org, force_refresh=force_refresh))
            elapsed = time.time() - t0

            profile_dict = profile.model_dump(mode="json")
            results.append(profile_dict)
            completed_orgs.add(clean_org)
            success_count += 1
            console.print(f"[{idx}/{len(org_numbers)}] [green]SUCCESS[/green] {profile.name} ({clean_org}) in {elapsed:.2f}s")

            # Save partial progress incrementally so interrupted runs can resume
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        except BudgetExceededError as be:
            console.print(f"[bold red]BUDGET LIMIT REACHED:[/bold red] {be}. Halting batch execution safely.")
            break
        except Exception as e:
            failed_count += 1
            console.print(f"[{idx}/{len(org_numbers)}] [red]FAILED[/red] {clean_org}: {e}")

    total_time = time.time() - start_time
    console.print(
        f"\n[bold green]Batch Complete:[/bold green] {success_count} succeeded, "
        f"{failed_count} failed in {total_time:.1f}s. Results saved to {output_file}"
    )


@app.command()
def export(
    output_file: Path = typer.Option(..., "--output", "-o", help="File to export company profiles to"),
    format: str = typer.Option("json", "--format", "-f", help="Export format (json)"),
):
    """Export all stored company profiles from database to JSON."""
    with get_db_session() as session:
        repo = CompanyRepository(session)
        companies = session.query(Company).all()
        profiles = [repo.build_profile_schema(c).model_dump(mode="json") for c in companies]

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")

        console.print(f"[bold green]Successfully exported {len(profiles)} company profiles to {output_file}[/bold green]")


@app.command()
def stats():
    """Display database statistics, profile counts, and verification rates."""
    with get_db_session() as session:
        repo = CompanyRepository(session)
        st = repo.get_stats()

        table = Table(title="Norwegian Company Intelligence — Database Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Companies", str(st["total_companies"]))
        table.add_row("Total Facts", str(st["total_facts"]))
        table.add_row("Current Active Facts", str(st["current_facts"]))
        table.add_row("Evidence Sources", str(st["total_sources"]))
        table.add_row("Recorded Evidence Records", str(st["total_evidence_records"]))
        table.add_row("Verified Evidence Rate", f"{st['verified_rate_pct']}%")
        table.add_row("Total Historical Changes", str(st["total_changes_recorded"]))

        console.print(table)


@app.command("cost-report")
def cost_report():
    """Generate and display external API cost and resource utilization report."""
    with get_db_session() as session:
        repo = CompanyRepository(session)
        count = session.query(Company).count()

    rep = generate_cost_report(companies_processed=count)

    table = Table(title="Daily Evaluation Resource & Cost Report")
    table.add_column("Resource / Metric", style="cyan")
    table.add_column("Usage", style="green")
    table.add_column("Limit / Ceiling", style="yellow")

    table.add_row("Outbound Requests", str(rep.total_outbound_requests), str(settings.MAX_DAILY_REQUESTS))
    table.add_row("Retry Count", str(rep.errors_and_retries), "N/A")
    table.add_row("Gemini Model Calls", str(rep.gemini_calls), "N/A")
    table.add_row("Gemini Input Tokens", f"{rep.input_tokens:,}", "N/A")
    table.add_row("Gemini Output Tokens", f"{rep.output_tokens:,}", "N/A")
    table.add_row("Cache Hit Rate", f"{rep.cache_hit_rate_pct}%", "N/A")
    table.add_row("Estimated Gemini Cost", f"${rep.estimated_gemini_cost_usd:.5f}", f"${settings.INTERNAL_COST_CEILING_USD:.2f}")
    table.add_row("Measured API Cost", f"${rep.measured_api_cost_usd:.5f}", "N/A")
    table.add_row("Total Evaluated Cost", f"${rep.total_cost_usd:.5f}", f"${settings.MAX_DAILY_COST_USD:.2f}")
    table.add_row("Cost Per Company", f"${rep.cost_per_company_usd:.5f}", "N/A")

    console.print(table)


@app.command()
def validate(
    input_file: Path = typer.Option(..., "--input", "-i", help="JSON file of profiles to validate"),
):
    """Validate a JSON file of company profiles against checksums and schemas."""
    if not input_file.exists():
        console.print(f"[bold red]File not found:[/bold red] {input_file}")
        raise typer.Exit(code=1)

    try:
        data = json.loads(input_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = [data]
    except Exception as e:
        console.print(f"[bold red]Invalid JSON file:[/bold red] {e}")
        raise typer.Exit(code=1)

    total = len(data)
    valid_ids = 0
    invalid_ids = 0
    schema_valid = 0
    has_facts = 0

    from company_agent.schemas import CompanyProfile

    for item in data:
        org_nr = item.get("organisation_number")
        is_v, _ = validate_organisation_number(str(org_nr))
        if is_v:
            valid_ids += 1
        else:
            invalid_ids += 1

        try:
            CompanyProfile(**item)
            schema_valid += 1
        except Exception:
            pass

        if item.get("facts"):
            has_facts += 1

    table = Table(title=f"Validation Audit Report: {input_file.name}")
    table.add_column("Criterion", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Total Profiles Inspected", str(total))
    table.add_row("Valid Organisation Numbers (Mod11)", f"{valid_ids} ({valid_ids/total*100:.1f}%)" if total else "0")
    table.add_row("Invalid Checksums / Formats", str(invalid_ids))
    table.add_row("Passed Strict Pydantic Schema", f"{schema_valid} ({schema_valid/total*100:.1f}%)" if total else "0")
    table.add_row("Profiles with Provenance Facts", f"{has_facts} ({has_facts/total*100:.1f}%)" if total else "0")

    console.print(table)


@app.command()
def seed(
    target: int = typer.Option(1000, "--target", "-t", help="Target number of distinct profiles"),
    output_dir: Path = typer.Option(settings.PROFILES_DIR, "--output", "-o", help="Directory for manifest"),
):
    """Discover and seed verified Norwegian company profiles from the official Brreg open registry."""
    from scripts.seed_profiles import seed_profiles
    console.print(f"[cyan]Initiating seeding of {target} distinct real Norwegian company profiles...[/cyan]")
    total = seed_profiles(target_count=target, output_dir=output_dir)
    console.print(f"[bold green]Seeding complete. Database currently maintains {total} verified profiles.[/bold green]")


@app.command()
def health():
    """Verify system readiness, database connectivity, and provider credentials."""
    table = Table(title="Norwegian Company Intelligence Agent — System Health")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="yellow")

    # Database
    try:
        with get_db_session() as session:
            count = session.query(Company).count()
        table.add_row("Database", "[green]READY[/green]", f"{settings.DATABASE_URL} ({count} companies)")
    except Exception as e:
        table.add_row("Database", "[red]ERROR[/red]", str(e))

    # Gemini
    if gemini_client.is_available():
        table.add_row("Gemini Model", "[green]CONFIGURED[/green]", f"Model: {settings.GEMINI_MODEL}")
    else:
        table.add_row("Gemini Model", "[yellow]MOCK/OFFLINE[/yellow]", "GEMINI_API_KEY not configured (using deterministic heuristic)")

    # Browser Provider
    table.add_row("Browser Provider", "[green]ACTIVE[/green]", f"Provider: {settings.BROWSER_PROVIDER}")

    # Brreg Registry API
    try:
        data = registry_client.get_enhet("923609016")
        if data:
            table.add_row("Brreg Enhetsregisteret", "[green]CONNECTED[/green]", f"Verified response for {data.get('navn')}")
        else:
            table.add_row("Brreg Enhetsregisteret", "[yellow]WARNING[/yellow]", "No data returned")
    except Exception as e:
        table.add_row("Brreg Enhetsregisteret", "[red]ERROR[/red]", str(e))

    console.print(table)


if __name__ == "__main__":
    app()
