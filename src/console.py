"""Console: serves the operator console page. Read off disk on every request
rather than baked into a template string, so editing static/console.html
never requires touching Python.
"""
from __future__ import annotations
import os
from fastapi.responses import HTMLResponse

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def render_console() -> HTMLResponse:
    path = os.path.join(STATIC_DIR, "console.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())
