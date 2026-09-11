"""Command-line interface for local PDF fill / inspect / preview."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from pdf_autofiller import __version__
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError
from pdf_autofiller.pipeline import fill, inspect, preview


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
def inspect_cmd(pdf: Path, max_pages: int | None) -> None:
    """List AcroForm fields in PDF as JSON."""
    result = inspect(pdf, max_pages=max_pages)
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
    help="Disable AI fallback mapping when strict (default).",
)
@click.option(
    "--ai/--no-ai",
    "use_ai",
    default=False,
    show_default=True,
    help="Enable optional semantic inference (needs MODEL_PROVIDER_API_KEY).",
)
def preview_cmd(
    pdf: Path,
    data_json: Path | None,
    data_inline: str | None,
    strict: bool,
    use_ai: bool,
) -> None:
    """Preview mapping decisions without writing a PDF."""
    user_data = _load_user_data(data_json, data_inline)
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
    help="Disable AI fallback mapping when strict (default).",
)
@click.option(
    "--ai/--no-ai",
    "use_ai",
    default=False,
    show_default=True,
    help="Enable optional semantic inference (needs MODEL_PROVIDER_API_KEY).",
)
@click.option(
    "--flatten/--no-flatten",
    default=False,
    show_default=True,
    help="Flatten form fields into page content.",
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
    json_report: bool,
) -> None:
    """Fill PDF with JSON user data and write an output PDF."""
    user_data = _load_user_data(data_json, data_inline)
    out = output or pdf.with_name(f"{pdf.stem}_filled{pdf.suffix}")
    try:
        report = fill(
            pdf,
            user_data,
            out,
            strict=strict,
            allow_fallback_mapping=not strict,
            use_semantic_inference=use_ai,
            flatten=flatten,
        )
    except UnresolvedRequiredFieldsError as exc:
        raise click.ClickException(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(f"Could not write output PDF: {exc}") from exc

    if json_report:
        payload = report.model_dump(mode="json")
        payload["output"] = str(out)
        _echo_json(payload)
    else:
        written = len(report.written_fields)
        click.echo(f"Wrote {out} ({written} field{'s' if written != 1 else ''} written)")


if __name__ == "__main__":
    main()
