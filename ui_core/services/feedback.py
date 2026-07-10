"""Shared service for recording student tutor-ratings (the ``feedback`` table).

App-agnostic: the ``Feedback`` model class is passed in so each app binds its
own (mirrors :mod:`ui_core.services.files` / :mod:`ui_core.services.images`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def record_feedback(
    db: Session,
    *,
    conversation_id,
    turn: int | None,
    rating: int,
    feedback_cls: type,
) -> Any:
    """Insert one feedback row (rating 1..5) linked to a conversation."""
    row = feedback_cls(conversation_id=conversation_id, turn=turn, rating=rating)
    db.add(row)
    db.flush()
    return row
