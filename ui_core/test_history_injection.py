from ui_core.services.conversation import _content_with_attachments


def test_appends_attachment_text():
    class Att:
        filename = "budget.csv"
        extracted_text = "a, b\n1, 2"
    out = _content_with_attachments("What does this show?", [Att()])
    assert out.startswith("What does this show?")
    assert "[Attachment: budget.csv]" in out
    assert "1, 2" in out


def test_no_attachments_returns_content_unchanged():
    assert _content_with_attachments("hi", []) == "hi"
