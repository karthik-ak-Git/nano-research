"""Base interface for browser automation providers."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class BrowserResult(BaseModel):
    """Result returned by a browser navigation or automation run."""
    url: str
    status_code: int = 200
    title: Optional[str] = None
    html_content: Optional[str] = None
    cleaned_text: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    execution_time_seconds: float = 0.0
    provider_name: str = "base"
    error: Optional[str] = None


class BaseBrowserProvider(ABC):
    """Abstract interface common to Browser Use, TinyFish, and Mock providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name identifier of the provider."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if provider requirements and credentials are met."""
        pass

    @abstractmethod
    async def navigate_and_extract(
        self,
        url: str,
        goal: str,
        timeout: float = 30.0,
    ) -> BrowserResult:
        """Navigates to URL and extracts relevant content fulfilling goal."""
        pass
