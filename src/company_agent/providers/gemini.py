"""Google Gemini model client using official google-genai SDK.

Features:
- Configurable models (Gemini Flash-Lite default, Gemini Flash fallback)
- Strict JSON output schema enforcement
- Token tracking and cost accounting via ResourceBudgetManager
- Deduplication and token budgeting per company
- Dry-run / mock fallback when credentials are not supplied
"""

import json
import re
from typing import Dict, Any, List, Optional
from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.budgets import budget_manager, BudgetExceededError
from company_agent.costs import calculate_gemini_cost
from company_agent.cache import cache, hash_content


class GeminiClient:
    """Official Google GenAI Gemini integration for extraction, classification, and explanation."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.primary_model = settings.GEMINI_MODEL
        self.fallback_model = settings.GEMINI_FALLBACK_MODEL
        self._client = None

        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning("Could not initialize Google GenAI client: %s", e)

    def is_available(self) -> bool:
        """Returns True if Google GenAI SDK and GEMINI_API_KEY are configured."""
        return bool(self._client is not None and self.api_key and len(self.api_key.strip()) > 5)

    def extract_structured_facts(
        self,
        company_name: str,
        org_nr: str,
        evidence_snippets: List[str],
        escalate: bool = False,
    ) -> Dict[str, Any]:
        """Extracts structured company facts and concise explanations from raw evidence passages.

        Args:
            company_name: Verified legal name from registry
            org_nr: Validated 9-digit organisation number
            evidence_snippets: Deduplicated, cleaned text snippets (max 5)
            escalate: If True, uses the stronger fallback model (e.g. gemini-2.0-flash)

        Returns:
            Dict containing extracted facts, confidence scores, and brief explanations.
        """
        model_name = self.fallback_model if escalate else self.primary_model

        # Token & cost safety check before sending request
        budget_manager.check_budget_available(cost_estimate=0.001)

        # Truncate and bound snippets to token budget
        bounded_snippets = evidence_snippets[: settings.MAX_SNIPPETS_PER_MODEL_CALL]
        combined_text = "\n---\n".join(bounded_snippets)[:3000]

        prompt_cache_key = f"gemini:extract:{org_nr}:{hash_content(combined_text)}"
        cached_result = cache.get(prompt_cache_key)
        if cached_result is not None:
            return cached_result

        # If offline / mock / dry-run or no API key, return deterministic heuristic extraction
        if not self.is_available() or settings.DRY_RUN:
            return self._heuristic_mock_extraction(company_name, org_nr, bounded_snippets)

        prompt = (
            f"You are a strict data-extraction engine for Norwegian corporate intelligence.\n"
            f"Target Company: {company_name} (Org Nr: {org_nr})\n\n"
            f"Rules:\n"
            f"1. Extract ONLY facts directly evidenced in the provided passages.\n"
            f"2. Never hallucinate, extrapolate, or guess dates, currencies, or numbers.\n"
            f"3. Return strict JSON matching the schema below.\n"
            f"4. For description, you MUST provide 'description_excerpt' containing the exact verbatim sentence from the passages supporting it.\n\n"
            f"Evidence Passages:\n{combined_text}\n\n"
            f"Schema format:\n"
            f"{{\n"
            f'  "website": string or null,\n'
            f'  "management_leadership": [string],\n'
            f'  "employee_count": integer or null,\n'
            f'  "description": string or null,\n'
            f'  "description_excerpt": string or null,\n'
            f'  "business_activities": [string],\n'
            f'  "explanation": string\n'
            f"}}"
        )

        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            raw_text = response.text or "{}"
            parsed = self._clean_and_parse_json(raw_text)

            # Strict evidence grounding verification: reject ungrounded or fabricated facts
            if parsed.get("description"):
                desc_text = str(parsed["description"]).strip()
                excerpt = str(parsed.get("description_excerpt") or "").strip()
                if excerpt and excerpt.lower() in combined_text.lower():
                    parsed["description_excerpt"] = excerpt
                else:
                    # Check if key words of description appear in the evidence text
                    words = [w for w in re.findall(r"\w+", desc_text.lower()) if len(w) > 4]
                    matching_words = [w for w in words if w in combined_text.lower()]
                    if words and (len(matching_words) / len(words) >= 0.5):
                        # Locate the best matching snippet as excerpt
                        for snip in bounded_snippets:
                            if any(w in snip.lower() for w in matching_words):
                                parsed["description_excerpt"] = snip[:300]
                                break
                    else:
                        logger.warning("Rejecting unsupported description from model: not evidenced in passages")
                        parsed["description"] = None
                        parsed["description_excerpt"] = None

            if parsed.get("website"):
                cand_domain = re.sub(r"^https?:\/\/", "", str(parsed["website"])).split("/")[0].lower()
                if cand_domain and cand_domain not in combined_text.lower():
                    logger.warning("Rejecting unsupported website '%s': not evidenced in source passages", parsed["website"])
                    parsed["website"] = None

            if parsed.get("employee_count") is not None:
                emp_str = str(parsed["employee_count"])
                if emp_str not in combined_text:
                    logger.warning("Rejecting unsupported employee_count '%s': not evidenced in source passages", emp_str)
                    parsed["employee_count"] = None

            # Extract token usage metadata from response if available
            in_tokens = 0
            out_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                in_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                out_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            else:
                # Estimate tokens deterministically (approx 4 chars/token)
                in_tokens = len(prompt) // 4
                out_tokens = len(raw_text) // 4

            cost = calculate_gemini_cost(model_name, in_tokens, out_tokens)
            budget_manager.record_gemini_usage(
                model=model_name,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                estimated_cost=cost,
            )

            cache.set(prompt_cache_key, parsed, ttl_seconds=86400 * 7)
            return parsed

        except BudgetExceededError:
            raise
        except Exception as e:
            logger.error("Gemini API call failed (%s): %s. Falling back to heuristic extraction.", model_name, e)
            return self._heuristic_mock_extraction(company_name, org_nr, bounded_snippets)

    def _clean_and_parse_json(self, raw: str) -> Dict[str, Any]:
        """Cleans Markdown backticks and safely parses JSON."""
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            return {}

    def _heuristic_mock_extraction(
        self,
        company_name: str,
        org_nr: str,
        snippets: List[str],
    ) -> Dict[str, Any]:
        """Deterministic, zero-token heuristic extraction used in mock mode and fallback."""
        if not snippets:
            return {
                "website": None,
                "management_leadership": [],
                "employee_count": None,
                "description": None,
                "description_excerpt": None,
                "business_activities": [],
                "explanation": f"No web evidence passages retrieved for {company_name}.",
            }

        full_text = " ".join(snippets)
        
        # CEO / Management pattern
        ceo_match = re.search(r"(?:ceo|daglig leder|chief executive officer)[:\s]+([A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+)+)", full_text, re.IGNORECASE)
        management = [ceo_match.group(1)] if ceo_match else []

        # Website pattern
        web_match = re.search(r"(?:https?:\/\/|www\.)([a-zA-Z0-9_\-\.]+\.[a-z]{2,4})", full_text)
        website = f"https://{web_match.group(1)}" if web_match else None

        # Employee count pattern
        emp_match = re.search(r"(?:employees|ansatte)[:\s]+(\d+)", full_text, re.IGNORECASE)
        employee_count = int(emp_match.group(1)) if emp_match else None

        desc = None
        desc_excerpt = None
        for snip in snippets:
            for sent in snip.split("."):
                s = sent.strip()
                if len(s) > 20 and (company_name.lower() in s.lower() or any(k in s.lower() for k in ("virksomhet", "tjenester", "selskap", "leverer", "tilbyr", "produserer", "international", "energy"))):
                    desc = s + "."
                    desc_excerpt = s
                    break
            if desc:
                break

        if not desc and snippets:
            first_sent = snippets[0].split(".")[0].strip()
            if len(first_sent) > 25:
                desc = first_sent + "."
                desc_excerpt = first_sent

        return {
            "website": website,
            "management_leadership": management,
            "employee_count": employee_count,
            "description": desc,
            "description_excerpt": desc_excerpt,
            "business_activities": [],
            "explanation": f"Profile extracted using verified evidence snippets for {company_name}." if desc else f"No evidenced operations text found for {company_name}.",
        }


# Global Gemini client
gemini_client = GeminiClient()
