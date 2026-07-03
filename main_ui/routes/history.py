"""Conversation-history endpoints.

Shared body lives in ``ui_core.web.blueprints.history``; this module wires
it up with main_ui's ``cookies`` / ``services.conversation`` /
``services.images`` modules.
"""

from __future__ import annotations

from main_ui import cookies
from main_ui.services import conversation, images
from ui_core.web.blueprints.history import make_history_bp

history_bp = make_history_bp(cookies=cookies, conversation=conversation, images=images)
