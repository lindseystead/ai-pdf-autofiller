"""
Provider-backed semantic inference for form fields.

This module isolates model calls and response parsing so the rest of the
pipeline can stay deterministic when the provider is unavailable.

Operational posture:
- Inference is **batched**: one call describes many fields, so a form costs one
  or two round trips rather than one per field.
- Every call carries an explicit timeout and bounded retries with backoff.
- Token usage, retries, and failures are recorded in a :class:`ProviderUsage`
  accumulator so a degraded run is visible instead of silent.

Privacy: prompts sent to the external provider include field metadata and
nearby page text, but never a field's current value (which may be PII). This
path is opt-in and only active when a provider API key is configured.

Security: page text and field names come from an uploaded document and are
therefore attacker-controlled. See :mod:`pdf_autofiller.untrusted_text` for how
that content is fenced and how model output is constrained.
"""

import json
import logging
import os
import time
from typing import Any

from pydantic import ValidationError

from .models import EnrichedFormField, FieldSemantics, FormField
from .provider_config import (
    MODEL_CONTEXT_CHAR_LIMIT,
    MODEL_MAX_RETRIES,
    MODEL_NAME,
    MODEL_RETRY_BACKOFF_SECONDS,
    MODEL_SEMANTIC_BATCH_SIZE,
    MODEL_TEMPERATURE,
    MODEL_TIMEOUT_SECONDS,
    ProviderUsage,
)
from .untrusted_text import (
    UNTRUSTED_CONTENT_RULES,
    fence_untrusted,
    is_safe_semantic_meaning,
    new_fence_token,
    sanitize_untrusted_text,
)

try:
    import openai

    # Held behind a module-level alias so the concrete SDK stays swappable, and
    # so this module is the single place that names the provider.
    provider_sdk: Any = openai
    PROVIDER_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via monkeypatching
    provider_sdk = None
    PROVIDER_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

_SEMANTICS_SYSTEM_PROMPT = (
    "You are a document analysis assistant. You infer what PDF form fields "
    "represent from their names and surrounding page text. Return ONLY valid "
    "JSON matching the required schema. " + UNTRUSTED_CONTENT_RULES
)

_MAPPING_SYSTEM_PROMPT = (
    "You are a data mapping assistant. You match form fields to user data keys. "
    "Return ONLY valid JSON matching the required schema. " + UNTRUSTED_CONTENT_RULES
)


def strip_json_code_fence(content: str) -> str:
    """Normalize JSON-ish model output by removing surrounding markdown fences."""
    normalized = content.strip()
    if normalized.startswith("```json"):
        normalized = normalized[7:]
    elif normalized.startswith("```"):
        normalized = normalized[3:]
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return normalized.strip()


def _coerce_semantics(payload: Any) -> FieldSemantics | None:
    """Validate one semantics object from a model response.

    Returns ``None`` when the payload is malformed or the semantic label is not
    a plain identifier, so a poisoned or garbled entry is dropped rather than
    propagated into mapping.
    """
    if not isinstance(payload, dict):
        return None
    try:
        semantics = FieldSemantics(**payload)
    except (ValidationError, TypeError):
        return None

    if not is_safe_semantic_meaning(semantics.semantic_meaning):
        logger.warning(
            "Discarding model semantic label that is not a plain identifier"
        )
        return None
    return semantics


