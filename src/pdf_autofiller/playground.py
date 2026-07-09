"""Web playground UI for trying PDF Autofiller in the browser."""

from pathlib import Path

PLAYGROUND_HTML = (Path(__file__).parent / "static" / "playground.html").read_text(encoding="utf-8")
