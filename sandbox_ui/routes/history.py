"""Conversation-history endpoints.

Shared body lives in ``ui_core.web.blueprints.history``; this module wires
it up with sandbox_ui's ``cookies`` / ``services.conversation`` /
``services.images`` / ``services.files`` modules.
"""

from __future__ import annotations

from sandbox_ui import cookies
from sandbox_ui.services import conversation, files, images
from ui_core.web.blueprints.history import make_history_bp

history_bp = make_history_bp(
    cookies=cookies, conversation=conversation, images=images, files=files
)
