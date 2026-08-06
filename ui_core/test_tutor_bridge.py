"""Standalone control-flow test for ui_core.tutor_bridge.TutorBridge.

Fully offline: monkeypatches the graph/model/system-prompt builders and the
upstream `tutor.run_tutor` calls with fakes that record the `messages` they
receive and return canned output. No real LLM/API/embedding calls are made.

Run with:
    python -m ui_core.test_tutor_bridge
"""

from __future__ import annotations

import json
import os

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


def _test_mode_resolution():
    """Unit-test the lifted mode resolver and week helper (no I/O)."""
    from ui_core.tutor_bridge import _resolve_context_mode, _week_for_exercise

    prev = os.environ.pop("TUTOR_CONTEXT_MODE", None)
    try:
        _check(
            "default is rag when course present and no custom",
            _resolve_context_mode("some_course", has_custom=False) == "rag",
        )
        _check(
            "no course -> full_context",
            _resolve_context_mode("", has_custom=False) == "full_context",
        )
        _check(
            "has_custom degrades rag -> full_context",
            _resolve_context_mode("some_course", has_custom=True) == "full_context",
        )
        _check(
            "explicit exercise_only wins",
            _resolve_context_mode("some_course", has_custom=False, requested="exercise_only")
            == "exercise_only",
        )
        os.environ["TUTOR_CONTEXT_MODE"] = "full_context"
        _check(
            "env override applies when no explicit request",
            _resolve_context_mode("some_course", has_custom=False) == "full_context",
        )
        _check(
            "explicit request beats env",
            _resolve_context_mode("some_course", has_custom=False, requested="rag") == "rag",
        )
    finally:
        os.environ.pop("TUTOR_CONTEXT_MODE", None)
        if prev is not None:
            os.environ["TUTOR_CONTEXT_MODE"] = prev

    # No due-session line on disk -> exercise number is the week.
    _check("numeric exercise -> week int", _week_for_exercise("no_such_course", "4") == 4)
    _check("non-numeric exercise -> None", _week_for_exercise("no_such_course", "custom") is None)
    _check("None exercise -> None", _week_for_exercise("no_such_course", None) is None)
    # A course whose exercise files declare "Due ... Session N" uses that session,
    # not the exercise number (its memos/papers are numbered independently of week).
    _check(
        "declared due session overrides exercise number",
        _week_for_exercise("economic_development_planning", "1") == 7,
    )
    _check(
        "final project due session parsed",
        _week_for_exercise("economic_development_planning", "4") == 23,
    )
    # Non-numeric exercise stays unscoped even for a due-session course.
    _check(
        "non-numeric exercise -> None (due-session course)",
        _week_for_exercise("economic_development_planning", "custom") is None,
    )


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
        # Per-call retrieved_context (RAG grounding) passed alongside the messages.
        self.get_rag: list[str] = []
        self.stream_rag: list[str] = []


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

    def fake_create_tutor_graph(system_prompt, *, provider="gpt", figures=None):
        """Return a sentinel graph tuple instead of compiling a real LangGraph.

        Accepts ``provider``/``figures`` to match the real ``create_tutor_graph``
        signature — the bridge now passes ``provider=`` per conversation.
        """
        return ("FAKE_GRAPH", system_prompt)

    def fake_build_tutor_model(provider="gpt"):
        """Return a sentinel model string instead of building a real chat model."""
        return "FAKE_MODEL"

    def fake_load_system_prompt(tutor, assignment_override=None, prompts_dir=None):
        """Return a synthetic system prompt echoing *tutor* and *assignment_override*."""
        return f"SYSTEM[{tutor}]::{assignment_override}"

    def fake_upstream_get_tutor_reply(messages, graph=None, retrieved_context=""):
        """Record *messages* + *retrieved_context* and return the canned reply."""
        recorder.get_calls.append(list(messages))
        recorder.get_rag.append(retrieved_context)
        out = [AIMessage(content=canned_raw)]
        _, answer = tb.parse_tutor_response(canned_raw)
        return out, (answer or "")

    def fake_upstream_stream_tutor_reply(
        messages, model=None, system_prompt=None, retrieved_context=""
    ):
        """Record *messages* + *retrieved_context*, then yield deltas + ``__done__``."""
        recorder.stream_calls.append(list(messages))
        recorder.stream_rag.append(retrieved_context)
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


def _test_build_system_prompt_course_rules():
    """build_system_prompt appends curriculum/<course>/tutor_rules.txt when present.

    Runs against the real (unstubbed) load_system_prompt + curriculum files, so it
    also proves `course` is threaded through to build_system_prompt.
    """
    from utils.curriculum import TUTOR_RULES_HEADER

    bridge = tb.TutorBridge()
    # supply_chain_design ships a tutor_rules.txt -> header appended.
    with_rules = bridge.build_system_prompt("tutor_07", "ASSIGN", course="supply_chain_design")
    _check(
        "course with tutor_rules.txt: rules appended",
        TUTOR_RULES_HEADER in with_rules,
    )
    # A course with no such file -> base prompt unchanged.
    none = bridge.build_system_prompt("tutor_07", "ASSIGN", course="___no_such_course___")
    _check(
        "course without tutor_rules.txt: base unchanged",
        TUTOR_RULES_HEADER not in none,
    )


