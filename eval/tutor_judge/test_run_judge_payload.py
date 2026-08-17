"""grade_transcript_payload: in-memory grading without file or network I/O."""
from eval.tutor_judge import run_judge


class _FakeGraph:
    def invoke(self, state):
        assert state["num_turns"] == 1          # exchanges were formatted
        assert "Physics" in state["conversation_text"]  # context flowed through
        return {
            "grade_json": {
                "sections": {}, "overview": "Solid Socratic guidance.",
                "total_base_score": 33, "max_base_score": 40,
                "total_score": 33, "max_score": 40,
            },
            "attempts": 1,
            "token_usage": {"input_tokens": 10, "output_tokens": 5, "cache_read": 0, "cache_write": 0},
            "judge_model": "claude-sonnet-4-6",
        }


def test_grade_transcript_payload_returns_ordered_grade(monkeypatch):
    monkeypatch.setattr(run_judge, "_create_model_invoke", lambda *a, **k: None)
    monkeypatch.setattr(run_judge, "_create_judge_graph", lambda **k: _FakeGraph())

    transcript = {
        "course": "",                       # disables figure discovery
        "context": "Physics III",
        "exercise": "Damped oscillator",
        "exchanges": [{"student": "where do I start?", "tutor": "what forces act on the mass?"}],
    }
    grade = run_judge.grade_transcript_payload(transcript, api_key="test-key")

    assert grade["total_score"] == 33
    assert grade["max_score"] == 40
    assert grade["overview"] == "Solid Socratic guidance."
    assert grade["model"] == {"provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0}
    assert "cost_estimate" in grade and "token_usage" in grade


def test_grade_transcript_payload_rejects_empty_exchanges(monkeypatch):
    monkeypatch.setattr(run_judge, "_create_model_invoke", lambda *a, **k: None)
    monkeypatch.setattr(run_judge, "_create_judge_graph", lambda **k: _FakeGraph())
    import pytest
    with pytest.raises(run_judge.JudgeError):
        run_judge.grade_transcript_payload({"course": "", "exchanges": []}, api_key="test-key")
