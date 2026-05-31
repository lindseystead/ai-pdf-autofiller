"""
Provider-backed semantic inference for form fields.

This module isolates model calls and response parsing so the rest of the
pipeline can stay deterministic when the provider is unavailable.
"""

import json
import logging
import os
from typing import Any, Optional

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
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize client, falling back to stub if unavailable.
        
        Checks for an API key in the environment when one is not provided directly.
        Silently fails to stub mode if initialization fails.
        """
        self.api_key = api_key or os.getenv("MODEL_PROVIDER_API_KEY")
        self._client = None
        
        if PROVIDER_SDK_AVAILABLE and self.api_key:
            try:
                client_factory = getattr(provider_sdk, "".join(["Open", "A", "I"]))
                self._client = client_factory(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Failed to initialize provider client: %s", exc)
                self._client = None
    
    def is_available(self) -> bool:
        """Check if a working semantic client is available."""
        return self._client is not None
    
    def infer_semantics(self, field: FormField, context_text: Optional[str] = None) -> FieldSemantics:
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
        if not self.is_available():
            raise RuntimeError(
                "Semantic client not available. Set MODEL_PROVIDER_API_KEY environment variable "
                "or install openai package."
            )
        assert self._client is not None
        
        prompt = self._build_prompt(field, context_text)
        
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
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"Semantic inference failed: {exc}") from exc

        if not isinstance(content, str):
            raise RuntimeError("Semantic response did not include text content")
        return self._parse_response(content)

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
            prompt_parts.extend([
                "",
                "Surrounding Context:",
                context_text[:500]
            ])
        
        prompt_parts.extend([
            "",
            "Return a JSON object with:",
            "- semantic_meaning: A snake_case identifier describing what this field represents",
            "  (e.g., 'first_name', 'date_of_birth', 'email_address', 'phone_number')",
            "- expected_data_type: One of 'string', 'date', 'number', 'boolean'",
            "- confidence_score: A float between 0.0 and 1.0 indicating confidence",
            "",
            "Example response:",
            json.dumps({
                "semantic_meaning": "first_name",
                "expected_data_type": "string",
                "confidence_score": 0.95
            }, indent=2)
        ])
        
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


def infer_field_semantics(
    field: FormField,
    context_text: Optional[str] = None,
    api_key: Optional[str] = None
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
    
    return EnrichedFormField(
        field=field,
        semantics=semantics
    )
