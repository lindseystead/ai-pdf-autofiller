"""
Shared Pydantic models for the PDF autofill pipeline.

These models define contracts between extraction, semantics, mapping, and write steps.
"""

from typing import Literal

from pydantic import BaseModel, Field


class FormField(BaseModel):
    """Represents a fillable form field in a PDF."""

    name: str = Field(description="Field name/identifier")
    field_type: Literal["text", "button", "choice", "signature", "unknown"] = Field(
        description="Type of form field"
    )
    value: str | None = Field(default=None, description="Current field value if present")
    required: bool = Field(default=False, description="Whether field is required")
    page_number: int = Field(description="Page number where field appears (1-indexed)")


class TextRegion(BaseModel):
    """Represents a block of text extracted from one PDF page."""

    text: str = Field(description="Extracted text content")
    page_number: int = Field(description="Page number where text appears (1-indexed)")


class DocumentMetadata(BaseModel):
    """Metadata about the PDF document."""

    num_pages: int = Field(description="Total number of pages")
    title: str | None = Field(default=None, description="Document title")
    author: str | None = Field(default=None, description="Document author")
    subject: str | None = Field(default=None, description="Document subject")
    creator: str | None = Field(default=None, description="Application that created the PDF")
    producer: str | None = Field(default=None, description="Application that produced the PDF")


class FieldSemantics(BaseModel):
    """Inferred semantics for a form field."""

    semantic_meaning: str = Field(
        description=(
            "Human-meaningful semantic identifier in snake_case "
            "(e.g., 'first_name', 'date_of_birth')"
        )
    )
    expected_data_type: Literal["string", "date", "number", "boolean"] = Field(
        description="Expected data type for this field"
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for the inference (0.0 to 1.0)",
    )


class EnrichedFormField(BaseModel):
    """Form field with inferred semantics."""

    field: FormField = Field(description="Original form field metadata")
    semantics: FieldSemantics = Field(description="Inferred field semantics")


class DocumentStructure(BaseModel):
    """Structured representation of a PDF document."""

    metadata: DocumentMetadata = Field(description="Document metadata")
    form_fields: list[FormField] = Field(
        default_factory=list, description="Fillable form fields"
    )
    text_regions: list[TextRegion] = Field(
        default_factory=list, description="Extracted text regions"
    )


class FieldMappingDecision(BaseModel):
    """Decision made when mapping user data to a form field."""

    field_name: str = Field(description="PDF form field name")
    semantic_meaning: str = Field(description="Semantic meaning of the field")
    selected_value: str | None = Field(
        default=None, description="Value selected from user data"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the mapping decision")
    confidence_source: Literal["deterministic", "model"] = Field(
        default="deterministic",
        description=(
            "Where the confidence came from. 'deterministic' values are assigned by "
            "matching rules; 'model' values are self-reported by a language model and "
            "are capped below the review threshold because they are not calibrated."
        ),
    )
    reason: str = Field(description="Explanation of how the mapping was determined")
    requires_review: bool = Field(
        default=False, description="Whether this mapping requires human review"
    )


class MappingResult(BaseModel):
    """Result of mapping user data to PDF form fields."""

    decisions: list[FieldMappingDecision] = Field(
        default_factory=list, description="Mapping decisions for each field"
    )
    missing_required: list[str] = Field(
        default_factory=list,
        description="Required fields that could not be mapped",
    )
    unmapped_user_keys: list[str] = Field(
        default_factory=list,
        description="User data keys that were not mapped to any field",
    )


class FillReport(BaseModel):
    """Outcome of writing mapping decisions into a PDF.

    Surfaces which fields were written and which were intentionally skipped, so
    callers can detect non-required fields that were dropped (for example because
    they were flagged ``requires_review``) instead of silently losing them.

    ``written_fields`` is verified against the output document, not assumed from
    the write attempt: anything the PDF library declined to persist appears in
    ``failed_fields`` instead.
    """

    written_fields: list[str] = Field(
        default_factory=list,
        description="Field names confirmed present in the output PDF",
    )
    failed_fields: list[str] = Field(
        default_factory=list,
        description="Field names that were written but could not be verified in the output",
    )
    skipped_review_fields: list[str] = Field(
        default_factory=list,
        description="Field names skipped because the mapping was flagged for review",
    )
    skipped_empty_fields: list[str] = Field(
        default_factory=list,
        description="Field names skipped because the mapped value was empty",
    )


class PipelineTelemetry(BaseModel):
    """What actually happened on the optional model path during one fill.

    Recorded so a run that silently degraded to deterministic behavior — because
    no API key was configured, or the provider failed — is visible to operators
    instead of being indistinguishable from a run where inference succeeded.
    """

    semantic_inference_requested: bool = Field(
        default=False, description="Whether the caller asked for semantic inference"
    )
    semantic_inference_applied: bool = Field(
        default=False, description="Whether any field received model-derived semantics"
    )
    fallback_mapping_requested: bool = Field(
        default=False, description="Whether the caller allowed provider-backed fallback mapping"
    )
    fallback_mapping_applied: bool = Field(
        default=False, description="Whether any field was mapped by the provider fallback"
    )
    fields_inferred: int = Field(
        default=0, description="Number of fields that received model-derived semantics"
    )
    provider_calls: int = Field(default=0, description="Successful provider round trips")
    provider_retries: int = Field(default=0, description="Retried provider attempts")
    provider_failures: int = Field(default=0, description="Terminal provider failures")
    prompt_tokens: int = Field(default=0, description="Prompt tokens billed")
    completion_tokens: int = Field(default=0, description="Completion tokens billed")
    degraded_reasons: list[str] = Field(
        default_factory=list,
        description="Why a requested model feature did not fully apply",
    )

    @property
    def degraded(self) -> bool:
        """True when a requested model feature did not fully apply."""
        return bool(self.degraded_reasons)

    @property
    def total_tokens(self) -> int:
        """Total tokens billed across every provider call in this fill."""
        return self.prompt_tokens + self.completion_tokens


class PipelineResult(BaseModel):
    """Everything a caller needs after one end-to-end fill."""

    fill_report: FillReport = Field(description="Outcome of writing the output PDF")
    mapping_result: MappingResult = Field(description="How user data was matched to fields")
    fields_total: int = Field(description="Number of form fields discovered in the document")
    telemetry: PipelineTelemetry = Field(
        default_factory=lambda: PipelineTelemetry(),
        description="Model-path activity for this fill",
    )
