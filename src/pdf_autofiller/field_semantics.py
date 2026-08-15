"""
Provider-backed semantic inference for form fields.

This module isolates model calls and response parsing so the rest of the
pipeline can stay deterministic when the provider is unavailable.

Inference is *batched*: one request describes the whole form and returns
semantics for every field. Asking per field made N serial round trips inside a
single request budget, which timed out on any real form and cost N times what
one call costs. Generating the whole object at once is also more self-consistent
— the model can see that a form has both a birth date and a signature date, and
tell them apart.

The response is constrained by a JSON schema where the provider supports it,
with local pydantic validation as the backstop, because schema-shaped output is
still not schema-*guaranteed* output on every provider and model.

Privacy: prompts include field metadata and nearby page text, but never a
field's current value (which may be PII). This path is opt-in and only active
when a provider API key is configured.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from pydantic import ValidationError

from .models import EnrichedFormField, FieldSemantics, FormField
from .settings import get_settings

provider_sdk: Any = None

try:
    import openai as provider_sdk

    PROVIDER_SDK_AVAILABLE = True
except ImportError:
    PROVIDER_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

# Context is truncated per field so one verbose page cannot dominate the prompt
# (or the bill) for a form with many fields.
_CONTEXT_CHARS_PER_FIELD = 400

_SEMANTICS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "field_name": {"type": "string"},
        "semantic_meaning": {"type": "string"},
        "expected_data_type": {
            "type": "string",
            "enum": ["string", "date", "number", "boolean"],
        },
        "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "field_name",
        "semantic_meaning",
        "expected_data_type",
        "confidence_score",
    ],
    "additionalProperties": False,
}

BATCH_SEMANTICS_SCHEMA = {
    "type": "object",
    "properties": {"fields": {"type": "array", "items": _SEMANTICS_ITEM_SCHEMA}},
    "required": ["fields"],
    "additionalProperties": False,
}


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


class SemanticClient:
    """
    Wrapper around the provider client with graceful degradation.

    Handles cases where the provider SDK is not installed or credentials are not
    configured. This allows the rest of the system to work even if provider-backed
    features are unavailable.

    Model, timeout, and retry count come from settings rather than being hardcoded
    at the call sites, so an operator can change the model without a code change
    and a slow provider cannot consume the whole request budget.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        """
        Initialize client, falling back to stub if unavailable.

        Checks settings for an API key when one is not provided directly.
        Silently falls back to stub mode if initialization fails.
        """
        settings = get_settings()
        self.api_key = api_key or settings.provider_api_key
        self.model = model or settings.provider_model
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.provider_timeout_seconds
        )
        self.max_retries = (
            max_retries if max_retries is not None else settings.provider_max_retries
        )
        self._client = None

        if PROVIDER_SDK_AVAILABLE and self.api_key:
            try:
                client_factory = getattr(provider_sdk, "OpenAI")
                self._client = client_factory(
                    api_key=self.api_key, timeout=self.timeout_seconds
                )
            except Exception as exc:
                logger.warning("Failed to initialize provider client: %s", exc)
                self._client = None

    def is_available(self) -> bool:
        """Check if a working semantic client is available."""
        return self._client is not None

    def infer_semantics(
        self, field: FormField, context_text: Optional[str] = None
    ) -> FieldSemantics:
        """
        Infer semantics for a single form field.

        Prefer :func:`infer_fields_semantics` for whole forms; this remains for
        one-off use and for callers holding a single field.

        Raises:
            RuntimeError: If the semantic client is not available or inference fails
            ValueError: If the response cannot be parsed
        """
        if not self.is_available():
            raise RuntimeError(
                "Semantic client not available. Set MODEL_PROVIDER_API_KEY environment variable "
                "or install openai package."
            )

        prompt = self._build_prompt(field, context_text)
        content = self.create_json_completion(
            system_prompt=(
                "You are a document analysis assistant. Analyze PDF form fields "
                "and infer their semantic meaning. Return ONLY valid JSON matching "
                "the required schema."
            ),
            user_prompt=prompt,
            temperature=0.3,
        )
        return self._parse_response(content)

    def infer_batch(
        self, fields: list[FormField], page_context: dict[int, str]
    ) -> dict[str, FieldSemantics]:
        """
        Infer semantics for many fields in one request.

        Returns a mapping of field name to semantics. Fields the provider omits
        or returns unusable output for are simply absent; the caller applies its
        deterministic fallback for those rather than failing the whole form.
        """
        if not fields:
            return {}
        if not self.is_available():
            raise RuntimeError("Semantic client unavailable")

        payload = []
        for field in fields:
            entry: dict[str, Any] = {
                "field_name": field.name,
                "field_type": field.field_type,
                "required": field.required,
                "page": field.page_number,
                # Privacy: never send the field's current value (it may be PII);
                # only whether one is present is relevant to inferring meaning.
                "has_value": bool(field.value),
            }
            if field.options:
                entry["options"] = field.options[:20]
            context = page_context.get(field.page_number)
            if context:
                entry["page_context"] = context[:_CONTEXT_CHARS_PER_FIELD]
            payload.append(entry)

        prompt = (
            "Infer the semantic meaning of each field in this PDF form.\n\n"
            "Fields:\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Return a JSON object with a 'fields' array. Each entry must contain:\n"
            "- field_name: echo the field_name exactly as given\n"
            "- semantic_meaning: snake_case identifier (e.g. 'first_name', "
            "'date_of_birth', 'email_address')\n"
            "- expected_data_type: one of 'string', 'date', 'number', 'boolean'\n"
            "- confidence_score: float between 0.0 and 1.0\n\n"
            "Return one entry per field, in the same order. Distinguish fields that "
            "look similar but differ in purpose (for example a date of birth versus "
            "a signature date) using the surrounding page context."
        )

        content = self.create_json_completion(
            system_prompt=(
                "You are a document analysis assistant. Analyze PDF form fields and "
                "infer their semantic meanings. Return ONLY valid JSON matching the schema."
            ),
            user_prompt=prompt,
            temperature=0.1,
            json_schema=BATCH_SEMANTICS_SCHEMA,
            schema_name="form_field_semantics",
        )
        return self._parse_batch_response(content, {f.name for f in fields})

    def create_json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        json_schema: Optional[dict[str, Any]] = None,
        schema_name: str = "response",
    ) -> str:
        """
        Execute a chat completion and return response content.

        Retries transient provider failures with exponential backoff. A schema is
        used when supplied and the provider accepts it; providers that reject
        strict schemas fall back to plain JSON mode, which local validation then
        has to catch.

        Raises:
            RuntimeError: If the client is unavailable or every attempt failed
        """
        if not self.is_available():
            raise RuntimeError("Semantic client unavailable")
        assert self._client is not None

        response_format: dict[str, Any] = {"type": "json_object"}
        if json_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                },
            }

        last_error: Optional[Exception] = None
        schema_rejected = False

        for attempt in range(self.max_retries + 1):
            try:
                effective_format = (
                    {"type": "json_object"} if schema_rejected else response_format
                )
                response = self._client.chat.completions.create(
                    model=model or self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=effective_format,
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                if not isinstance(content, str):
                    raise RuntimeError("Semantic response did not include text content")
                return content
            except Exception as exc:
                last_error = exc
                if json_schema is not None and not schema_rejected and _looks_like_schema_error(exc):
                    logger.info(
                        "Provider rejected strict schema; retrying with JSON mode: %s", exc
                    )
                    schema_rejected = True
                    continue
                if attempt < self.max_retries:
                    backoff = 0.5 * (2**attempt)
                    logger.info(
                        "Provider call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        self.max_retries + 1,
                        backoff,
                        exc,
                    )
                    time.sleep(backoff)
                    continue

        raise RuntimeError(f"Semantic completion failed: {last_error}") from last_error

    def _build_prompt(self, field: FormField, context_text: Optional[str] = None) -> str:
        """
        Construct the prompt sent to the semantic provider.

        Includes field metadata and optional surrounding text for context.
        The prompt explicitly requests JSON output matching our schema.
        """
        prompt_parts = [
            "Analyze this PDF form field and infer its semantic meaning.",
            "",
            "Field Information:",
            f"- Name: {field.name}",
            f"- Type: {field.field_type}",
            f"- Required: {field.required}",
            # Privacy: never send the field's current value (it may be PII);
            # only whether one is present is relevant to inferring meaning.
            f"- Has Value: {'yes' if field.value else 'no'}",
            f"- Page: {field.page_number}",
        ]

        if context_text:
            prompt_parts.extend(["", "Surrounding Context:", context_text[:500]])

        prompt_parts.extend(
            [
                "",
                "Return a JSON object with:",
                "- semantic_meaning: A snake_case identifier describing what this field represents",
                "  (e.g., 'first_name', 'date_of_birth', 'email_address', 'phone_number')",
                "- expected_data_type: One of 'string', 'date', 'number', 'boolean'",
                "- confidence_score: A float between 0.0 and 1.0 indicating confidence",
                "",
                "Example response:",
                json.dumps(
                    {
                        "semantic_meaning": "first_name",
                        "expected_data_type": "string",
                        "confidence_score": 0.95,
                    },
                    indent=2,
                ),
            ]
        )

        return "\n".join(prompt_parts)

    def _parse_response(self, content: str) -> FieldSemantics:
        """
        Parse a provider response and validate against schema.

        Handles cases where the response wraps JSON in markdown code blocks.
        Raises ValueError if parsing or validation fails.
        """
        try:
            data = json.loads(strip_json_code_fence(content))
            return FieldSemantics(**data)

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in semantic response: {e}") from e
        except ValidationError as e:
            raise ValueError(f"Semantic response does not match schema: {e}") from e

    def _parse_batch_response(
        self, content: str, expected_names: set[str]
    ) -> dict[str, FieldSemantics]:
        """Parse a batched response, keeping only well-formed known fields."""
        try:
            data = json.loads(strip_json_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in semantic response: {exc}") from exc

        entries = data.get("fields") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Semantic response missing 'fields' array")

        results: dict[str, FieldSemantics] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("field_name")
            if name not in expected_names:
                # A hallucinated field name must not become a mapping decision.
                continue
            try:
                results[name] = FieldSemantics(
                    semantic_meaning=entry["semantic_meaning"],
                    expected_data_type=entry["expected_data_type"],
                    confidence_score=float(entry["confidence_score"]),
                )
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                logger.debug("Discarding unusable semantics for %r: %s", name, exc)
                continue

        return results


def _looks_like_schema_error(exc: Exception) -> bool:
    """Heuristic: did the provider reject the strict-schema response format?"""
    text = str(exc).lower()
    return "response_format" in text or "json_schema" in text or "schema" in text


def infer_fields_semantics(
    fields: list[FormField],
    page_context: Optional[dict[int, str]] = None,
    api_key: Optional[str] = None,
) -> dict[str, FieldSemantics]:
    """
    Infer semantics for a whole form, batching provider calls.

    Very large forms are split into chunks so one request cannot exceed the
    provider's context window. Returns whatever could be inferred; the caller
    applies deterministic fallback for the rest, so a provider outage degrades
    the result instead of failing it.
    """
    if not fields:
        return {}

    settings = get_settings()
    client = SemanticClient(api_key=api_key)
    if not client.is_available():
        return {}

    batch_size = max(1, settings.provider_batch_size)
    results: dict[str, FieldSemantics] = {}
    for start in range(0, len(fields), batch_size):
        chunk = fields[start : start + batch_size]
        try:
            results.update(client.infer_batch(chunk, page_context or {}))
        except (RuntimeError, ValueError) as exc:
            logger.warning(
                "Semantic inference failed for fields %d-%d: %s",
                start,
                start + len(chunk),
                exc,
            )
            continue

    return results


def infer_field_semantics(
    field: FormField, context_text: Optional[str] = None, api_key: Optional[str] = None
) -> EnrichedFormField:
    """
    Infer semantic meaning for a single PDF form field.

    Takes a raw form field (e.g., "txtFirstName") and determines what it
    actually represents (e.g., "first_name"). Also infers expected data
    type and provides a confidence score.

    Raises:
        RuntimeError: If the semantic client is unavailable or the API call fails
        ValueError: If the response is invalid or doesn't match schema
    """
    client = SemanticClient(api_key=api_key)
    semantics = client.infer_semantics(field, context_text)

    return EnrichedFormField(field=field, semantics=semantics)
