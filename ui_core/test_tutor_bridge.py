"""Standalone control-flow test for ui_core.tutor_bridge.TutorBridge.

Fully offline: monkeypatches the graph/model/system-prompt builders and the
upstream `tutor.run_tutor` calls with fakes that record the `messages` they
receive and return canned output. No real LLM/API/embedding calls are made.

Run with:
    python -m ui_core.test_tutor_bridge
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage

import ui_core.tutor_bridge as tb
from sandbox_ui.services.tutor_bridge import SandboxTutorBridge

_PASSED = 0
_FAILED = 0


def _check(name, cond, detail=""):
    """Record and print a PASS/FAIL for *name* based on *cond*."""
    global _PASSED, _FAILED
    if cond:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _text_of(content):
    """Pull the student-facing text out of a HumanMessage's content.

    Content is a plain string when there are no attachments, or a list of
    LangChain content blocks (``{"type": "text", ...}`` among them) when
    curriculum figures / uploaded images are attached (see
    ``utils.figures.build_multimodal_content``).
    """
    if isinstance(content, str):
        return content
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"]
    return None


class _Recorder:
    """Captures the `messages` list passed to each stubbed upstream call."""

    def __init__(self):
        """Initialize empty capture lists for the get and stream upstream calls."""
        self.get_calls: list[list] = []
        self.stream_calls: list[list] = []


def _install_stubs(module, recorder: _Recorder, canned_raw: str) -> dict:
    """Monkeypatch *module* (ui_core.tutor_bridge) in place; return originals."""
    originals = {
        name: getattr(module, name)
        for name in (
            "create_tutor_graph",
            "build_tutor_model",
            "load_system_prompt",
            "_upstream_get_tutor_reply",
            "_upstream_stream_tutor_reply",
        )
    }

    def fake_create_tutor_graph(system_prompt):
        """Return a sentinel graph tuple instead of compiling a real LangGraph."""
        return ("FAKE_GRAPH", system_prompt)

    def fake_build_tutor_model(provider="gpt"):
        """Return a sentinel model string instead of building a real chat model."""
        return "FAKE_MODEL"

    def fake_load_system_prompt(tutor, assignment_override=None):
        """Return a synthetic system prompt echoing *tutor* and *assignment_override*."""
        return f"SYSTEM[{tutor}]::{assignment_override}"

    def fake_upstream_get_tutor_reply(messages, graph=None):
        """Record *messages* and return the canned AIMessage plus its parsed answer."""
        recorder.get_calls.append(list(messages))
        out = [AIMessage(content=canned_raw)]
        _, answer = tb.parse_tutor_response(canned_raw)
        return out, (answer or "")

    def fake_upstream_stream_tutor_reply(messages, model=None, system_prompt=None):
        """Record *messages* and yield two text deltas then the canned ``__done__`` tuple."""
        recorder.stream_calls.append(list(messages))
        yield "Hello "
        yield "world"
        yield ("__done__", canned_raw)

    module.create_tutor_graph = fake_create_tutor_graph
    module.build_tutor_model = fake_build_tutor_model
    module.load_system_prompt = fake_load_system_prompt
    module._upstream_get_tutor_reply = fake_upstream_get_tutor_reply
    module._upstream_stream_tutor_reply = fake_upstream_stream_tutor_reply
    return originals


def _restore_stubs(module, originals: dict) -> None:
    """Restore each monkeypatched attribute on *module* from *originals*."""
    for name, value in originals.items():
        setattr(module, name, value)


def main() -> int:
    """Run the offline bridge control-flow checks and return an exit code (1 if any failed)."""
    canned_raw = json.dumps(
        {
            "pedagogical-reasoning": "because X",
            "Student-facing-answer": "Here is your answer.",
        }
    )

    recorder = _Recorder()
    originals = _install_stubs(tb, recorder, canned_raw)
    try:
        # ---------------------------------------------------------------
        # Base TutorBridge (main_ui's behavior)
        # ---------------------------------------------------------------
        bridge = tb.TutorBridge()
        history = [
            {"role": "student", "content": "Hi"},
            {"role": "tutor", "content": "Hello!"},
        ]
        result = bridge.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=history,
            new_student_message="What now?",
        )
        _check(
            "get_tutor_reply returns {reply, reasoning} parsed from canned AIMessage",
            result == {"reply": "Here is your answer.", "reasoning": "because X"},
            result,
        )

        messages = recorder.get_calls[-1]
        _check("history converted in order + new turn appended (3 total)", len(messages) == 3, len(messages))
        _check(
            "1st message: student turn -> HumanMessage('Hi')",
            isinstance(messages[0], HumanMessage) and messages[0].content == "Hi",
            messages[0],
        )
        _check(
            "2nd message: tutor turn -> AIMessage('Hello!')",
            isinstance(messages[1], AIMessage) and messages[1].content == "Hello!",
            messages[1],
        )
        _check("3rd message: new student turn appended last", isinstance(messages[2], HumanMessage))
        _check(
            "new student turn text is the plain message (no RAG block; base never retrieves)",
            _text_of(messages[2].content) == "What now?",
            messages[2].content,
        )

        # Streaming path
        events = list(
            bridge.stream_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=history,
                new_student_message="Stream please",
            )
        )
        _check(
            "stream yields deltas then exactly one terminal 'done' event",
            [e["type"] for e in events] == ["delta", "delta", "done"],
            events,
        )
        _check(
            "stream 'done' event carries the parsed reply+reasoning",
            events[-1] == {"type": "done", "reply": "Here is your answer.", "reasoning": "because X"},
            events[-1],
        )
        stream_messages = recorder.stream_calls[-1]
        _check(
            "stream: new student message appended last, unmodified text",
            _text_of(stream_messages[-1].content) == "Stream please",
            stream_messages[-1].content,
        )

        # ---------------------------------------------------------------
        # SandboxTutorBridge: RAG context prepended only in "rag" mode
        # ---------------------------------------------------------------
        sbx = SandboxTutorBridge()
        # Stub retrieved_context so no real RAG/embedding call happens.
        sbx.retrieved_context = (
            lambda course, query, **ctx: "RAG_BLOCK" if ctx.get("context_mode") == "rag" else ""
        )

        sbx.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=[],
            new_student_message="Explain X",
            context_mode="rag",
        )
        rag_text = _text_of(recorder.get_calls[-1][-1].content)
        _check(
            "sandbox rag mode: appended message begins with retrieved block + delimiter",
            isinstance(rag_text, str) and rag_text.startswith("RAG_BLOCK\n\n---\n\nStudent message:\n"),
            rag_text,
        )

        sbx.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=[],
            new_student_message="Explain X",
            context_mode="exercise_only",
        )
        non_rag_content = recorder.get_calls[-1][-1].content
        _check(
            "sandbox non-rag mode: no retrieved block prepended",
            _text_of(non_rag_content) == "Explain X",
            non_rag_content,
        )
    finally:
        _restore_stubs(tb, originals)

    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
