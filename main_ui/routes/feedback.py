"""Feedback route wiring for main_ui (shared body in ui_core)."""

from __future__ import annotations

from main_ui import cookies
from main_ui.services import conversation, feedback
from ui_core.web.blueprints.feedback import make_feedback_bp

feedback_bp = make_feedback_bp(cookies=cookies, conversation=conversation, feedback=feedback)
