"""
Configuration and telemetry for provider-backed (model) calls.

Everything that governs how the service talks to a model provider lives here so
operators can tune it without code changes, and so the model, temperature, and
retry posture are never hard-coded at a call site.

All values are read once at import time. See docs/OPERATIONS.md for the
deployment-facing description of each knob.
"""

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back on malformed input."""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back on malformed input."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Which model to call. Pinned by default: an unpinned alias would let the
# provider change inference behavior underneath a "deterministic-first" service.
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")

# Semantic inference and fallback mapping are classification tasks. Sampling
# adds nothing but variance, so the default is greedy decoding.
MODEL_TEMPERATURE = _env_float("MODEL_TEMPERATURE", 0.0)

# Per-call ceiling handed to the provider SDK. Without it, a hung connection is
# bounded only by the request-level budget.
MODEL_TIMEOUT_SECONDS = _env_float("MODEL_TIMEOUT_SECONDS", 15.0)

# Retries for transient provider failures (network, 5xx, rate limits).
MODEL_MAX_RETRIES = _env_int("MODEL_MAX_RETRIES", 2)
MODEL_RETRY_BACKOFF_SECONDS = _env_float("MODEL_RETRY_BACKOFF_SECONDS", 0.5)

# How many fields to describe in a single semantic-inference call. Batching is
# what keeps the stage to one or two round trips instead of one per field.
MODEL_SEMANTIC_BATCH_SIZE = max(1, _env_int("MODEL_SEMANTIC_BATCH_SIZE", 40))

# Untrusted page text forwarded per field as disambiguating context.
MODEL_CONTEXT_CHAR_LIMIT = max(0, _env_int("MODEL_CONTEXT_CHAR_LIMIT", 500))

# Ceiling applied to any confidence a model reports about its own output.
#
# Model self-reported confidence is not calibrated, so it must not be able to
# clear a review gate on its own. The default sits below MAPPING_REVIEW_THRESHOLD
# so every model-derived mapping is flagged for human review. Operators who
# accept the risk can raise it.
MODEL_CONFIDENCE_CEILING = _env_float("MODEL_CONFIDENCE_CEILING", 0.75)

# Confidence at or above which a mapping decision is written without review.
MAPPING_REVIEW_THRESHOLD = _env_float("MAPPING_REVIEW_THRESHOLD", 0.80)

# Total wall-clock budget for all provider work in one fill.
#
# This bounds the batch loop as a whole. Without it, worst-case provider time
# scales with batch count — each batch can spend
# MODEL_TIMEOUT_SECONDS * (MODEL_MAX_RETRIES + 1) plus backoff — so a document
# with many batches could hold its worker slot far longer than the request
# budget implies. The API grants the same allowance on top of its parsing
# budget, so the two stay in step.
SEMANTIC_TIMEOUT_SECONDS = _env_float("SEMANTIC_TIMEOUT_SECONDS", 45.0)


@dataclass
class ProviderUsage:
    """Mutable accumulator for provider activity during a single fill.

    Threaded through the pipeline so the API can report what actually happened
    on the model path — including whether it silently degraded to deterministic
    behavior — instead of only reporting which flags the caller passed.
    """

    calls: int = 0
    retries: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fields_inferred: int = 0
    degraded_reasons: list[str] = field(default_factory=list)

    def record_call(self, *, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Record one successful provider round trip."""
        self.calls += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    def record_retry(self) -> None:
        """Record one retried attempt."""
        self.retries += 1

    def record_failure(self, reason: str) -> None:
        """Record a terminal provider failure and why the path degraded."""
        self.failures += 1
        self.note_degraded(reason)

    def note_degraded(self, reason: str) -> None:
        """Record that the model path did not fully apply, without duplicates."""
        if reason not in self.degraded_reasons:
            self.degraded_reasons.append(reason)

    @property
    def total_tokens(self) -> int:
        """Total tokens billed across every provider call in this fill."""
        return self.prompt_tokens + self.completion_tokens
