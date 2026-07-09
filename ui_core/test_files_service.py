from ui_core.services import files as F


def test_read_and_validate_skips_empty(monkeypatch):
    class FS:
        def __init__(self, name, data):
            self.filename = name
            self._data = data
        def read(self):
            return self._data
    out = F.read_and_validate([FS("", b""), FS("t.csv", b"a,b\n1,2\n")])
    assert len(out) == 1 and out[0].kind == "csv"


def test_files_to_text_labels():
    from utils.attachments import validate_files
    atts = validate_files([("t.csv", b"a,b\n1,2\n")])
    assert "[Attachment: t.csv]" in F.files_to_text(atts)
