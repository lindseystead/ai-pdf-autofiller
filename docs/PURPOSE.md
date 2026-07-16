# Purpose

## Problem

PDF form automation usually fails on field-name mismatch. User data keys (`first_name`) often do not match AcroForm field names (`txtFirstName`, `field_12`), and manual mapping does not scale.

## What This Project Provides

This repository provides a deterministic-first pipeline to:

1. Read fillable fields and text from a PDF.
2. Infer field semantics (optional model-backed path).
3. Map user data to fields with normalization, aliases, and type coercion.
4. Write values to an output PDF while enforcing required-field rules.

## Core Use Cases

- Reusable profile data mapped across multiple PDF forms.
- Semi-structured intake workflows where field names vary by template.
- Batch processing where deterministic mapping behavior is preferred.

## Safety and Review Behavior

- Deterministic mapping runs without optional provider-backed inference.
- Ambiguous coercions are flagged with `requires_review`.
- Missing required fields are surfaced before output is finalized.

## Scope Notes

- The current implementation targets PDF forms (AcroForm-style field extraction/writing through `pypdf`).
- Non-fillable scanned PDFs and OCR-heavy flows are outside current scope.
- Optional provider-backed inference depends on external service availability and credentials.
