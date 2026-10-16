"""Central resource budget manager for hard execution and cost limits.

Enforces:
- 45 minutes maximum execution time per daily evaluation.
- Maximum 2,000 outbound requests ceiling (including retries).
- $10.00 hard external API cost ceiling (with $8.00 internal safety margin).
- Thread-safe and async-safe request and token accounting.
- Audit persistence to SQLite/Postgres.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from company_agent.config import settings
from company_agent.logging_config import logger


class BudgetExceededError(RuntimeError):
    """Raised when an execution or resource budget limit has been reached."""
    pass


class ResourceBudgetManager:
    """Thread-safe resource budget manager shared across all pipeline components."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ResourceBudgetManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        max_requests: Optional[int] = None,
        max_cost_usd: Optional[float] = None,
        internal_cost_ceiling_usd: Optional[float] = None,
        max_time_seconds: Optional[int] = None,
        run_id: Optional[str] = None,
    ):
        if getattr(self, "_initialized", False):
            return

        self.max_requests = max_requests or settings.MAX_DAILY_REQUESTS
        self.max_cost_usd = max_cost_usd or settings.MAX_DAILY_COST_USD
        self.internal_cost_ceiling = internal_cost_ceiling_usd or settings.INTERNAL_COST_CEILING_USD
        self.max_time_seconds = max_time_seconds or settings.MAX_RUN_TIME_SECONDS
        self.run_id = run_id or f"run_{int(time.time())}"

        self.start_time = time.time()
        self.deadline = self.start_time + self.max_time_seconds

        # Counters
        self.request_count = 0
        self.retry_count = 0
        self.gemini_call_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.estimated_cost_usd = 0.0
        self.measured_cost_usd = 0.0
        self.cache_hits = 0
        self.cache_misses = 0

        self.is_stopped = False
        self.stop_reason: Optional[str] = None

        self._counter_lock = threading.Lock()
        self._initialized = True

    def reset(self, run_id: Optional[str] = None) -> None:
        """Resets counters for a new evaluation run."""
        with self._counter_lock:
            self.run_id = run_id or f"run_{int(time.time())}"
            self.start_time = time.time()
            self.deadline = self.start_time + self.max_time_seconds
            self.request_count = 0
            self.retry_count = 0
            self.gemini_call_count = 0
            self.input_tokens = 0
            self.output_tokens = 0
            self.estimated_cost_usd = 0.0
            self.measured_cost_usd = 0.0
            self.cache_hits = 0
            self.cache_misses = 0
            self.is_stopped = False
            self.stop_reason = None

    def check_budget_available(self, cost_estimate: float = 0.0) -> None:
        """Validates that sufficient request, time, and cost budgets remain.

        Raises BudgetExceededError if budget ceiling is reached.
        """
        with self._counter_lock:
            # Check time deadline (reserve 60s for persistence and graceful shutdown)
            remaining_time = self.deadline - time.time()
            if remaining_time <= 60.0:
                self.is_stopped = True
                self.stop_reason = f"Time budget expiring: {remaining_time:.1f}s remaining (limit {self.max_time_seconds}s)"
                raise BudgetExceededError(self.stop_reason)

            # Check outbound requests ceiling
            if self.request_count >= self.max_requests:
                self.is_stopped = True
                self.stop_reason = f"Request budget exhausted: {self.request_count}/{self.max_requests} requests made"
                raise BudgetExceededError(self.stop_reason)

            # Check financial cost ceiling
            projected_cost = self.estimated_cost_usd + cost_estimate
            if projected_cost >= self.internal_cost_ceiling:
                self.is_stopped = True
                self.stop_reason = (
                    f"Cost budget safety ceiling reached: ${projected_cost:.4f} "
                    f"(ceiling: ${self.internal_cost_ceiling:.2f}, hard limit: ${self.max_cost_usd:.2f})"
                )
                raise BudgetExceededError(self.stop_reason)

    def record_request(
        self,
        provider: str,
        endpoint: str,
        status_code: Optional[int] = None,
        retries: int = 0,
        persist: bool = True,
    ) -> None:
        """Records an outbound network request, including retries, and persists to DB."""
        with self._counter_lock:
            self.request_count += (1 + retries)
            self.retry_count += retries

        if not persist or self.run_id.startswith("test"):
            return

        # Async or direct DB persistence for auditing
        try:
            from company_agent.database import get_db_session
            from company_agent.models import RequestUsage
            with get_db_session() as session:
                session.add(
                    RequestUsage(
                        run_id=self.run_id,
                        provider=provider,
                        endpoint=endpoint[:500],
                        status_code=status_code,
                        retries=retries,
                    )
                )
        except Exception as e:
            logger.debug("Failed to persist request usage to DB: %s", e)

    def record_gemini_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
        measured_cost: float = 0.0,
        persist: bool = True,
    ) -> None:
        """Records Gemini token and cost metrics."""
        with self._counter_lock:
            self.gemini_call_count += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.estimated_cost_usd += estimated_cost
            if measured_cost > 0.0:
                self.measured_cost_usd += measured_cost

        if not persist or self.run_id.startswith("test"):
            return

        try:
            from company_agent.database import get_db_session
            from company_agent.models import ModelUsage
            with get_db_session() as session:
                session.add(
                    ModelUsage(
                        run_id=self.run_id,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        estimated_cost=estimated_cost,
                        measured_cost=measured_cost,
                    )
                )
        except Exception as e:
            logger.debug("Failed to persist model usage to DB: %s", e)

    def record_cache_hit(self) -> None:
        with self._counter_lock:
            self.cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._counter_lock:
            self.cache_misses += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Returns snapshot of current resource metrics."""
        with self._counter_lock:
            elapsed = time.time() - self.start_time
            total_cache = self.cache_hits + self.cache_misses
            hit_rate = (self.cache_hits / total_cache * 100.0) if total_cache > 0 else 0.0
            return {
                "run_id": self.run_id,
                "elapsed_seconds": round(elapsed, 2),
                "remaining_seconds": max(0.0, round(self.deadline - time.time(), 2)),
                "request_count": self.request_count,
                "request_limit": self.max_requests,
                "retry_count": self.retry_count,
                "gemini_call_count": self.gemini_call_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_cost_usd": round(self.estimated_cost_usd, 5),
                "measured_cost_usd": round(self.measured_cost_usd, 5),
                "internal_cost_ceiling_usd": self.internal_cost_ceiling,
                "hard_cost_limit_usd": self.max_cost_usd,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_rate_pct": round(hit_rate, 2),
                "is_stopped": self.is_stopped,
                "stop_reason": self.stop_reason,
            }


# Global singleton instance
budget_manager = ResourceBudgetManager()
