"""Database package for main_ui.

Public API: model classes, declarative `Base`, and session helpers.
"""

from main_ui.db.models import Base, Conversation, Message, Student, UploadedImage
from main_ui.db.session import SessionLocal, engine, get_session

__all__ = [
    "Base",
    "Conversation",
    "Message",
    "Student",
    "UploadedImage",
    "SessionLocal",
    "engine",
    "get_session",
]
