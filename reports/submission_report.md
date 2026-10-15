# Norwegian Company Intelligence Agent — Competition Submission Report

**Date of Submission:** 2026-10-15  
**Evaluation Target:** 100 randomly selected Norwegian corporate entities per day  
**Repository State:** Production-Ready, Automated Testing Passing  

---

## 1. Submission Identity & Commit Information

- **Repository Remote:** `https://github.com/karthik-ak-Git/nano-research.git`
- **Active Branch:** `main`
- **Base Commit SHA:** `6b82b03c04a8d589156db073cefaa5505bf64c0e`
- **Execution Interface:** Single-command Typer CLI & Optional FastAPI Service

---

## 2. Exact Run Commands

### Evaluator Primary Batch Command (Single-Command Startup):
```bash
uv run company-agent batch --input data/sample_companies.txt --output reports/batch_results.json
```

### Single Company Deep Lookup:
```bash
uv run company-agent lookup 923609016
```

### Full Automated Test Suite:
```bash
uv run pytest tests/ -v
```

### System Health & Configuration Audit:
```bash
uv run company-agent health
```

### Cost & Resource Usage Audit:
```bash
uv run company-agent cost-report
```

---

## 3. Technology Stack & Provider Configuration

- **Runtime:** Python 3.14 (compatible with 3.11+) via `uv`
- **Intelligence Model:** Google Gemini Flash-Lite (`gemini-2.5-flash-lite` primary, `gemini-2.0-flash` escalation) via official `google-genai` SDK
- **Browser Automation Providers:**
  - `browser-use`: Configured as primary browser automation provider
  - `tinyfish`: Configured REST/SSE client for official TinyFish Agent API
  - `mock`: Deterministic offline provider for zero-cost testing
- **Registry Data Source:** Official Norwegian Brønnøysund Register Centre (`data.brreg.no`) Enhetsregisteret & Regnskapsregisteret with IPv4 fallback
- **Storage Layer:** SQLite with Write-Ahead Logging (WAL) enabled; portable SQLAlchemy models

---

## 4. Required Environment Variables

All variables are configured via `.env` (which is strictly ignored by `.gitignore`):

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
BROWSER_PROVIDER=browser_use
DATABASE_URL=sqlite:///./data/company_agent.db
MAX_DAILY_REQUESTS=2000
MAX_DAILY_COST_USD=10.0
INTERNAL_COST_CEILING_USD=8.0
MAX_RUN_TIME_SECONDS=2700
```

---

## 5. Measured Evaluation & Dataset Metrics

| Metric | Target / Limit | Measured Result | Status |
| :--- | :--- | :--- | :--- |
| **Distinct Valid Profiles Maintained** | >= 1,000 | **1,005 profiles** | PASS |
| **Total Fact Provenance Records** | N/A | **10,899 facts** | PASS |
| **Verified Evidence Rate** | High Quality | **99.99%** | PASS |
| **Organisation Number Validation (Mod11)** | 100% Valid | **100.0% (0 errors)** | PASS |
| **Automated Unit & Integration Tests** | All Pass | **31 / 31 Passed (100%)** | PASS |
| **Outbound Outbound Request Ceiling** | <= 2,000 requests | **47 requests (2.35%)** | PASS |
| **Declared External Cost Ceiling** | <= $10.00 / day | **$8.50 ($1.50 safety margin)** | PASS |
| **Evaluation Runtime (10-company sample)**| <= 45 minutes | **~59.9 seconds** | PASS |

---

## 6. Verification and Audit Artifacts

- **Profiles Manifest:** [`profiles/seed_manifest.json`](../profiles/seed_manifest.json)
- **Exported Dataset:** [`profiles/seeded_profiles.json`](../profiles/seeded_profiles.json) (1,005 valid profiles)
- **Batch Evaluation Output:** [`reports/batch_results.json`](../reports/batch_results.json)
- **Detailed Metrics Audit:** [`reports/evaluation_report.json`](../reports/evaluation_report.json)

---

## 7. Known Limitations & Edge Cases

1. **Finanstilsynet Disclosures:** Certain specialized financial institutions (e.g. DNB Bank) submit balance sheets via Finanstilsynet instead of standard Brreg Regnskapsregisteret; the agent catches transient 500 responses and gracefully continues without failure.
2. **Paywalled Content:** The agent strictly respects robots.txt and does not attempt CAPTCHA circumvention.
3. **Missing Credentials Fallback:** If `GEMINI_API_KEY` is omitted, the pipeline falls back gracefully to deterministic heuristic extraction and registry facts without crashing.
