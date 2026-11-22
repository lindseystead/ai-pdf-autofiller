"""Parse a batch of records from JSON, JSONL, or CSV.

CSV cells stay strings. A cell that looks like a spreadsheet formula is data,
not something this process evaluates.
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Literal

from .errors import RecordsError
from .user_data import UserDataTooDeepError, validate_user_data_depth

# A batch shares the API's single job timeout, so the default stays small.
# Operators can raise it, up to a hard ceiling, with BATCH_MAX_RECORDS.
_BATCH_RECORD_CEILING = 500
MAX_RECORDS_BYTES = 1024 * 1024


def max_batch_records() -> int:
    """How many records one batch may contain."""
    raw = os.getenv("BATCH_MAX_RECORDS", "25")
    try:
        value = int(raw)
    except ValueError:
        return 25
    return max(1, min(value, _BATCH_RECORD_CEILING))


def parse_records(
    raw: str,
    *,
    fmt: Literal["json", "jsonl", "csv"],
    max_records: int | None = None,
) -> list[dict[str, Any]]:
    """Return one dict per record.

    Blank CSV rows are skipped. Blank cells are omitted so they are not written
    as empty strings. Duplicate CSV headers, extra columns, and NUL bytes are
    rejected.
    """
    limit = max_batch_records() if max_records is None else max_records
    if limit < 1:
        raise RecordsError("max_records must be at least 1")
    if "\x00" in raw:
        raise RecordsError("Records contain NUL bytes")

    if fmt == "csv":
        records = _parse_csv(raw)
    elif fmt == "jsonl":
        records = _parse_jsonl(raw)
    elif fmt == "json":
        records = _parse_json_array(raw)
    else:
        raise RecordsError(f"Unknown records format: {fmt}")

    if not records:
        raise RecordsError("Records must contain at least one object")
    if len(records) > limit:
        raise RecordsError(
            f"Records exceed the limit of {limit}",
            code="too_many_records",
        )
    for index, record in enumerate(records):
        try:
            validate_user_data_depth(record)
        except UserDataTooDeepError as exc:
            raise RecordsError(f"Record {index} is nested too deeply") from exc
    return records


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecordsError(f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise RecordsError("Records file must be a JSON array of objects")
    return [_object_record(index, item) for index, item in enumerate(parsed)]


def _parse_jsonl(raw: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecordsError(f"Invalid JSON on line {line_number}: {exc}") from exc
        records.append(_object_record(len(records), parsed))
    return records


def _parse_csv(raw: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise RecordsError("CSV has no header row")
    headers = ["" if name is None else name.strip() for name in reader.fieldnames]
    if any(not name for name in headers):
        raise RecordsError("CSV header has an empty column")
    if len(headers) != len(set(headers)):
        raise RecordsError("CSV header has a duplicate column")

    records: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise RecordsError(f"CSV row {row_number} has more columns than the header")
        item: dict[str, str] = {}
        for key, value in row.items():
            name = (key or "").strip()
            cell = "" if value is None else value.strip()
            if cell:
                item[name] = cell
        if item:
            records.append(item)
    return records


def _object_record(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RecordsError(f"Record {index} must be a JSON object")
    return item
