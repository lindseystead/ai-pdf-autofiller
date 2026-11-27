"""Web playground UI for trying PDF Autofiller in the browser."""

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
PLAYGROUND_HTML = (STATIC_DIR / "playground.html").read_text(encoding="utf-8")
PLAYGROUND_CSS_PATH = STATIC_DIR / "playground.css"
PLAYGROUND_JS_PATH = STATIC_DIR / "playground.js"
