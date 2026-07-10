"""Feedback route wiring for sandbox_ui (shared body in ui_core)."""

from __future__ import annotations

from sandbox_ui import cookies
from sandbox_ui.services import conversation, feedback
from ui_core.web.blueprints.feedback import make_feedback_bp

feedback_bp = make_feedback_bp(cookies=cookies, conversation=conversation, feedback=feedback)
