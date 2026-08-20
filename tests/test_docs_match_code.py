"""
Documentation must describe the software that exists.

These docs went stale once already: `docs/API.md` described `POST /fill` and
`GET /health` long after the service had grown `/v1`, inspect, templates, and
profiles, and the CLI — by then the main feature — appeared nowhere. Prose has
no compiler, so the only thing that keeps it honest is a test.

Each check here is deliberately one-directional: documenting something that does
not exist is a bug, while not documenting everything that exists is a judgement
call these tests do not make (except for the specific surfaces asserted below,
which are the ones users cannot discover any other way).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdf_autofiller import api_service
from pdf_autofiller.cli import build_parser
from pdf_autofiller.errors import PdfAutofillerError
from pdf_autofiller.settings import Settings

DOCS = Path(__file__).resolve().parents[1] / "docs"
README = Path(__file__).resolve().parents[1] / "README.md"


def _doc(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _registered_routes() -> set[str]:
    """Every path the app serves.

    Read from the OpenAPI schema rather than ``app.routes``: this FastAPI keeps
    an included router as an opaque wrapper, so walking ``app.routes`` reports
    that most of the API does not exist. The unversioned aliases are added back
    because they are registered with ``include_in_schema=False``.
    """
    paths = set(api_service.app.openapi()["paths"])
    paths |= {p[len("/v1") :] for p in paths if p.startswith("/v1/")}
    return paths


def _documented_env_vars() -> set[str]:
    """Env var names documented as `NAME` list items in OPERATIONS.md."""
    return set(re.findall(r"^- `([A-Z][A-Z0-9_]{3,})`", _doc("OPERATIONS.md"), re.M))


def _settings_env_names() -> set[str]:
    """Env var names Settings.from_env actually reads."""
    source = Path(Settings.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[1] / "src" / source).read_text(encoding="utf-8")
    body = text.split("def from_env", 1)[1]
    names = set(re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]{3,})"', body))
    names |= set(re.findall(r'_env_(?:bool|int|float|list)\(\s*"([A-Z][A-Z0-9_]{3,})"', body))
    return names


# --- endpoints -------------------------------------------------------------


def test_every_documented_endpoint_exists():
    """A path in the docs that the app does not serve is a broken promise."""
    documented = set(re.findall(r"`(?:GET|POST|PUT|DELETE)\s+(/[a-z0-9/_{}-]*)`", _doc("API.md")))
    documented |= set(re.findall(r"^### `(?:GET|POST|PUT|DELETE) (/[a-z0-9/_{}-]*)`", _doc("API.md"), re.M))
    assert documented, "no endpoints found in API.md — the parser is wrong, not the docs"

    registered = _registered_routes()
    missing = {path for path in documented if path not in registered}
    assert not missing, f"API.md documents endpoints that do not exist: {sorted(missing)}"


@pytest.mark.parametrize("path", ["/v1/inspect", "/v1/fill", "/v1/health", "/v1/templates/{name}"])
def test_user_facing_endpoints_are_documented(path):
    """These cannot be discovered without docs, so their absence is a real gap."""
    assert path in _doc("API.md"), f"{path} is served but undocumented in API.md"


# --- environment -----------------------------------------------------------


def test_every_documented_env_var_is_read():
    """Documenting a setting the code ignores sends operators chasing ghosts."""
    documented = _documented_env_vars()
    actual = _settings_env_names()
    stale = documented - actual
    assert not stale, f"OPERATIONS.md documents settings nothing reads: {sorted(stale)}"


def test_every_env_var_is_documented():
    """A setting nobody can find is a setting nobody can use."""
    undocumented = _settings_env_names() - _documented_env_vars()
    assert not undocumented, f"settings read but undocumented: {sorted(undocumented)}"


# --- CLI -------------------------------------------------------------------


def _cli_commands() -> set[str]:
    parser = build_parser()
    actions = [a for a in parser._actions if getattr(a, "choices", None) and hasattr(a, "dest")]
    for action in actions:
        if action.dest == "command":
            return set(action.choices)
    raise AssertionError("could not introspect CLI subcommands")


def test_every_cli_command_is_documented():
    """The CLI is the primary interface; an undocumented command is invisible."""
    doc = _doc("CLI.md")
    missing = {cmd for cmd in _cli_commands() if f"## `{cmd}`" not in doc}
    assert not missing, f"CLI commands missing a section in CLI.md: {sorted(missing)}"


def test_documented_cli_commands_exist():
    documented = set(re.findall(r"^## `([a-z-]+)`", _doc("CLI.md"), re.M))
    unknown = documented - _cli_commands()
    assert not unknown, f"CLI.md documents commands that do not exist: {sorted(unknown)}"


# --- errors ----------------------------------------------------------------


def _error_codes() -> set[str]:
    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    # RemotePdfAutofillerError carries whatever code it transported, not its own.
    return {
        sub.code
        for sub in walk(PdfAutofillerError)
        if sub.__name__ != "RemotePdfAutofillerError"
    }


def test_every_error_code_is_documented():
    """Clients branch on these codes, so each needs to be findable."""
    import pdf_autofiller.execution  # noqa: F401  (registers the remote error subclass)

    doc = _doc("API.md")
    missing = {code for code in _error_codes() if f"`{code}`" not in doc}
    assert not missing, f"error codes missing from the API.md table: {sorted(missing)}"


# --- cross-links -----------------------------------------------------------


def test_docs_index_and_readme_link_the_cli_reference():
    assert "CLI.md" in (DOCS / "README.md").read_text(encoding="utf-8"), (
        "docs/README.md does not link the CLI reference"
    )
    assert "CLI.md" in README.read_text(encoding="utf-8"), "README does not link the CLI reference"


def test_no_doc_links_to_a_missing_file():
    """A dead relative link is the cheapest possible way to lose a reader."""
    broken: list[str] = []
    for doc in DOCS.rglob("*.md"):
        for target in re.findall(r"\]\((?!https?://|#)([^)#]+)", doc.read_text(encoding="utf-8")):
            if not (doc.parent / target).exists():
                broken.append(f"{doc.relative_to(DOCS.parent)} -> {target}")
    assert not broken, f"broken relative links: {broken}"
