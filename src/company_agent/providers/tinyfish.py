"""TinyFish Agent API provider integration.

Official API specifications:
- Base URL: https://agent.tinyfish.ai
- Endpoint: POST /v1/automation/run
- Header: X-API-Key: $TINYFISH_API_KEY
- Request Payload: {"url": "<target>", "goal": "<objective>"}
- Documentation: https://agent.tinyfish.ai
"""

import time
from typing import Optional
import httpx
from company_agent.providers.base import BaseBrowserProvider, BrowserResult
from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.budgets import budget_manager


class TinyFishProvider(BaseBrowserProvider):
    """Browser agent provider utilizing the official TinyFish Agent REST API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.TINYFISH_API_KEY
        self.base_url = "https://agent.tinyfish.ai"

    @property
    def name(self) -> str:
        return "tinyfish"

    def is_available(self) -> bool:
        """Returns True only when a valid TINYFISH_API_KEY is supplied."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    async def navigate_and_extract(
        self,
        url: str,
        goal: str,
        timeout: float = 30.0,
    ) -> BrowserResult:
        """Calls the official TinyFish POST /v1/automation/run endpoint."""
        start_time = time.time()

        if not self.is_available():
            elapsed = time.time() - start_time
            return BrowserResult(
                url=url,
                provider_name=self.name,
                execution_time_seconds=elapsed,
                error="TINYFISH_API_KEY not configured. Set TINYFISH_API_KEY in environment or .env.",
            )

        budget_manager.check_budget_available()

        endpoint = f"{self.base_url}/v1/automation/run"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": settings.USER_AGENT,
        }
        payload = {
            "url": url,
            "goal": goal,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                budget_manager.record_request(
                    provider="tinyfish",
                    endpoint=endpoint,
                    status_code=resp.status_code,
                )

                elapsed = time.time() - start_time
                if resp.status_code == 200:
                    data = resp.json()
                    # TinyFish returns structured data or extracted text
                    extracted_text = data.get("result") or data.get("content") or str(data)
                    return BrowserResult(
                        url=url,
                        status_code=resp.status_code,
                        provider_name=self.name,
                        cleaned_text=str(extracted_text),
                        structured_data=data if isinstance(data, dict) else None,
                        execution_time_seconds=elapsed,
                    )
                elif resp.status_code == 401:
                    logger.error("TinyFish authentication failed: Invalid or expired X-API-Key")
                    return BrowserResult(
                        url=url,
                        status_code=resp.status_code,
                        provider_name=self.name,
                        execution_time_seconds=elapsed,
                        error="Unauthorized: Invalid TINYFISH_API_KEY",
                    )
                else:
                    return BrowserResult(
                        url=url,
                        status_code=resp.status_code,
                        provider_name=self.name,
                        execution_time_seconds=elapsed,
                        error=f"TinyFish API returned status {resp.status_code}: {resp.text[:200]}",
                    )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("TinyFish network exception: %s", e)
            return BrowserResult(
                url=url,
                provider_name=self.name,
                execution_time_seconds=elapsed,
                error=f"TinyFish connection error: {str(e)}",
            )