class SemanticClient:
    """
    Wrapper around the provider client with graceful degradation.

    Handles cases where the provider SDK is not installed or credentials are not
    configured. This allows the rest of the system to work even if provider-backed
    features are unavailable.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        usage: ProviderUsage | None = None,
    ):
        """
        Initialize client, falling back to stub if unavailable.

        Checks for an API key in the environment when one is not provided directly.
        Falls back to stub mode (with a logged warning) if initialization fails.
        """
        self.api_key = api_key or os.getenv("MODEL_PROVIDER_API_KEY")
        self.usage = usage if usage is not None else ProviderUsage()
        self._client = None

        if PROVIDER_SDK_AVAILABLE and self.api_key:
            try:
                self._client = provider_sdk.OpenAI(
                    api_key=self.api_key,
                    timeout=MODEL_TIMEOUT_SECONDS,
                    max_retries=0,  # retries are handled here so they are counted
                )
            except Exception as exc:  # noqa: BLE001 - SDK init failure must degrade, not crash
                logger.warning("Failed to initialize provider client: %s", exc)
                self._client = None

    def is_available(self) -> bool:
        """Check if a working semantic client is available."""
        return self._client is not None

    def _completion_with_retry(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
    ) -> str:
        """Call the provider with bounded retries and record usage.

        Raises:
            RuntimeError: If every attempt fails, or the response has no content
        """
        assert self._client is not None
        last_error: Exception | None = None

        for attempt in range(MODEL_MAX_RETRIES + 1):
            if attempt:
                self.usage.record_retry()
                time.sleep(MODEL_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    timeout=MODEL_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - any provider error is retryable here
                last_error = exc
                logger.warning(
                    "Provider call failed (attempt %d/%d): %s",
                    attempt + 1,
                    MODEL_MAX_RETRIES + 1,
                    exc,
                )
                continue

            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            self.usage.record_call(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
            if not isinstance(content, str):
                raise RuntimeError("Semantic response did not include text content")
            return content

        raise RuntimeError(f"Semantic inference failed: {last_error}")

    def infer_semantics(
        self, field: FormField, context_text: str | None = None
    ) -> FieldSemantics:
        """
        Infer semantics for a single form field.

        Prefer :meth:`infer_semantics_batch` for whole forms; this remains for
        single-field callers and keeps the original contract.

        Raises:
            RuntimeError: If the semantic client is not available or inference fails
            ValueError: If the response cannot be parsed
        """
        results = self.infer_semantics_batch([(field, context_text)])
        semantics = results.get(field.name)
        if semantics is None:
            raise ValueError("Semantic response did not cover the requested field")
        return semantics

    def infer_semantics_batch(
        self, items: list[tuple[FormField, str | None]]
    ) -> dict[str, FieldSemantics]:
        """
        Infer semantics for many fields using as few provider calls as possible.

        Args:
            items: (field, optional surrounding page text) pairs

        Returns:
            Mapping of field name to inferred semantics. Fields the model did
            not cover, or covered with an unusable answer, are simply absent —
            callers fall back to deterministic semantics for those.

        Raises:
            RuntimeError: If the semantic client is not available or a call fails
        """
        if not self.is_available():
            raise RuntimeError(
                "Semantic client not available. Set MODEL_PROVIDER_API_KEY environment variable "
                "or install openai package."
            )
        if not items:
            return {}

        resolved: dict[str, FieldSemantics] = {}
        for start in range(0, len(items), MODEL_SEMANTIC_BATCH_SIZE):
            batch = items[start : start + MODEL_SEMANTIC_BATCH_SIZE]
            content = self._completion_with_retry(
                system_prompt=_SEMANTICS_SYSTEM_PROMPT,
                user_prompt=self._build_batch_prompt(batch),
                model=MODEL_NAME,
                temperature=MODEL_TEMPERATURE,
            )
            resolved.update(self._parse_batch_response(content, batch))

        return resolved

    def create_json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str = MODEL_NAME,
        temperature: float = MODEL_TEMPERATURE,
    ) -> str:
        """
        Execute a chat completion and return response content.

        Raises:
            RuntimeError: If the client is unavailable or every attempt fails
        """
        if not self.is_available():
            raise RuntimeError("Semantic client unavailable")

        return self._completion_with_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
        )

    def _build_prompt(self, field: FormField, context_text: str | None = None) -> str:
        """Construct the prompt for a single field (see :meth:`_build_batch_prompt`)."""
        return self._build_batch_prompt([(field, context_text)])

    def _build_batch_prompt(self, batch: list[tuple[FormField, str | None]]) -> str:
        """
        Construct the batched prompt sent to the semantic provider.

        Field metadata and page text originate in the uploaded document, so both
        are sanitized and fenced as untrusted data. A field's current value is
        never included — only whether one is present, which is all that helps
        infer meaning.
        """
        fence = new_fence_token()
        described: list[dict[str, Any]] = []
        context_blocks: list[str] = []

        for index, (field, context_text) in enumerate(batch):
            described.append(
                {
                    "id": index,
                    "field_name": sanitize_untrusted_text(field.name, limit=200, fence=fence),
                    "field_type": field.field_type,
                    "required": field.required,
                    # Privacy: never send the field's current value (it may be PII).
                    "has_value": bool(field.value),
                    "page": field.page_number,
                }
            )
            cleaned = sanitize_untrusted_text(
                context_text, limit=MODEL_CONTEXT_CHAR_LIMIT, fence=fence
            )
            if cleaned:
                context_blocks.append(
                    fence_untrusted(f"page_{field.page_number}_context", cleaned, fence)
                )

        prompt_parts = [
            "Infer the semantic meaning of each PDF form field listed below.",
            "",
            "Fields (JSON):",
            json.dumps(described, indent=2),
        ]

        if context_blocks:
            prompt_parts.extend(
                [
                    "",
                    "Surrounding page text, for disambiguation only:",
                    *dict.fromkeys(context_blocks),
                ]
            )

        prompt_parts.extend(
            [
                "",
                UNTRUSTED_CONTENT_RULES,
                "",
                'Return a JSON object of the form {"fields": {...}} where each key is a',
                "field id from the list above (as a string) and each value has:",
                "- semantic_meaning: snake_case identifier, letters/digits/underscores only",
                "  (e.g., 'first_name', 'date_of_birth', 'email_address', 'phone_number')",
                "- expected_data_type: one of 'string', 'date', 'number', 'boolean'",
                "- confidence_score: float between 0.0 and 1.0",
                "",
                "Example response:",
                json.dumps(
                    {
                        "fields": {
                            "0": {
                                "semantic_meaning": "first_name",
                                "expected_data_type": "string",
                                "confidence_score": 0.95,
                            }
                        }
                    },
                    indent=2,
                ),
            ]
        )

        return "\n".join(prompt_parts)

    def _parse_batch_response(
        self, content: str, batch: list[tuple[FormField, str | None]]
    ) -> dict[str, FieldSemantics]:
        """
        Parse a batched provider response into validated semantics.

        Entries are keyed back to the batch by index, so a response cannot
        introduce field names that were not asked about. Unusable entries are
        dropped individually rather than failing the whole batch.

        Raises:
            ValueError: If the response is not JSON or has no ``fields`` object
        """
        try:
            payload = json.loads(strip_json_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in semantic response: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Semantic response was not a JSON object")

        entries = payload.get("fields")
        if not isinstance(entries, dict):
            raise ValueError("Semantic response did not include a 'fields' object")

        resolved: dict[str, FieldSemantics] = {}
        for index, (field, _context) in enumerate(batch):
            entry = entries.get(str(index), entries.get(index))
            semantics = _coerce_semantics(entry)
            if semantics is not None:
                resolved[field.name] = semantics
        return resolved

    def _parse_response(self, content: str) -> FieldSemantics:
        """
        Parse a single-field provider response and validate against schema.

        Accepts both the batched ``{"fields": {...}}`` shape and a bare
        semantics object, so older single-field responses still parse.

        Raises:
            ValueError: If parsing or validation fails
        """
        try:
            data = json.loads(strip_json_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in semantic response: {exc}") from exc

        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            entries = data["fields"]
            data = next(iter(entries.values()), None)

        semantics = _coerce_semantics(data)
        if semantics is None:
            raise ValueError("Semantic response does not match schema")
        return semantics


def infer_field_semantics(
    field: FormField,
    context_text: str | None = None,
    api_key: str | None = None,
    *,
    usage: ProviderUsage | None = None,
) -> EnrichedFormField:
    """
    Infer semantic meaning for a single PDF form field.

    Takes a raw form field (e.g., "txtFirstName") and determines what it
    actually represents (e.g., "first_name"). Also infers expected data
    type and provides a confidence score.

    For whole forms prefer :func:`infer_fields_semantics`, which batches.

    Raises:
        RuntimeError: If the semantic client is unavailable or the API call fails
        ValueError: If the response is invalid or doesn't match schema
    """
    client = SemanticClient(api_key=api_key, usage=usage)
    semantics = client.infer_semantics(field, context_text)
    return EnrichedFormField(field=field, semantics=semantics)


def infer_fields_semantics(
    items: list[tuple[FormField, str | None]],
    api_key: str | None = None,
    *,
    usage: ProviderUsage | None = None,
) -> dict[str, FieldSemantics]:
    """
    Infer semantics for many fields in as few provider calls as possible.

    Args:
        items: (field, optional page context) pairs
        api_key: Provider API key (defaults to MODEL_PROVIDER_API_KEY env var)
        usage: Optional accumulator recording calls, tokens, and failures

    Returns:
        Mapping of field name to semantics for every field the model resolved

    Raises:
        RuntimeError: If the semantic client is unavailable or a call fails
        ValueError: If a response cannot be parsed
    """
    client = SemanticClient(api_key=api_key, usage=usage)
    return client.infer_semantics_batch(items)
