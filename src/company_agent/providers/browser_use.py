"""Browser Use automation provider integration."""

import asyncio
import time
from typing import Optional
from company_agent.providers.base import BaseBrowserProvider, BrowserResult
from company_agent.config import settings
from company_agent.logging_config import logger
from company_agent.budgets import budget_manager


class BrowserUseProvider(BaseBrowserProvider):
    """Primary browser automation integration using the browser-use library."""

    @property
    def name(self) -> str:
        return "browser_use"

    def is_available(self) -> bool:
        """Checks if browser-use can be instantiated."""
        try:
            import browser_use
            return True
        except ImportError:
            return False

    async def navigate_and_extract(
        self,
        url: str,
        goal: str,
        timeout: float = 30.0,
    ) -> BrowserResult:
        """Executes a browser automation task using browser-use."""
        start_time = time.time()
        budget_manager.check_budget_available()

        try:
            # Check if LLM or API keys are configured for browser-use
            # Browser-use Agent requires an LLM or controller
            from browser_use import Agent

            # Create task description
            task_description = (
                f"Navigate to {url} and fulfill this objective: {goal}. "
                f"Extract the company legal name, organisation number, address, and description if visible."
            )

            # Record outbound request
            budget_manager.record_request(
                provider="browser_use",
                endpoint=url,
                status_code=200,
            )

            # If Gemini API key is configured, use ChatGoogle directly from browser_use
            # This completely avoids the cloud BU2 model and requires NO BROWSER_USE_API_KEY!
            if not settings.GEMINI_API_KEY:
                elapsed = time.time() - start_time
                return BrowserResult(
                    url=url,
                    provider_name=self.name,
                    execution_time_seconds=elapsed,
                    error="GEMINI_API_KEY not configured for browser-use agent reasoning",
                )

            import os
            os.environ["ANONYMIZED_TELEMETRY"] = "false"
            from browser_use import Agent, ChatGoogle

            try:
                # Use ChatGoogle wrapper with configured Gemini model and user's API key
                llm = ChatGoogle(
                    model=settings.GEMINI_MODEL,
                    api_key=settings.GEMINI_API_KEY,
                )
                agent = Agent(
                    task=task_description,
                    llm=llm,
                    flash_mode=True,
                )
                history = await asyncio.wait_for(agent.run(max_steps=5), timeout=timeout)
                elapsed = time.time() - start_time
                final_text = history.final_result() or str(history)
                return BrowserResult(
                    url=url,
                    status_code=200,
                    provider_name=self.name,
                    cleaned_text=final_text,
                    execution_time_seconds=elapsed,
                )
            except Exception as e:
                elapsed = time.time() - start_time
                logger.warning("Browser-use execution exception for %s: %s. Falling back to fast direct fetch.", url, e)
                # Resilient fallback: direct fetch using httpx + HTML extraction
                try:
                    import httpx
                    from company_agent.extraction import extract_clean_text_from_html
                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                        budget_manager.check_budget_available()
                        resp = await client.get(url, headers={"User-Agent": settings.USER_AGENT})
                        budget_manager.record_request(
                            provider="browser_use_fallback",
                            endpoint=url,
                            status_code=resp.status_code,
                        )
                        cleaned = extract_clean_text_from_html(resp.text)
                        return BrowserResult(
                            url=url,
                            status_code=resp.status_code,
                            provider_name=self.name,
                            cleaned_text=cleaned,
                            execution_time_seconds=time.time() - start_time,
                        )
                except Exception as fetch_err:
                    return BrowserResult(
                        url=url,
                        provider_name=self.name,
                        execution_time_seconds=elapsed,
                        error=f"Browser-use error: {e}; Fetch error: {fetch_err}",
                    )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("Failed to initialize browser-use: %s", e)
            return BrowserResult(
                url=url,
                provider_name=self.name,
                execution_time_seconds=elapsed,
                error=f"Browser-use provider error: {str(e)}",
            )
