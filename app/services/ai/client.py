"""
Anthropic AI client wrapper for invoice processing.

Wraps the raw Anthropic AsyncAnthropic SDK with production concerns:
retry with exponential backoff and jitter, a circuit breaker, per-call
and daily cost tracking, and cost-limit enforcement.

Usage:
    client = AnthropicClient(anthropic.AsyncAnthropic(api_key=...), settings)
    result: AICallResult = await client.complete(system_prompt, user_msg, prompt_version="v1")
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from app.config import Settings
from app.core.exceptions import (
    CircuitBreakerOpenError,
    CostLimitExceededError,
    ExtractionError,
)

logger = logging.getLogger(__name__)


class AICallResult(BaseModel):
    """
    Result of a single AI API call, including cost and performance metadata.

    Every field needed for evaluation, cost reporting, and debugging is
    captured here so callers never need to inspect raw SDK objects.
    """

    content: str = Field(..., description="Raw text content returned by the AI model")
    input_tokens: int = Field(..., ge=0, description="Tokens consumed by the input prompt")
    output_tokens: int = Field(..., ge=0, description="Tokens in the AI response")
    cost_usd: float = Field(..., ge=0.0, description="Estimated cost of this call in USD")
    latency_ms: float = Field(..., ge=0.0, description="End-to-end API call latency in ms")
    model: str = Field(..., description="Model identifier used for this call")
    prompt_version: str = Field(..., description="Prompt template version tag")


class CircuitBreaker:
    """
    Tracks consecutive final failures and rejects calls when a threshold is breached.

    A "failure" is counted only after all retry attempts are exhausted.
    The breaker resets automatically after reset_timeout_seconds.
    """

    def __init__(
        self,
        failure_threshold: int,
        reset_timeout_seconds: float,
    ) -> None:
        """
        Args:
            failure_threshold: Number of failures before the circuit opens.
            reset_timeout_seconds: Seconds until the open circuit resets.
        """
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout_seconds
        self._failure_count: int = 0
        self._opened_at: datetime | None = None

    def check(self) -> None:
        """
        Assert the circuit is closed.

        Raises:
            CircuitBreakerOpenError: If the circuit is open and the reset
                timeout has not elapsed.
        """
        if self._opened_at is None:
            return
        elapsed = (datetime.now(UTC) - self._opened_at).total_seconds()
        if elapsed >= self._reset_timeout:
            self._failure_count = 0
            self._opened_at = None
        else:
            remaining = self._reset_timeout - elapsed
            raise CircuitBreakerOpenError(
                f"AI circuit breaker open — retry in {remaining:.0f}s",
                context={"reset_in_seconds": round(remaining, 1)},
            )

    def record_success(self) -> None:
        """Reset failure state after a successful call."""
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """
        Record a final failure and open the circuit if the threshold is reached.

        Args: none — state is purely internal.
        """
        self._failure_count += 1
        if self._failure_count >= self._threshold and self._opened_at is None:
            self._opened_at = datetime.now(UTC)
            logger.warning(
                "AI circuit breaker opened",
                extra={
                    "failure_count": self._failure_count,
                    "threshold": self._threshold,
                    "reset_timeout_seconds": self._reset_timeout,
                },
            )

    @property
    def is_open(self) -> bool:
        """True if the circuit is currently open (no calls allowed)."""
        if self._opened_at is None:
            return False
        elapsed = (datetime.now(UTC) - self._opened_at).total_seconds()
        return elapsed < self._reset_timeout

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count


class AnthropicClient:
    """
    Production-grade async Anthropic client for invoice processing.

    Features:
    - Retry with exponential backoff and jitter (configurable attempts)
    - Circuit breaker (opens after N final failures in a window)
    - Per-call cost calculation and daily cost aggregation
    - Cost-limit enforcement (raises before making a call that would exceed budget)

    All configuration is injected via Settings; no hardcoded values.
    """

    def __init__(
        self,
        anthropic_client: anthropic.AsyncAnthropic,
        settings: Settings,
    ) -> None:
        """
        Args:
            anthropic_client: Pre-built async Anthropic SDK client.
            settings: Application settings (model, cost limits, retry config).
        """
        self._client = anthropic_client
        self._settings = settings
        self._daily_cost_usd: float = 0.0
        self._daily_call_count: int = 0
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=settings.ai_circuit_breaker_threshold,
            reset_timeout_seconds=settings.ai_circuit_breaker_reset_seconds,
        )

    @property
    def daily_cost_usd(self) -> float:
        """Total USD cost incurred by this client instance today."""
        return self._daily_cost_usd

    @property
    def daily_call_count(self) -> int:
        """Number of successful AI calls made by this client instance."""
        return self._daily_call_count

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Expose the circuit breaker for inspection in tests and metrics."""
        return self._circuit_breaker

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        prompt_version: str,
        max_tokens: int = 1024,
    ) -> AICallResult:
        """
        Execute a completion request with retry, circuit breaker, and cost tracking.

        Args:
            system_prompt: Instructions for the AI model role and output format.
            user_message: The content to process (e.g. invoice text).
            prompt_version: Version tag used for evaluation and observability.
            max_tokens: Maximum tokens allowed in the response.

        Returns:
            AICallResult containing the response content and all cost/latency metadata.

        Raises:
            CostLimitExceededError: Daily cost budget exhausted.
            CircuitBreakerOpenError: Circuit is open due to repeated failures.
            ExtractionError: All retry attempts failed.
        """
        self._check_cost_limit()
        self._circuit_breaker.check()

        ai_call_result = await self._execute_with_retry(
            system_prompt=system_prompt,
            user_message=user_message,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
        )

        self._circuit_breaker.record_success()
        self._daily_cost_usd += ai_call_result.cost_usd
        self._daily_call_count += 1

        logger.info(
            "AI call completed",
            extra={
                "model": ai_call_result.model,
                "input_tokens": ai_call_result.input_tokens,
                "output_tokens": ai_call_result.output_tokens,
                "cost_usd": ai_call_result.cost_usd,
                "latency_ms": ai_call_result.latency_ms,
                "prompt_version": ai_call_result.prompt_version,
                "daily_cost_usd": round(self._daily_cost_usd, 6),
                "daily_call_count": self._daily_call_count,
            },
        )

        return ai_call_result

    def _check_cost_limit(self) -> None:
        """Raise CostLimitExceededError if the daily budget is exhausted."""
        if self._daily_cost_usd >= self._settings.max_daily_cost_usd:
            raise CostLimitExceededError(
                f"Daily cost limit of ${self._settings.max_daily_cost_usd:.2f} reached"
                f" (spent ${self._daily_cost_usd:.4f})",
                context={
                    "daily_cost_usd": self._daily_cost_usd,
                    "limit_usd": self._settings.max_daily_cost_usd,
                },
            )

    async def _execute_with_retry(
        self,
        system_prompt: str,
        user_message: str,
        prompt_version: str,
        max_tokens: int,
    ) -> AICallResult:
        """Attempt the API call up to ai_max_retries times with backoff."""
        last_error: Exception | None = None
        max_attempts = self._settings.ai_max_retries
        base_delay = self._settings.ai_retry_base_delay_seconds

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._single_attempt(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    prompt_version=prompt_version,
                    max_tokens=max_tokens,
                )
            except anthropic.AuthenticationError as exc:
                # Auth errors are never retryable — fail immediately.
                self._circuit_breaker.record_failure()
                raise ExtractionError(
                    f"AI authentication failed: {exc}",
                    context={"prompt_version": prompt_version},
                ) from exc
            except anthropic.APIError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.warning(
                    "AI call failed, retrying",
                    extra={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "delay_seconds": round(delay, 2),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "prompt_version": prompt_version,
                    },
                )
                await asyncio.sleep(delay)

        self._circuit_breaker.record_failure()
        raise ExtractionError(
            f"AI call failed after {max_attempts} attempt(s)",
            context={
                "prompt_version": prompt_version,
                "error": str(last_error),
                "attempts": max_attempts,
            },
        ) from last_error

    async def _single_attempt(
        self,
        system_prompt: str,
        user_message: str,
        prompt_version: str,
        max_tokens: int,
    ) -> AICallResult:
        """Make one raw API call and return an AICallResult."""
        start_ms = time.monotonic() * 1000

        message = await self._client.messages.create(
            model=self._settings.ai_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        latency_ms = time.monotonic() * 1000 - start_ms
        cost_usd = self._calculate_cost(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

        first_block = message.content[0]
        response_text = first_block.text if hasattr(first_block, "text") else ""

        return AICallResult(
            content=response_text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cost_usd=cost_usd,
            latency_ms=round(latency_ms, 2),
            model=self._settings.ai_model,
            prompt_version=prompt_version,
        )

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Compute the USD cost for a given token pair using Settings pricing."""
        return (
            input_tokens * self._settings.ai_cost_per_input_token_usd
            + output_tokens * self._settings.ai_cost_per_output_token_usd
        )

    def get_metrics(self) -> dict[str, Any]:
        """
        Return current cost and circuit-breaker metrics for the /metrics endpoint.

        Returns:
            Dict with daily_cost_usd, daily_call_count, limit_usd,
            utilisation_pct, and circuit_breaker_open.
        """
        limit = self._settings.max_daily_cost_usd
        utilisation = (self._daily_cost_usd / limit * 100) if limit > 0 else 0.0
        return {
            "daily_cost_usd": round(self._daily_cost_usd, 6),
            "daily_call_count": self._daily_call_count,
            "limit_usd": limit,
            "utilisation_pct": round(utilisation, 1),
            "circuit_breaker_open": self._circuit_breaker.is_open,
        }
