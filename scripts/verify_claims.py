#!/usr/bin/env python3
"""Verify recruiter-facing README / docs claims against the live codebase.

Run from repo root with dependencies installed:

    PYTHONPATH=src python -m scripts.verify_claims
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SAMPLES = ROOT / "samples" / "sample_form.pdf"


def _ok(label: str) -> None:
    print(f"  ✓ {label}")


def _fail(label: str, detail: str) -> None:
    print(f"  ✗ {label}: {detail}")
    raise AssertionError(f"{label}: {detail}")


def claim_version_consistent() -> None:
    from pdf_autofiller import __version__
    from pdf_autofiller import api_service

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not match:
        _fail("version", "pyproject.toml version not found")
    if __version__ != match.group(1):
        _fail("version", f"package {__version__} != pyproject {match.group(1)}")
    if api_service.app.version != __version__:
        _fail("version", f"FastAPI app version {api_service.app.version} mismatch")
    _ok(f"version consistent ({__version__})")


def claim_sdk_fill() -> None:
    from pdf_autofiller import fill
    from pypdf import PdfReader

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "filled.pdf"
        fill(
            str(SAMPLES),
            {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
            str(out),
        )
        fields = PdfReader(str(out)).get_fields() or {}
        if fields.get("txtFirstName", {}).get("/V") != "Jane":
            _fail("sdk fill()", "txtFirstName was not written")
        if fields.get("txtLastName", {}).get("/V") != "Doe":
            _fail("sdk fill()", "txtLastName was not written")
    _ok("Python SDK fill() writes mapped AcroForm fields")


def claim_api_endpoints() -> None:
    from fastapi.testclient import TestClient

    from pdf_autofiller import api_service

    # Mirror local-dev / Docker-demo posture used in the README.
    original_auth = api_service.API_AUTH_ENABLED
    api_service.API_AUTH_ENABLED = False
    client = TestClient(api_service.app)
    try:
        health = client.get("/health")
        if health.status_code != 200:
            _fail("GET /health", f"status {health.status_code}")
        payload = health.json()
        for key in ("status", "service", "version", "checks"):
            if key not in payload:
                _fail("GET /health", f"missing key {key}")
        if "alias_pack_count" not in payload["checks"]:
            _fail("GET /health", "missing checks.alias_pack_count")
        _ok("GET /health returns status + alias pack checks")

        version = client.get("/version")
        if version.status_code != 200 or "version" not in version.json():
            _fail("GET /version", "unexpected response")
        _ok("GET /version returns service version")

        playground = client.get("/playground")
        if playground.status_code != 200 or "PDF Autofiller" not in playground.text:
            _fail("GET /playground", "HTML playground missing")
        match = re.search(
            r'<textarea id="userData"[^>]*>(.*?)</textarea>',
            playground.text,
            re.DOTALL,
        )
        if not match:
            _fail("GET /playground", "userData textarea missing")
        json.loads(match.group(1))
        _ok("GET /playground ships with valid default JSON")

        root = client.get("/", follow_redirects=False)
        if root.status_code not in (307, 308) or root.headers.get("location") != "/playground":
            _fail("GET /", "does not redirect to /playground")
        _ok("GET / redirects to /playground")

        with SAMPLES.open("rb") as handle:
            response = client.post(
                "/fill",
                files={"pdf_file": ("sample_form.pdf", handle, "application/pdf")},
                data={
                    "user_data": json.dumps(
                        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"}
                    ),
                    "strict": "true",
                },
            )
        if response.status_code != 200:
            _fail("POST /fill", f"status {response.status_code}: {response.text[:200]}")
        if "application/pdf" not in response.headers.get("content-type", ""):
            _fail("POST /fill", "content-type is not application/pdf")
        if int(response.headers.get("X-PDF-Fields-Written", "0")) < 3:
            _fail("POST /fill", "expected at least 3 fields written")
        _ok("POST /fill returns filled PDF with report headers")
    finally:
        api_service.API_AUTH_ENABLED = original_auth


def claim_alias_packs() -> None:
    from pdf_autofiller.mapping import FIELD_ALIASES, alias_pack_status

    status = alias_pack_status()
    if int(status["alias_pack_count"]) < 2:
        _fail("alias packs", f"expected >=2 packs, got {status}")
    for key in ("taxpayer_name", "business_name", "start_date", "employee_id"):
        if key not in FIELD_ALIASES:
            _fail("alias packs", f"missing semantic key {key}")
    variants = {variant for values in FIELD_ALIASES.values() for variant in values}
    for variant in ("name_line_1", "hire_date", "emp_id"):
        if variant not in variants:
            _fail("alias packs", f"missing user-data variant {variant}")
    _ok("W-9 and HR alias packs load into FIELD_ALIASES")


def claim_test_count_and_coverage() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-q",
            "--cov=src",
            "--cov-report=term",
            "--cov-fail-under=85",
        ],
        cwd=ROOT,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        _fail("pytest + coverage", output[-1500:])
    match = re.search(r"(\d+) passed", output)
    if not match:
        _fail("pytest + coverage", "could not parse passed count")
    passed = int(match.group(1))
    if passed < 107:
        _fail("pytest + coverage", f"expected >=107 tests, got {passed}")
    cov = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
    if not cov:
        _fail("pytest + coverage", "could not parse TOTAL coverage")
    coverage = int(cov.group(1))
    if coverage < 85:
        _fail("pytest + coverage", f"coverage {coverage}% < 85%")
    _ok(f"{passed} tests passed with {coverage}% coverage (>=85%)")


def claim_docs_and_assets_exist() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "Dockerfile",
        ROOT / "render.yaml",
        ROOT / "docs" / "API.md",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "OPERATIONS.md",
        ROOT / "docs" / "TESTING.md",
        ROOT / "recipes" / "w9.md",
        ROOT / "recipes" / "hr-onboarding.md",
        ROOT / "recipes" / "sample-form.sh",
        ROOT / "docs" / "assets" / "social-preview.png",
        ROOT / "docs" / "assets" / "playground-preview.png",
        SAMPLES,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        _fail("docs/assets", f"missing: {', '.join(missing)}")
    _ok("documented files, recipes, Docker, and assets exist")


def main() -> int:
    print("=" * 60)
    print("PDF Autofiller — claim verification")
    print("=" * 60)
    checks = [
        claim_version_consistent,
        claim_sdk_fill,
        claim_api_endpoints,
        claim_alias_packs,
        claim_docs_and_assets_exist,
        claim_test_count_and_coverage,
    ]
    failures = 0
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - surface every claim failure
            failures += 1
            print(f"  ! {check.__name__} failed: {exc}")
    print("=" * 60)
    if failures:
        print(f"FAILED: {failures} claim group(s)")
        return 1
    print("All recruiter-facing claims verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
