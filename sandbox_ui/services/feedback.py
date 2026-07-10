"""sandbox_ui binding of the shared feedback service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from sandbox_ui.db.models import Feedback
from ui_core.services import feedback as _shared


def record_feedback(db: Session, *, conversation_id, turn, rating):
    """Insert one Feedback row (rating 1..5), linked to *conversation_id*."""
    return _shared.record_feedback(
        db, conversation_id=conversation_id, turn=turn, rating=rating, feedback_cls=Feedback
    )
