"""Flask app for the main_ui production-shape tutor."""

from __future__ import annotations

from main_ui.config import load_config
from main_ui.db import SessionLocal
from main_ui.routes.chat import chat_bp
from main_ui.routes.embed import embed_bp
from main_ui.routes.history import history_bp
from main_ui.routes.identity import identity_bp
from ui_core.app_factory import create_app

app = create_app(
    import_name=__name__,
    config=load_config(),
    service_name="main_ui",
    session_local=SessionLocal,
    blueprints=[embed_bp, identity_bp, chat_bp, history_bp],
)
