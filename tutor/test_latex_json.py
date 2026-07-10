r"""Regression tests: tutor replies with un-escaped LaTeX backslashes.

tutor_06 tells the model to write math as ``\(...\)`` and double the backslashes
so the JSON stays valid. The model is inconsistent — it sometimes emits a single
``\(``, which is an invalid JSON escape. Before the fix, ``parse_tutor_response``
failed and the raw JSON leaked to the student. These lock in graceful recovery.
"""

from tutor.run_tutor import parse_tutor_response, StudentAnswerExtractor

# Exactly the shape observed in the DB (single-backslash \( \) — invalid JSON).
BAD = (
    '{"pedagogical-reasoning":"reasoning here",'
    '"Student-facing-answer":"If \\(i\\) indexes suppliers, what does \\(j\\) index? '
    'Try \\(\\frac{a}{b}\\) too."}'
)
# NOTE: in this Python source, "\\(" is a single backslash + "(" at runtime,
# i.e. the invalid-JSON form the model actually emits.


def test_parse_recovers_answer_from_single_backslash_latex():
    reasoning, answer = parse_tutor_response(BAD)
    assert answer is not None, "answer should be recovered, not None"
    assert "raw" not in (answer or "")
    # LaTeX must survive for KaTeX: single-backslash \( ... \) in the output.
    assert "\\(i\\)" in answer
    assert "\\frac{a}{b}" in answer
    assert reasoning == "reasoning here"


def test_parse_still_handles_valid_doubled_json():
    good = '{"pedagogical-reasoning":"r","Student-facing-answer":"ok \\\\(x\\\\)"}'
    # good has properly doubled backslashes -> valid JSON -> answer "ok \(x\)"
    _, answer = parse_tutor_response(good)
    assert answer == "ok \\(x\\)"


def test_stream_extractor_preserves_latex_backslash():
    ex = StudentAnswerExtractor()
    visible = ex.feed(BAD)
    # the streamed visible answer keeps the LaTeX delimiters
    assert "\\(i\\)" in visible
