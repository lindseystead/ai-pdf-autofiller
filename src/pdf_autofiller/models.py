"""
Shared Pydantic models for the PDF autofill pipeline.

These models define contracts between extraction, semantics, mapping, and write steps.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class FormField(BaseModel):
    """Represents a fillable form field in a PDF."""
    
    name: str = Field(description="Field name/identifier")
    field_type: Literal["text", "button", "choice", "signature", "unknown"] = Field(
        description="Type of form field"
    )
    value: Optional[str] = Field(default=None, description="Current field value if present")
    required: bool = Field(default=False, description="Whether field is required")
    page_number: int = Field(description="Page number where field appears (1-indexed)")


class TextRegion(BaseModel):
    """Represents a text region extracted from a PDF."""
    
    text: str = Field(description="Extracted text content")
    page_number: int = Field(description="Page number where text appears (1-indexed)")
    x: Optional[float] = Field(default=None, description="X coordinate of text region")
    y: Optional[float] = Field(default=None, description="Y coordinate of text region")


class DocumentMetadata(BaseModel):
    """Metadata about the PDF document."""
    
    num_pages: int = Field(description="Total number of pages")
    title: Optional[str] = Field(default=None, description="Document title")
    author: Optional[str] = Field(default=None, description="Document author")
    subject: Optional[str] = Field(default=None, description="Document subject")
    creator: Optional[str] = Field(default=None, description="Application that created the PDF")
    producer: Optional[str] = Field(default=None, description="Application that produced the PDF")


class FieldSemantics(BaseModel):
    """Inferred semantics for a form field."""
    
    semantic_meaning: str = Field(
        description="Human-meaningful semantic identifier in snake_case (e.g., 'first_name', 'date_of_birth')"
    )
    expected_data_type: Literal["string", "date", "number", "boolean"] = Field(
        description="Expected data type for this field"
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for the inference (0.0 to 1.0)"
    )


class EnrichedFormField(BaseModel):
    """Form field with inferred semantics."""
    
    field: FormField = Field(description="Original form field metadata")
    semantics: FieldSemantics = Field(description="Inferred field semantics")


class DocumentStructure(BaseModel):
    """Structured representation of a PDF document."""
    
    metadata: DocumentMetadata = Field(description="Document metadata")
    form_fields: list[FormField] = Field(default_factory=list, description="Fillable form fields")
    text_regions: list[TextRegion] = Field(default_factory=list, description="Extracted text regions")


class FieldMappingDecision(BaseModel):
    """Decision made when mapping user data to a form field."""
    
    field_name: str = Field(description="PDF form field name")
    semantic_meaning: str = Field(description="Semantic meaning of the field")
    selected_value: Optional[str] = Field(default=None, description="Value selected from user data")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the mapping decision")
    reason: str = Field(description="Explanation of how the mapping was determined")
    requires_review: bool = Field(default=False, description="Whether this mapping requires human review")


class MappingResult(BaseModel):
    """Result of mapping user data to PDF form fields."""

    decisions: list[FieldMappingDecision] = Field(
        default_factory=list,
        description="Mapping decisions for each field"
    )
    missing_required: list[str] = Field(
        default_factory=list,
        description="Required fields that could not be mapped"
    )
    unmapped_user_keys: list[str] = Field(
        default_factory=list,
        description="User data keys that were not mapped to any field"
    )


class FillReport(BaseModel):
    """Outcome of writing mapping decisions into a PDF.

    Surfaces which fields were written and which were intentionally skipped, so
    callers can detect non-required fields that were dropped (for example because
    they were flagged ``requires_review``) instead of silently losing them.
    """

    written_fields: list[str] = Field(
        default_factory=list,
        description="Field names that received a value in the output PDF"
    )
    skipped_review_fields: list[str] = Field(
        default_factory=list,
        description="Field names skipped because the mapping was flagged for review"
    )
    skipped_empty_fields: list[str] = Field(
        default_factory=list,
        description="Field names skipped because the mapped value was empty"
    )
