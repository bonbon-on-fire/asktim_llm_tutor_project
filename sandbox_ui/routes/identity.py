"""Identity routes — session state plus username+password linking.

Shared body lives in ``ui_core.web.blueprints.identity``; this module wires
it up with sandbox_ui's ``cookies`` / ``services.conversation`` /
``services.students`` modules.
"""

from __future__ import annotations

from sandbox_ui import cookies
from sandbox_ui.services import conversation, students
from ui_core.web.blueprints.identity import make_identity_bp

identity_bp = make_identity_bp(cookies=cookies, conversation=conversation, students=students)
