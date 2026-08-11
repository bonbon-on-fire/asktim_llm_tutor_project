"""One-off: create/rebuild the `uploaded_files` table for an existing Sandbox DB.

Sandbox builds its schema with ``create_all`` (creates missing tables, never
ALTERs). A DB created before ``UploadedFile`` existed has no ``uploaded_files``
table, so file inserts crash. This creates it (or rebuilds it) against the same
DB the app uses.

    python -m sandbox_ui.db.reset_uploaded_files
"""

from __future__ import annotations

from sandbox_ui.db.models import UploadedFile
from sandbox_ui.db.session import engine


def main() -> None:
    """Drop and rebuild the `uploaded_files` table on the Sandbox's DB."""
    print(f"Target DB: {engine.url}")
    UploadedFile.__table__.drop(engine, checkfirst=True)
    UploadedFile.__table__.create(engine)
    print("Rebuilt 'uploaded_files' with the current schema.")
    print("Restart the Sandbox: python -m sandbox_ui")


if __name__ == "__main__":
    main()
