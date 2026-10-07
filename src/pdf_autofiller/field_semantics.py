"""
AI field inference: the only module that calls the AI provider (OpenAI).

Used by AI field inference (`use_semantic_inference`) and, through
create_json_completion, by the AI key fallback in mapping.py. Both are opt-in
and need MODEL_PROVIDER_API_KEY.

Privacy: prompts include field metadata and the start of each page's text, but
never a field's current value (which may be PII).
"""

import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from .models import FieldSemantics, FormField

provider_sdk: Any = None

try:
    import openai as provider_sdk

    PROVIDER_SDK_AVAILABLE = True
except ImportError:
    PROVIDER_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
# A run makes at most two provider calls (inference + fallback), and both must
# finish inside the API job timeout (PDF_READ_TIMEOUT_SECONDS, 20 s by default).
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 0


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
    """Thin wrapper over the OpenAI client; ``is_available()`` is False when no client could be built."""

    def __init__(self, api_key: str | None = None):
        """Build the provider client from ``api_key`` or MODEL_PROVIDER_API_KEY.

        If the SDK or key is missing, or setup fails (logged as a warning),
        ``is_available()`` returns False.
        """
        self.api_key = api_key or os.getenv("MODEL_PROVIDER_API_KEY")
        self._client = None

        if PROVIDER_SDK_AVAILABLE and self.api_key:
            try:
                self._client = provider_sdk.OpenAI(
                    api_key=self.api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES
                )
            except Exception as exc:
                logger.warning("Failed to initialize provider client: %s", exc)
                self._client = None

    def _require_client(self) -> Any:
        """Return the provider client, or raise RuntimeError when none could be built."""
        if self._client is None:
            raise RuntimeError(
                "Semantic client not available. Set MODEL_PROVIDER_API_KEY and install the openai package."
            )
        return self._client

    def is_available(self) -> bool:
        """Check if a working semantic client is available."""
        return self._client is not None

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
        client = self._require_client()
        prompt = self._build_batch_prompt(fields, page_context=page_context)
        try:
            response = client.chat.completions.create(
                model=MODEL,
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
        except Exception as exc:  # SDK and network errors vary by version; callers handle RuntimeError
            raise RuntimeError(f"Semantic inference failed: {exc}") from exc

        if not isinstance(content, str):
            raise RuntimeError("Semantic response did not include text content")
        return self._parse_batch_response(content, expected_names={f.name for f in fields})

    def create_json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        """
        Execute a chat completion and return response content.

        Raises:
            RuntimeError: If the client is unavailable or the call fails
        """
        client = self._require_client()
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            content = response.choices[0].message.content
        except Exception as exc:  # SDK and network errors vary by version; callers handle RuntimeError
            raise RuntimeError(f"Semantic completion failed: {exc}") from exc
        if not isinstance(content, str):
            raise RuntimeError("Semantic response did not include text content")
        return content

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
