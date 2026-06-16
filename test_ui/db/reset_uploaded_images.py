"""One-off maintenance: rebuild the `uploaded_images` table from the current model.

The Sandbox builds its schema with ``Base.metadata.create_all``, which creates
*missing tables* but never ALTERs an existing one. When the ``UploadedImage``
model gained the ``data`` column (image bytes), any pre-existing Sandbox DB kept
the old table, so image inserts crash with "column data does not exist" /
"no such column: data".

This drops and recreates ONLY ``uploaded_images`` (it holds nothing but uploaded
images — no conversations/messages/history are touched) against the **same DB the
app uses**, resolved via the normal ``TEST_UI_DATABASE_URL`` -> ``DATABASE_URL``
-> SQLite order. Run it in the same shell/env you start the server in:

    python -m test_ui.db.reset_uploaded_images
"""

from __future__ import annotations

from test_ui.db.models import UploadedImage
from test_ui.db.session import engine


def main() -> None:
    print(f"Target DB: {engine.url}")
    UploadedImage.__table__.drop(engine, checkfirst=True)
    UploadedImage.__table__.create(engine)
    print("Rebuilt 'uploaded_images' with the current schema (incl. the 'data' column).")
    print("Restart the Sandbox: python -m test_ui")


if __name__ == "__main__":
    main()
