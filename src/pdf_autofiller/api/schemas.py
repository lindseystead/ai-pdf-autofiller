"""HTTP response models for the PDF Autofiller API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    service: str
    version: str


class InspectField(BaseModel):
    name: str
    field_type: str
    required: bool
    page_number: int
    current_value: str | None = None


class InspectResponse(BaseModel):
    pages: int
    field_count: int
    fields: list[InspectField]


class PreviewDecision(BaseModel):
    field_name: str
    semantic_meaning: str
    selected_value: str | None = None
    confidence: float
    reason: str
    requires_review: bool = False


class PreviewResponse(BaseModel):
    pages: int
    field_count: int
    decisions: list[PreviewDecision]
    missing_required: list[str]
    unmapped_user_keys: list[str]


class FillReportResponse(BaseModel):
    """JSON fill outcome when the client asks for ``Accept: application/json``."""

    pages: int
    field_count: int
    written_fields: list[str]
    skipped_review_fields: list[str]
    skipped_empty_fields: list[str]
    skipped_unwritable_fields: list[str] = Field(
        default_factory=list,
        description="Mapped fields that could not be written (see FillReport)",
    )
    missing_required: list[str]
    unmapped_user_keys: list[str]
    decisions: list[PreviewDecision]
    pdf_base64: str = Field(
        description="Filled PDF encoded as standard base64 (not URL-safe)"
    )
