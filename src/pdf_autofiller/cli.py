"""
Command-line interface.

Filling one PDF used to mean starting a server and posting to it, because the
only console script was the API itself. That is the wrong shape for the way this
work usually arrives: a shell script, a cron job, or a person with a form and a
JSON file.

Every command runs the pipeline in-process. There is no server, no port, and no
auth token in the loop for local use.

    pdf-autofiller init form.pdf > me.json
    pdf-autofiller inspect form.pdf --data me.json
    pdf-autofiller fill form.pdf --data me.json --out filled.pdf --flatten
    pdf-autofiller extract filled.pdf --save-profile jane
    pdf-autofiller validate form.pdf
    pdf-autofiller profile set me --data me.json
    pdf-autofiller batch form.pdf --csv staff.csv --out-dir ./filled
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from . import __version__
from .errors import PdfAutofillerError
from .pipeline import (
    data_skeleton,
    extract_form_values,
    run_fill_pipeline,
    run_inspect_pipeline,
)
from .settings import get_settings
from .store import (
    Profile,
    Template,
    profile_store,
    resolve_fill_inputs,
    sanitize_name,
    template_store,
)


def _load_json(path: Optional[str], label: str) -> dict[str, Any]:
    """Read a JSON object from a file path, or '-' for stdin."""
    if not path:
        return {}
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {label} is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise SystemExit(f"error: {label} must be a JSON object")
    return parsed


def _emit(payload: Any, as_json: bool, text: str) -> None:
    """Print machine-readable JSON or a human summary."""
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(text)


def _resolve(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    """Combine --data, --profile, --template, and --set into the final inputs."""
    inline: dict[str, Any] = {}
    for assignment in getattr(args, "set", None) or []:
        key, sep, value = assignment.partition("=")
        if not sep:
            raise SystemExit(f"error: --set expects key=value, got {assignment!r}")
        inline[key] = value

    user_data = _load_json(getattr(args, "data", None), "--data")
    user_data.update(inline)

    overrides = _load_json(getattr(args, "overrides", None), "--overrides")
    data, resolved_overrides, _ = resolve_fill_inputs(
        template_name=getattr(args, "template", None),
        profile_name=getattr(args, "profile", None),
        user_data=user_data,
        overrides=overrides,
    )
    return data, resolved_overrides


def cmd_inspect(args: argparse.Namespace) -> int:
    """Show a form's fields and what a fill would do."""
    data, overrides = _resolve(args)
    settings = get_settings()
    report = run_inspect_pipeline(
        Path(args.pdf),
        data,
        strict=not args.allow_fallback,
        allow_fallback_mapping=args.allow_fallback,
        use_semantic_inference=args.infer,
        max_pages=settings.max_pdf_pages,
        max_text_chars=settings.max_pdf_text_chars,
        overrides=overrides,
    )

    if args.json:
        print(json.dumps(report.model_dump(), indent=2, default=str))
        return 0

    print(f"{args.pdf}: {len(report.fields)} fields, {report.metadata.num_pages} pages")
    print(f"fingerprint: {report.fingerprint}")
    print()
    decisions = {d.field_name: d for d in (report.mapping.decisions if report.mapping else [])}
    width = max((len(f.field.name) for f in report.fields), default=10)
    for enriched in report.fields:
        field = enriched.field
        decision = decisions.get(field.name)
        flags = []
        if field.required:
            flags.append("required")
        if field.options:
            flags.append(f"options={len(field.options)}")
        marker = " "
        if decision and not decision.requires_review and decision.selected_value is not None:
            marker = "+"
        elif decision and decision.requires_review:
            marker = "?"
        elif field.required:
            marker = "!"
        value = f" -> {decision.selected_value!r}" if decision else ""
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(
            f" {marker} {field.name:<{width}}  {field.field_type:<9} "
            f"{enriched.semantics.semantic_meaning}{suffix}{value}"
        )

    print()
    print(f"would write {len(report.would_write)}, would skip {len(report.would_skip)}")
    if report.mapping and report.mapping.missing_required:
        print(f"missing required: {', '.join(report.mapping.missing_required)}")
    if report.mapping and report.mapping.unmapped_user_keys:
        print(f"unused data keys: {', '.join(report.mapping.unmapped_user_keys)}")
    print("legend: + will fill   ? needs review   ! required and unmapped")
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    """Fill a form and write the result."""
    data, overrides = _resolve(args)
    settings = get_settings()
    output = Path(args.out) if args.out else Path(args.pdf).with_name(
        Path(args.pdf).stem + "_filled.pdf"
    )

    report, mapping, total = run_fill_pipeline(
        Path(args.pdf),
        output,
        data,
        strict=not args.allow_fallback,
        allow_fallback_mapping=args.allow_fallback,
        use_semantic_inference=args.infer,
        max_pages=settings.max_pdf_pages,
        max_text_chars=settings.max_pdf_text_chars,
        overrides=overrides,
        allow_key_reuse=not args.no_key_reuse,
        flatten=args.flatten,
    )

    payload = {
        "output": str(output),
        "fields_total": total,
        "report": report.model_dump(),
        "unmapped_user_keys": mapping.unmapped_user_keys,
    }
    summary = [f"wrote {output} ({len(report.written_fields)}/{total} fields)"]
    if report.skipped_review_fields:
        summary.append(f"  needs review: {', '.join(report.skipped_review_fields)}")
    if report.skipped_invalid_fields:
        summary.append(f"  invalid for field type: {', '.join(report.skipped_invalid_fields)}")
    if mapping.unmapped_user_keys:
        summary.append(f"  unused data keys: {', '.join(mapping.unmapped_user_keys)}")
    if report.flattened:
        summary.append("  flattened: form is no longer editable")
    _emit(payload, args.json, "\n".join(summary))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Read the values back out of an already-filled PDF."""
    settings = get_settings()
    values = extract_form_values(
        Path(args.pdf),
        raw=args.raw,
        include_empty=args.include_empty,
        max_pages=settings.max_pdf_pages,
        max_text_chars=settings.max_pdf_text_chars,
    )

    if args.save_profile:
        saved = profile_store().save(
            Profile(name=args.save_profile, description=f"Extracted from {args.pdf}", data=values)
        )
        _emit(
            saved.model_dump(),
            args.json,
            f"saved profile {saved.name} ({len(values)} values from {args.pdf})",
        )
        return 0

    # Default output is the data itself, so it can be piped straight to a file.
    print(json.dumps(values, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Emit a starter data file carrying the keys this form wants."""
    settings = get_settings()
    skeleton, annotations = data_skeleton(
        Path(args.pdf),
        max_pages=settings.max_pdf_pages,
        max_text_chars=settings.max_pdf_text_chars,
    )
    if not skeleton:
        print(f"error: {args.pdf} has no fillable form fields", file=sys.stderr)
        return 1

    if args.annotate:
        # JSON has no comments, so annotations ride alongside under a key the
        # mapper ignores rather than being emitted as invalid JSON.
        print(json.dumps({"_fields": annotations, **skeleton}, indent=2))
    else:
        print(json.dumps(skeleton, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Check that a PDF is a fillable AcroForm this tool can handle."""
    settings = get_settings()
    report = run_inspect_pipeline(
        Path(args.pdf), {}, max_pages=settings.max_pdf_pages,
        max_text_chars=settings.max_pdf_text_chars,
    )
    required = [f.field.name for f in report.fields if f.field.required]
    payload = {
        "ok": bool(report.fields),
        "fields": len(report.fields),
        "required_fields": required,
        "fingerprint": report.fingerprint,
        "pages": report.metadata.num_pages,
    }
    if not report.fields:
        _emit(payload, args.json, f"{args.pdf}: no fillable form fields found")
        return 1
    _emit(
        payload,
        args.json,
        f"{args.pdf}: ok, {len(report.fields)} fields "
        f"({len(required)} required), fingerprint {report.fingerprint}",
    )
    return 0


def _read_batch_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Load batch rows from either a JSON array or a CSV file.

    CSV exists because the people doing this work have spreadsheets, not JSON
    arrays; requiring a conversion step first is a tax on the most repetitive
    workflow the tool has. Each column header is a data key, and an optional
    ``name`` column names the output file.
    """
    if args.csv:
        rows: list[dict[str, Any]] = []
        with Path(args.csv).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise SystemExit(f"error: {args.csv} has no header row")
            for index, row in enumerate(reader):
                # Drop empty cells: a blank means "not supplied", and carrying it
                # through as "" would overwrite a profile value with nothing.
                data = {k: v for k, v in row.items() if k and v not in (None, "")}
                name = str(data.pop("name", f"row-{index + 1}"))
                rows.append({"name": name, "user_data": data})
        if not rows:
            raise SystemExit(f"error: {args.csv} contains no data rows")
        return rows

    raw = json.loads(Path(args.items).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("error: --items must be a JSON array")
    return raw


def cmd_batch(args: argparse.Namespace) -> int:
    """Fill one form once per row of data."""
    raw = _read_batch_items(args)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    results = []
    failures = 0
    for index, item in enumerate(raw):
        name = str(item.get("name", f"item-{index}"))
        target = out_dir / f"{sanitize_name(name)}_filled.pdf"
        try:
            report, _, _ = run_fill_pipeline(
                Path(args.pdf),
                target,
                item.get("user_data", {}),
                strict=not args.allow_fallback,
                allow_fallback_mapping=args.allow_fallback,
                use_semantic_inference=args.infer,
                max_pages=settings.max_pdf_pages,
                max_text_chars=settings.max_pdf_text_chars,
                overrides=item.get("overrides"),
                flatten=args.flatten,
            )
            results.append(
                {"name": name, "status": "ok", "output": str(target),
                 "fields_written": len(report.written_fields)}
            )
            if not args.json:
                print(f"  ok    {name} -> {target}")
        except (PdfAutofillerError, OSError, ValueError) as exc:
            # One bad row must not discard the rest of the batch.
            failures += 1
            code = getattr(exc, "code", type(exc).__name__)
            results.append({"name": name, "status": "failed", "error": str(exc), "code": code})
            if not args.json:
                print(f"  FAIL  {name}: {exc}", file=sys.stderr)

    payload = {"total": len(raw), "failed": failures, "items": results}
    _emit(payload, args.json, f"\n{len(raw) - failures}/{len(raw)} filled into {out_dir}")
    return 1 if failures else 0


def cmd_profile(args: argparse.Namespace) -> int:
    """Manage named user-data profiles."""
    store = profile_store()
    if args.profile_action == "list":
        items = store.list()
        _emit(
            [{"name": p.name, "keys": sorted(p.data)} for p in items],
            args.json,
            "\n".join(f"{p.name}  ({len(p.data)} keys)" for p in items) or "no profiles",
        )
    elif args.profile_action == "set":
        profile = Profile(
            name=args.name, description=args.description or "", data=_load_json(args.data, "--data")
        )
        saved = store.save(profile)
        _emit(saved.model_dump(), args.json, f"saved profile {saved.name}")
    elif args.profile_action == "show":
        _emit(store.get(args.name).model_dump(), args.json, json.dumps(store.get(args.name).data, indent=2))
    elif args.profile_action == "delete":
        store.delete(args.name)
        _emit({"deleted": args.name}, args.json, f"deleted profile {args.name}")
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    """Manage form templates."""
    store = template_store()
    if args.template_action == "list":
        items = store.list()
        _emit(
            [t.model_dump() for t in items],
            args.json,
            "\n".join(f"{t.name}  {t.fingerprint}  {t.description}" for t in items)
            or "no templates",
        )
    elif args.template_action == "save":
        settings = get_settings()
        report = run_inspect_pipeline(
            Path(args.pdf), {}, max_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_pdf_text_chars,
        )
        template = Template(
            name=args.name,
            fingerprint=report.fingerprint,
            description=args.description or "",
            overrides=_load_json(args.overrides, "--overrides"),
            flatten=args.flatten,
        )
        saved = store.save(template)
        _emit(saved.model_dump(), args.json, f"saved template {saved.name} ({saved.fingerprint})")
    elif args.template_action == "delete":
        store.delete(args.name)
        _emit({"deleted": args.name}, args.json, f"deleted template {args.name}")
    return 0


def _add_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", help="JSON file of user data, or - for stdin")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE",
                        help="Inline data value; repeatable, wins over --data")
    parser.add_argument("--profile", help="Name of a stored profile to use as base data")
    parser.add_argument("--template", help="Name of a stored template to apply")
    parser.add_argument("--overrides", help="JSON file of explicit field_name -> value")
    parser.add_argument("--infer", action="store_true",
                        help="Use the model provider to infer field meanings")
    parser.add_argument("--allow-fallback", action="store_true",
                        help="Let the provider resolve fields deterministic matching missed")


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="pdf-autofiller", description="Fill AcroForm PDFs from JSON."
    )
    parser.add_argument("--version", action="version", version=f"pdf-autofiller {__version__}")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="List a form's fields and preview a fill")
    p_inspect.add_argument("pdf")
    _add_data_args(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect)

    p_fill = sub.add_parser("fill", help="Fill a form and write the result")
    p_fill.add_argument("pdf")
    p_fill.add_argument("--out", help="Output path (default: <input>_filled.pdf)")
    p_fill.add_argument("--flatten", action="store_true",
                        help="Remove the interactive form so the result cannot be edited")
    p_fill.add_argument("--no-key-reuse", action="store_true",
                        help="Use each data key for at most one field")
    _add_data_args(p_fill)
    p_fill.set_defaults(func=cmd_fill)

    p_init = sub.add_parser("init", help="Emit a starter data file for a form")
    p_init.add_argument("pdf")
    p_init.add_argument("--annotate", action="store_true",
                        help="Include a _fields block describing each key")
    p_init.set_defaults(func=cmd_init)

    p_extract = sub.add_parser("extract", help="Read values out of a filled PDF")
    p_extract.add_argument("pdf")
    p_extract.add_argument("--raw", action="store_true",
                           help="Key by exact PDF field name instead of semantic meaning")
    p_extract.add_argument("--include-empty", action="store_true",
                           help="Include fields that have no value")
    p_extract.add_argument("--save-profile", metavar="NAME",
                           help="Save the extracted values as a named profile")
    p_extract.set_defaults(func=cmd_extract)

    p_validate = sub.add_parser("validate", help="Check a PDF is a fillable AcroForm")
    p_validate.add_argument("pdf")
    p_validate.set_defaults(func=cmd_validate)

    p_batch = sub.add_parser("batch", help="Fill one form once per row of data")
    p_batch.add_argument("pdf")
    batch_source = p_batch.add_mutually_exclusive_group(required=True)
    batch_source.add_argument("--items", help="JSON array of {name, user_data}")
    batch_source.add_argument("--csv", help="CSV file; each column is a data key")
    p_batch.add_argument("--out-dir", default="./filled")
    p_batch.add_argument("--flatten", action="store_true")
    p_batch.add_argument("--infer", action="store_true")
    p_batch.add_argument("--allow-fallback", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    p_profile = sub.add_parser("profile", help="Manage reusable data profiles")
    ps = p_profile.add_subparsers(dest="profile_action", required=True)
    ps.add_parser("list")
    p_set = ps.add_parser("set")
    p_set.add_argument("name")
    p_set.add_argument("--data", required=True)
    p_set.add_argument("--description")
    p_show = ps.add_parser("show")
    p_show.add_argument("name")
    p_del = ps.add_parser("delete")
    p_del.add_argument("name")
    p_profile.set_defaults(func=cmd_profile)

    p_template = sub.add_parser("template", help="Manage form templates")
    ts = p_template.add_subparsers(dest="template_action", required=True)
    ts.add_parser("list")
    t_save = ts.add_parser("save")
    t_save.add_argument("name")
    t_save.add_argument("pdf")
    t_save.add_argument("--overrides")
    t_save.add_argument("--description")
    t_save.add_argument("--flatten", action="store_true")
    t_del = ts.add_parser("delete")
    t_del.add_argument("name")
    p_template.set_defaults(func=cmd_template)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except PdfAutofillerError as exc:
        # Typed pipeline errors already carry an actionable message.
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
