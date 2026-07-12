"""Per-message rating route wiring for sandbox_ui (shared body in ui_core)."""

from __future__ import annotations

from sandbox_ui import cookies
from sandbox_ui.services import conversation
from ui_core.web.blueprints.message_rating import make_message_rating_bp

message_rating_bp = make_message_rating_bp(cookies=cookies, conversation=conversation)
