"""Command-line interface for local PDF fill / inspect / preview."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import click

from pdf_autofiller import __version__
from pdf_autofiller.errors import PdfAutofillerError
from pdf_autofiller.field_semantics import SemanticClient
from pdf_autofiller.pipeline import fill, fill_batch, fill_template, inspect, preview, preview_batch
from pdf_autofiller.records import parse_records


@contextmanager
def _user_errors() -> Iterator[None]:
    """Turn expected input/output failures into a one-line error, not a traceback."""
    try:
        yield
    except PdfAutofillerError as exc:
        raise click.ClickException(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(f"File error: {exc}") from exc


def _load_records(path: Path, *, fmt: Literal["json", "jsonl", "csv"]) -> list[dict[str, Any]]:
    """Load records as a JSON array, JSONL, or CSV."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise click.ClickException(f"Could not read records file: {exc}") from exc
    return parse_records(raw, fmt=fmt)


def _load_user_data(data_file: Path | None, data_json: str | None) -> dict[str, Any]:
    """Load user data from ``--data`` JSON or a JSON file path (``-`` = stdin)."""
    if data_json is not None and data_file is not None:
        raise click.UsageError("Pass either DATA_JSON file or --data, not both.")
    if data_json is None and data_file is None:
        raise click.UsageError("Provide a DATA_JSON file or --data='{}'.")

    raw: str
    if data_json is not None:
        raw = data_json
    elif data_file is not None and str(data_file) == "-":
        raw = sys.stdin.read()
    else:
        assert data_file is not None
        try:
            raw = data_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Could not read data file: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.ClickException("User data must be a JSON object (dict).")
    return parsed


def _require_provider_for(*, use_ai: bool, strict: bool) -> None:
    """--ai and --no-strict only do anything with a working AI provider; say so up front."""
    if (use_ai or not strict) and not SemanticClient().is_available():
        flag = "--ai" if use_ai else "--no-strict"
        raise click.UsageError(f"{flag} needs MODEL_PROVIDER_API_KEY and the openai package")


def _echo_json(payload: Any) -> None:
    click.echo(json.dumps(payload, indent=2, default=str))


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="pdf-autofiller")
def main() -> None:
    """Fill AcroForm PDFs from JSON — inspect, preview, or fill locally."""


@main.command("version")
def version_cmd() -> None:
    """Print the package version."""
    click.echo(__version__)


@main.command("inspect")
@click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--max-pages",
    type=int,
    default=None,
    help="Only read the first N pages.",
)
@click.option(
    "--template",
    is_flag=True,
    default=False,
    help="Print a starter JSON object for this form instead of the field inventory.",
)
def inspect_cmd(pdf: Path, max_pages: int | None, template: bool) -> None:
    """List AcroForm fields in PDF as JSON."""
    with _user_errors():
        result = fill_template(pdf, max_pages=max_pages) if template else inspect(pdf, max_pages=max_pages)
    _echo_json(result.model_dump(mode="json"))


@main.command("preview")
@click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("data_json", required=False, type=click.Path(path_type=Path))
@click.option(
    "--data",
    "data_inline",
    default=None,
    help='Inline JSON object, e.g. \'{"firstname":"Jane"}\'.',
)
@click.option(
    "--strict/--no-strict",
    default=True,
    show_default=True,
    help="--no-strict enables the AI key fallback for unresolved fields (needs MODEL_PROVIDER_API_KEY).",
)
@click.option(
    "--ai/--no-ai",
    "use_ai",
    default=False,
    show_default=True,
    help="Enable AI field inference (needs MODEL_PROVIDER_API_KEY).",
)
def preview_cmd(
    pdf: Path,
    data_json: Path | None,
    data_inline: str | None,
    strict: bool,
    use_ai: bool,
) -> None:
    """Preview mapping decisions without writing a PDF."""
    _require_provider_for(use_ai=use_ai, strict=strict)
    user_data = _load_user_data(data_json, data_inline)
    with _user_errors():
        result = preview(
            pdf,
            user_data,
            strict=strict,
            allow_fallback_mapping=not strict,
            use_semantic_inference=use_ai,
        )
    _echo_json(result.model_dump(mode="json"))


