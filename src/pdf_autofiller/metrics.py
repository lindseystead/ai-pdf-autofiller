"""
Prometheus-format metrics, without a Prometheus client dependency.

The audit log records what happened per request, which answers "what did this
one fill do" but not "is mapping quality getting worse". The numbers that matter
for this service are aggregate: fill success rate, how much of each form gets
populated, how often decisions land in review, and provider latency.

The exposition format is simple enough that emitting it directly is cheaper than
taking on a dependency for a handful of counters. Everything is process-local,
so a multi-worker deployment scrapes each worker (the usual Prometheus model).
"""

from __future__ import annotations

import threading
from typing import Iterable

_lock = threading.Lock()

_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}

# Buckets chosen around this workload: sub-second deterministic fills, multi-
# second fills once inference is involved, and a tail that catches the timeout.
_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 60.0)

_HELP = {
    "pdf_autofiller_fills_total": "Fill attempts by outcome.",
    "pdf_autofiller_inspects_total": "Inspect (dry-run) requests by outcome.",
    "pdf_autofiller_fields_written_total": "Form fields populated across all fills.",
    "pdf_autofiller_fields_skipped_total": "Form fields skipped, by reason.",
    "pdf_autofiller_provider_calls_total": "Model provider calls by outcome.",
    "pdf_autofiller_request_duration_seconds": "Request handling time by endpoint.",
    "pdf_autofiller_provider_duration_seconds": "Model provider call latency.",
}

_TYPES = {
    "pdf_autofiller_fills_total": "counter",
    "pdf_autofiller_inspects_total": "counter",
    "pdf_autofiller_fields_written_total": "counter",
    "pdf_autofiller_fields_skipped_total": "counter",
    "pdf_autofiller_provider_calls_total": "counter",
    "pdf_autofiller_request_duration_seconds": "histogram",
    "pdf_autofiller_provider_duration_seconds": "histogram",
}


def _key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((labels or {}).items()))


def increment(name: str, value: float = 1.0, **labels: str) -> None:
    """Add to a counter series."""
    with _lock:
        key = (name, _key(labels))
        _counters[key] = _counters.get(key, 0.0) + value


def observe(name: str, value: float, **labels: str) -> None:
    """Record an observation into a histogram series."""
    with _lock:
        key = (name, _key(labels))
        _histograms.setdefault(key, []).append(value)


def reset() -> None:
    """Clear all series (used by tests)."""
    with _lock:
        _counters.clear()
        _histograms.clear()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_labels(labels: tuple[tuple[str, str], ...], extra: str = "") -> str:
    parts = [f'{k}="{_escape(v)}"' for k, v in labels]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


def render() -> str:
    """Render all series in Prometheus text exposition format."""
    with _lock:
        counters = dict(_counters)
        histograms = {k: list(v) for k, v in _histograms.items()}

    lines: list[str] = []
    emitted: set[str] = set()

    def header(name: str) -> None:
        if name in emitted:
            return
        emitted.add(name)
        if name in _HELP:
            lines.append(f"# HELP {name} {_HELP[name]}")
        if name in _TYPES:
            lines.append(f"# TYPE {name} {_TYPES[name]}")

    for (name, labels), value in sorted(counters.items()):
        header(name)
        lines.append(f"{name}{_render_labels(labels)} {value:g}")

    for (name, labels), values in sorted(histograms.items()):
        header(name)
        ordered = sorted(values)
        cumulative = 0
        index = 0
        # Bucket labels are assembled outside the f-string: Python 3.11 rejects
        # backslashes inside f-string expressions, and these need quote escapes.
        for bound in _DURATION_BUCKETS:
            while index < len(ordered) and ordered[index] <= bound:
                cumulative += 1
                index += 1
            le_label = 'le="{:g}"'.format(bound)
            lines.append(f"{name}_bucket{_render_labels(labels, le_label)} {cumulative}")
        inf_label = 'le="+Inf"'
        lines.append(f"{name}_bucket{_render_labels(labels, inf_label)} {len(ordered)}")
        lines.append(f"{name}_sum{_render_labels(labels)} {sum(ordered):g}")
        lines.append(f"{name}_count{_render_labels(labels)} {len(ordered)}")

    return "\n".join(lines) + "\n" if lines else "\n"


def series_names() -> Iterable[str]:
    """Names of series currently holding data."""
    with _lock:
        return {name for name, _ in _counters} | {name for name, _ in _histograms}