def main() -> int:
    """Run the offline bridge control-flow checks and return an exit code (1 if any failed)."""
    _test_mode_resolution()
    _test_build_system_prompt_course_rules()

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
        # Base TutorBridge (main_ui's behavior): now defaults to rag and
        # retrieves per turn. Stub retrieved_context so no real embedding runs.
        # ---------------------------------------------------------------
        bridge = tb.TutorBridge()
        bridge.retrieved_context = (
            lambda course, query, **ctx: tb.RetrievedContext(
                text="RAG_BLOCK", records=[{"source": "local:course", "score": 1.0, "chars": 3, "text": "abc"}]
            )
            if ctx.get("context_mode") == "rag"
            else tb.RetrievedContext()
        )
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
            "base rag mode: reply parsed; retrieved records surfaced",
            result["reply"] == "Here is your answer."
            and result["reasoning"] == "because X"
            and result["retrieved"]
            and result["retrieved"][0]["source"] == "local:course",
            result,
        )
        messages = recorder.get_calls[-1]
        _check("history in order + new turn appended (3 total)", len(messages) == 3, len(messages))
        _check(
            "new student turn is the plain message (RAG never on a user turn)",
            _text_of(messages[2].content) == "What now?",
            messages[2].content,
        )
        _check(
            "base rag mode: retrieved block routed to the system channel",
            "RAG_BLOCK" in recorder.get_rag[-1],
            recorder.get_rag[-1],
        )

        # Fail closed: rag mode with empty retrieval must raise BEFORE any model call.
        bridge.retrieved_context = lambda course, query, **ctx: tb.RetrievedContext()
        before_get = len(recorder.get_calls)
        raised = False
        try:
            bridge.get_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=[],
                new_student_message="What now?",
            )
        except tb.RagUnavailableError:
            raised = True
        _check("rag + empty retrieval raises RagUnavailableError (non-streaming)", raised)
        _check(
            "no upstream model call was made on refusal (non-streaming)",
            len(recorder.get_calls) == before_get,
            (before_get, len(recorder.get_calls)),
        )

        before_stream = len(recorder.stream_calls)
        raised_stream = False
        try:
            list(
                bridge.stream_tutor_reply(
                    course="cities_and_climate_change",
                    exercise="04",
                    tutor="tutor_05",
                    history=[],
                    new_student_message="What now?",
                )
            )
        except tb.RagUnavailableError:
            raised_stream = True
        _check("rag + empty retrieval raises RagUnavailableError (streaming)", raised_stream)
        _check(
            "no upstream model call was made on refusal (streaming)",
            len(recorder.stream_calls) == before_stream,
            (before_stream, len(recorder.stream_calls)),
        )

        # Non-rag mode with empty retrieval must NOT raise.
        ok_mode = True
        try:
            bridge.get_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=[],
                new_student_message="What now?",
                context_mode="exercise_only",
            )
        except tb.RagUnavailableError:
            ok_mode = False
        _check("exercise_only mode with empty retrieval does NOT raise", ok_mode)

        # ---------------------------------------------------------------
        # SandboxTutorBridge: in "rag" mode the retrieved context is routed to
        # the SYSTEM channel (retrieved_context arg), never onto a user turn.
        # ---------------------------------------------------------------
        sbx = SandboxTutorBridge()
        # Stub retrieved_context so no real RAG/embedding call happens.
        sbx.retrieved_context = (
            lambda course, query, **ctx: tb.RetrievedContext(
                text="RAG_BLOCK", records=[{"source": "local:course", "score": 1.0, "chars": 3, "text": "abc"}]
            )
            if ctx.get("context_mode") == "rag"
            else tb.RetrievedContext()
        )

        sbx.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=[],
            new_student_message="Explain X",
            context_mode="rag",
        )
        rag_messages = recorder.get_calls[-1]
        rag_ctx = recorder.get_rag[-1]
        _check(
            "sandbox rag mode: single clean student message (RAG not on a user turn)",
            len(rag_messages) == 1 and _text_of(rag_messages[-1].content) == "Explain X",
            rag_messages,
        )
        _check(
            "sandbox rag mode: retrieved context routed to the system channel",
            isinstance(rag_ctx, str) and "RAG_BLOCK" in rag_ctx,
            rag_ctx,
        )

        # Streaming path mirrors the same routing.
        list(
            sbx.stream_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=[],
                new_student_message="Explain X",
                context_mode="rag",
            )
        )
        rag_stream_messages = recorder.stream_calls[-1]
        rag_stream_ctx = recorder.stream_rag[-1]
        _check(
            "sandbox rag stream: clean student turn + RAG in the system channel",
            len(rag_stream_messages) == 1
            and _text_of(rag_stream_messages[-1].content) == "Explain X"
            and "RAG_BLOCK" in rag_stream_ctx,
            (rag_stream_messages, rag_stream_ctx),
        )

        sbx.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=[],
            new_student_message="Explain X",
            context_mode="exercise_only",
        )
        non_rag_messages = recorder.get_calls[-1]
        non_rag_ctx = recorder.get_rag[-1]
        _check(
            "sandbox non-rag mode: single clean student message, no retrieved context",
            len(non_rag_messages) == 1
            and _text_of(non_rag_messages[-1].content) == "Explain X"
            and not non_rag_ctx,
            (non_rag_messages, non_rag_ctx),
        )
    finally:
        _restore_stubs(tb, originals)

    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
