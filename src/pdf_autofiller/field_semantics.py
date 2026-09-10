"""
Provider-backed semantic inference for form fields.

This module isolates model calls and response parsing so the rest of the
pipeline can stay deterministic when the provider is unavailable.

Privacy: prompts sent to the external provider include field metadata and
nearby page text, but never a field's current value (which may be PII). This
path is opt-in and only active when a provider API key is configured.
"""

import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from .models import EnrichedFormField, FieldSemantics, FormField

provider_sdk: Any = None

try:
    import openai as provider_sdk

    PROVIDER_SDK_AVAILABLE = True
except ImportError:
    PROVIDER_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)


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
    """

    def __init__(self, api_key: str | None = None):
        """
        Initialize client, falling back to stub if unavailable.

        Checks for an API key in the environment when one is not provided directly.
        Silently fails to stub mode if initialization fails.
        """
        self.api_key = api_key or os.getenv("MODEL_PROVIDER_API_KEY")
        self._client = None

        if PROVIDER_SDK_AVAILABLE and self.api_key:
            try:
                self._client = provider_sdk.OpenAI(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Failed to initialize provider client: %s", exc)
                self._client = None

    def is_available(self) -> bool:
        """Check if a working semantic client is available."""
        return self._client is not None

    def infer_semantics(self, field: FormField, context_text: str | None = None) -> FieldSemantics:
        """
        Infer semantics for a form field using the provider client.

        Args:
            field: Form field to analyze
            context_text: Optional surrounding text for context

        Returns:
            FieldSemantics with inferred meaning, data type, and confidence

        Raises:
            RuntimeError: If the semantic client is not available or inference fails
            ValueError: If the response cannot be parsed
        """
        batch = self.infer_semantics_batch(
            [field], page_context={field.page_number: context_text} if context_text else None
        )
        if field.name not in batch:
            raise RuntimeError(f"Semantic inference returned no result for field={field.name}")
        return batch[field.name]

    def infer_semantics_batch(
        self,
        fields: list[FormField],
        *,
        page_context: dict[int, str] | None = None,
    ) -> dict[str, FieldSemantics]:
        """
        Infer semantics for many fields in a single provider call.

        Returns a mapping of field name → semantics for fields present in the
        response. Missing entries are omitted (callers fall back deterministically).
        """
        if not fields:
            return {}
        if not self.is_available():
            raise RuntimeError(
                "Semantic client not available. Set MODEL_PROVIDER_API_KEY environment variable "
                "or install openai package."
            )
        assert self._client is not None

        prompt = self._build_batch_prompt(fields, page_context=page_context)
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a document analysis assistant. Analyze PDF form fields "
                            "and infer their semantic meaning. Return ONLY valid JSON matching "
                            "the required schema."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"Semantic inference failed: {exc}") from exc

        if not isinstance(content, str):
            raise RuntimeError("Semantic response did not include text content")
        return self._parse_batch_response(content, expected_names={f.name for f in fields})

    def create_json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ) -> str:
        """
        Execute a chat completion and return response content.

        Raises:
            RuntimeError: If the client is unavailable or the call fails
        """
        if not self.is_available():
            raise RuntimeError("Semantic client unavailable")
        assert self._client is not None

        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if not isinstance(content, str):
                raise RuntimeError("Semantic response did not include text content")
            return content
        except Exception as exc:
            raise RuntimeError(f"Semantic completion failed: {exc}") from exc

    def _build_prompt(self, field: FormField, context_text: str | None = None) -> str:
        """
        Construct the prompt sent to the semantic provider.

        Includes field metadata and optional surrounding text for context.
        The prompt explicitly requests JSON output matching our schema.
        """
        return self._build_batch_prompt(
            [field],
            page_context={field.page_number: context_text} if context_text else None,
        )

    def _build_batch_prompt(
        self,
        fields: list[FormField],
        *,
        page_context: dict[int, str] | None = None,
    ) -> str:
        """Build a single prompt covering all fields (one provider round-trip)."""
        field_payload = []
        for field in fields:
            entry: dict[str, object] = {
                "name": field.name,
                "type": field.field_type,
                "required": field.required,
                "has_value": bool(field.value),
                "page": field.page_number,
            }
            if page_context and field.page_number in page_context:
                context = page_context[field.page_number] or ""
                entry["surrounding_context"] = context[:500]
            field_payload.append(entry)

        return "\n".join(
            [
                "Analyze these PDF form fields and infer each semantic meaning.",
                "",
                "Fields:",
                json.dumps(field_payload, indent=2),
                "",
                'Return a JSON object with a top-level "fields" object mapping each',
                "field name to:",
                "- semantic_meaning: snake_case identifier (e.g. 'first_name')",
                "- expected_data_type: one of 'string', 'date', 'number', 'boolean'",
                "- confidence_score: float between 0.0 and 1.0",
                "",
                "Example response:",
                json.dumps(
                    {
                        "fields": {
                            "txtFirstName": {
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

    def _parse_response(self, content: str) -> FieldSemantics:
        """
        Parse a provider response and validate against schema.

        Handles single-field objects and batch ``{\"fields\": {...}}`` envelopes.
        Raises ValueError if parsing or validation fails.
        """
        try:
            data = json.loads(strip_json_code_fence(content))
            if isinstance(data, dict) and "fields" in data and isinstance(data["fields"], dict):
                # Batch envelope with a single field — take the first entry.
                if not data["fields"]:
                    raise ValueError("Semantic response fields object is empty")
                first = next(iter(data["fields"].values()))
                return FieldSemantics(**first)
            return FieldSemantics(**data)

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in semantic response: {e}") from e
        except ValidationError as e:
            raise ValueError(f"Semantic response does not match schema: {e}") from e

    def _parse_batch_response(
        self,
        content: str,
        *,
        expected_names: set[str],
    ) -> dict[str, FieldSemantics]:
        """Parse a batch response into per-field semantics."""
        try:
            data = json.loads(strip_json_code_fence(content))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in semantic response: {e}") from e

        raw_fields: dict[str, Any]
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            raw_fields = data["fields"]
        elif isinstance(data, dict) and expected_names and set(data.keys()) <= expected_names:
            raw_fields = data
        else:
            raise ValueError("Semantic batch response missing a 'fields' object")

        parsed: dict[str, FieldSemantics] = {}
        for name, payload in raw_fields.items():
            if name not in expected_names or not isinstance(payload, dict):
                continue
            try:
                parsed[name] = FieldSemantics(**payload)
            except ValidationError as e:
                logger.warning("Skipping invalid semantics for field=%s: %s", name, e)
        return parsed


def infer_field_semantics(
    field: FormField, context_text: str | None = None, api_key: str | None = None
) -> EnrichedFormField:
    """
    Infer semantic meaning for a PDF form field using the provider client.

    Takes a raw form field (e.g., "txtFirstName") and determines what it
    actually represents (e.g., "first_name"). Also infers expected data
    type and provides a confidence score.

    Args:
        field: Form field extracted from PDF
        context_text: Optional surrounding text for additional context
        api_key: Provider API key (defaults to MODEL_PROVIDER_API_KEY env var)

    Returns:
        EnrichedFormField with original field plus inferred semantics

    Raises:
        RuntimeError: If the semantic client is unavailable or the API call fails
        ValueError: If the response is invalid or doesn't match schema
    """
    client = SemanticClient(api_key=api_key)
    semantics = client.infer_semantics(field, context_text)

    return EnrichedFormField(field=field, semantics=semantics)