@main.command("fill")
@click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("data_json", required=False, type=click.Path(path_type=Path))
@click.option(
    "--data",
    "data_inline",
    default=None,
    help='Inline JSON object, e.g. \'{"firstname":"Jane"}\'.',
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output PDF path (default: <pdf>_filled.pdf).",
)
@click.option(
    "--strict/--no-strict",
    default=True,
    show_default=True,
    help="--no-strict enables the AI key fallback for unresolved fields (needs MODEL_PROVIDER_API_KEY).",
)
@click.option(
    "--ai/--no-ai",
    "use_ai",
    default=False,
    show_default=True,
    help="Enable AI field inference (needs MODEL_PROVIDER_API_KEY).",
)
@click.option(
    "--flatten/--no-flatten",
    default=False,
    show_default=True,
    help="Flatten form fields into page content.",
)
@click.option(
    "--allow-partial/--no-allow-partial",
    default=False,
    show_default=True,
    help="Write the PDF even when required fields are unresolved (listed in the report).",
)
@click.option(
    "--json-report",
    is_flag=True,
    default=False,
    help="Print the fill report as JSON to stdout.",
)
def fill_cmd(
    pdf: Path,
    data_json: Path | None,
    data_inline: str | None,
    output: Path | None,
    strict: bool,
    use_ai: bool,
    flatten: bool,
    allow_partial: bool,
    json_report: bool,
) -> None:
    """Fill PDF with JSON user data and write an output PDF."""
    _require_provider_for(use_ai=use_ai, strict=strict)
    user_data = _load_user_data(data_json, data_inline)
    out = output or pdf.with_name(f"{pdf.stem}_filled{pdf.suffix}")
    with _user_errors():
        report = fill(
            pdf,
            user_data,
            out,
            strict=strict,
            allow_fallback_mapping=not strict,
            use_semantic_inference=use_ai,
            flatten=flatten,
            allow_partial=allow_partial,
        )

    if json_report:
        payload = report.model_dump(mode="json")
        payload["output"] = str(out)
        _echo_json(payload)
    else:
        written = len(report.written_fields)
        click.echo(f"Wrote {out} ({written} field{'s' if written != 1 else ''} written)")
        if report.ai_assisted_fields:
            click.echo(
                "Mapped by AI (review these): " + ", ".join(report.ai_assisted_fields),
                err=True,
            )
        if report.missing_required_fields:
            click.echo(
                "Required fields still empty: " + ", ".join(report.missing_required_fields),
                err=True,
            )


@main.command("batch")
@click.argument("pdf", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("records", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for one PDF per record. Also receives fill-report.json.",
)
@click.option(
    "--filename-key",
    default=None,
    help="Record field used as the PDF filename. Unsafe characters are replaced.",
)
@click.option(
    "--jsonl",
    is_flag=True,
    default=False,
    help="Read one JSON object per line instead of a JSON array.",
)
@click.option(
    "--csv",
    "csv_mode",
    is_flag=True,
    default=False,
    help="Read a CSV with a header row. Also assumed for a .csv path.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be written. Creates no PDFs and no report file.",
)
@click.option(
    "--stop-on-error/--continue-on-error",
    default=False,
    show_default=True,
    help="Stop at the first record that cannot be filled. The default keeps going.",
)
@click.option("--strict/--no-strict", default=True, show_default=True)
@click.option("--ai/--no-ai", "use_ai", default=False, show_default=True)
@click.option("--flatten/--no-flatten", default=False, show_default=True)
@click.option("--allow-partial/--no-allow-partial", default=False, show_default=True)
@click.pass_context
def batch_cmd(
    ctx: click.Context,
    pdf: Path,
    records: Path,
    output_dir: Path,
    filename_key: str | None,
    jsonl: bool,
    csv_mode: bool,
    dry_run: bool,
    stop_on_error: bool,
    strict: bool,
    use_ai: bool,
    flatten: bool,
    allow_partial: bool,
) -> None:
    """Fill one PDF template for every record in a JSON list or CSV."""
    if jsonl and csv_mode:
        raise click.UsageError("Pass either --jsonl or --csv, not both.")
    if not dry_run and output_dir is None:
        raise click.UsageError("-o/--output-dir is required unless --dry-run.")
    _require_provider_for(use_ai=use_ai, strict=strict)
    fmt: Literal["json", "jsonl", "csv"]
    if csv_mode or records.suffix.lower() == ".csv":
        fmt = "csv"
    elif jsonl:
        fmt = "jsonl"
    else:
        fmt = "json"
    with _user_errors():
        loaded = _load_records(records, fmt=fmt)
        on_error: Literal["continue", "stop"] = "stop" if stop_on_error else "continue"
        if dry_run:
            report = preview_batch(
                pdf,
                loaded,
                on_error=on_error,
                strict=strict,
                allow_fallback_mapping=not strict,
                use_semantic_inference=use_ai,
                allow_partial=allow_partial,
            )
        else:
            assert output_dir is not None
            report = fill_batch(
                pdf,
                loaded,
                output_dir,
                filename_key=filename_key,
                on_error=on_error,
                strict=strict,
                allow_fallback_mapping=not strict,
                use_semantic_inference=use_ai,
                flatten=flatten,
                allow_partial=allow_partial,
            )
    payload = report.model_dump(mode="json")
    _echo_json(payload)
    if report.failed:
        ctx.exit(1)


if __name__ == "__main__":
    main()
