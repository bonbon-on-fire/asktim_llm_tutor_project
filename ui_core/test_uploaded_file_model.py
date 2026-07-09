from sandbox_ui.db.models import UploadedFile


def test_columns_present():
    cols = {c.name for c in UploadedFile.__table__.columns}
    assert {"id", "message_id", "filename", "kind", "extracted_text",
            "size_bytes", "data", "created_at"} <= cols
    assert UploadedFile.__tablename__ == "uploaded_files"
