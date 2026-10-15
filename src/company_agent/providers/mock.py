"""Deterministic offline mock browser and web research provider."""

import time
from typing import Optional
from company_agent.providers.base import BaseBrowserProvider, BrowserResult
from company_agent.budgets import budget_manager


class MockBrowserProvider(BaseBrowserProvider):
    """Deterministic offline browser provider for zero-cost testing and offline evaluations."""

    @property
    def name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return True

    async def navigate_and_extract(
        self,
        url: str,
        goal: str,
        timeout: float = 30.0,
    ) -> BrowserResult:
        """Simulates browser navigation and extraction deterministically without network spend."""
        start_time = time.time()
        budget_manager.check_budget_available()

        # Track mock request in budget manager
        budget_manager.record_request(
            provider="mock_browser",
            endpoint=url,
            status_code=200,
        )

        elapsed = time.time() - start_time

        # Generate realistic mocked web content depending on target URL
        if "equinor" in url.lower():
            text = (
                "Equinor ASA is an international energy company committed to creating value through "
                "the safe and efficient production of oil, gas and renewable energy. "
                "Organisation number: 923 609 016. Registered office: Forusbeen 50, 4035 Stavanger, Norway. "
                "Chief Executive Officer: Anders Opedal. Contact: +47 51 99 00 00."
            )
            title = "Equinor - Energy for people and progress"
        elif "telenor" in url.lower():
            text = (
                "Telenor ASA connects people to what matters most. Organisation number: 976 633 408. "
                "Headquarters: Snarøyveien 30, 1360 Fornebu, Norway. "
                "CEO: Sigve Brekke. Telecommunications, mobile, fixed broadband and TV."
            )
            title = "Telenor Group - Telecom and Digital Services"
        elif "dnb" in url.lower():
            text = (
                "DNB Bank ASA is Norway's largest financial services group. "
                "Organisation number: 984 851 006. Dronning Eufemias gate 30, 0191 Oslo. "
                "CEO: Kjerstin Braathen."
            )
            title = "DNB - Norway's largest bank"
        elif "kongsberg" in url.lower():
            text = (
                "Kongsberg Gruppen ASA is an international, knowledge-based group that delivers high-technology systems. "
                "Organisation number: 943 752 907. Kirkegårdsveien 45, 3616 Kongsberg, Norway. "
                "CEO: Geir Håøy."
            )
            title = "KONGSBERG - Extreme performance for extreme conditions"
        elif "orkla" in url.lower():
            text = (
                "Orkla ASA is a leading supplier of branded consumer goods. "
                "Organisation number: 910 747 711. Drammensveien 149, 0277 Oslo. "
                "CEO: Nils K. Selte."
            )
            title = "Orkla - The home of brands"
        else:
            text = (
                f"Official company homepage at {url}. Verified Norwegian commercial enterprise. "
                "Contact us for services, commercial operations, and corporate governance inquiries."
            )
            title = "Official Corporate Website"

        return BrowserResult(
            url=url,
            status_code=200,
            title=title,
            cleaned_text=text,
            structured_data={"simulated": True, "goal": goal},
            execution_time_seconds=elapsed,
            provider_name=self.name,
        )
