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

            # If Gemini API key is configured, use LangChain or native ChatGoogleGenerativeAI if available
            # Otherwise run lightweight extraction or return informative error
            if not settings.GEMINI_API_KEY:
                # Return documented mock-assisted result or failure
                elapsed = time.time() - start_time
                return BrowserResult(
                    url=url,
                    provider_name=self.name,
                    execution_time_seconds=elapsed,
                    error="GEMINI_API_KEY not configured for browser-use agent reasoning",
                )

            # Run agent asynchronously
            # Note: For production reliability in environments without headless Chrome installed,
            # we handle browser launch errors gracefully
            try:
                agent = Agent(task=task_description)
                history = await asyncio.wait_for(agent.run(), timeout=timeout)
                elapsed = time.time() - start_time
                return BrowserResult(
                    url=url,
                    status_code=200,
                    provider_name=self.name,
                    cleaned_text=str(history),
                    execution_time_seconds=elapsed,
                )
            except Exception as e:
                elapsed = time.time() - start_time
                logger.warning("Browser-use execution exception for %s: %s", url, e)
                return BrowserResult(
                    url=url,
                    provider_name=self.name,
                    execution_time_seconds=elapsed,
                    error=str(e),
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
