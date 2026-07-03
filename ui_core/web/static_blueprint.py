"""Blueprint serving static assets shared across the UI apps (e.g. chat.css)."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint

_STATIC = Path(__file__).resolve().parent.parent / "static"

static_bp = Blueprint(
    "ui_core", __name__, static_folder=str(_STATIC), static_url_path="/ui-core"
)
