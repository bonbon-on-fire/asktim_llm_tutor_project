"""Bridge from main_ui to the existing tutor.run_tutor pipeline.

The one place in `main_ui` that talks to `tutor.run_tutor`. Routes call
`get_tutor_reply(...)` here; they never import the upstream tutor API
directly. If the underlying tutor API changes shape later, only this module
needs updating.

No HTTP, no DB, no Flask state — just a thin function from
``(course, exercise, tutor, history, new_student_message)`` to a tutor reply.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from tutor.run_tutor import (
    build_tutor_model,
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
)
from tutor.run_tutor import get_tutor_reply as _upstream_get_tutor_reply
from tutor.run_tutor import stream_tutor_reply as _upstream_stream_tutor_reply


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_ABOUT_ASKTIM_PATH = Path(__file__).resolve().parents[1] / "about_asktim.txt"


_graph_cache: dict[tuple[str, str, str], object] = {}
# Parallel cache for the streaming path. The non-streaming path drives a
# compiled LangGraph; the streaming path drives the raw model with the same
# system prompt. We cache both per (tutor, course, exercise) so successive
# turns reuse the same prompt build.
_stream_cache: dict[tuple[str, str, str], tuple[object, str]] = {}


def build_assignment_text(course: str, exercise: str) -> str:
    """Concatenate about_asktim.txt + course.txt + optional syllabus.txt + exercise_<NN>.txt.

    Mirrors `ui/run_ui_raw.py:_build_assignment_text` but omits the
    `Run configuration` block — main_ui chats are open-ended, no planned
    turn count. The leading block describes the AskTIM deployment so the
    tutor can coherently answer "what are you?" / "where am I?" questions;
    it lives at `main_ui/about_asktim.txt` and is only read here so
    `tutor/`, `test_ui/`, and the bulk-transcript runners stay unaware of it.
    """
    course_dir = _CURRICULUM_DIR / course
    exercise_path = course_dir / f"exercise_{exercise}.txt"
    exercise_text = exercise_path.read_text(encoding="utf-8").strip()

    parts: list[str] = []

    if _ABOUT_ASKTIM_PATH.is_file():
        about_text = _ABOUT_ASKTIM_PATH.read_text(encoding="utf-8").strip()
        if about_text:
            parts.append("About yourself:\n" + about_text)

    course_path = course_dir / "course.txt"
    if course_path.is_file():
        parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())

    syllabus_path = course_dir / "syllabus.txt"
    if syllabus_path.is_file():
        parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())

    parts.append("Exercise:\n" + exercise_text)
    return "\n\n".join(parts)


def _get_or_build_graph(tutor: str, course: str, exercise: str):
    key = (tutor, course, exercise)
    cached = _graph_cache.get(key)
    if cached is not None:
        return cached
    assignment_text = build_assignment_text(course, exercise)
    system_prompt = load_system_prompt(tutor, assignment_override=assignment_text)
    graph = create_tutor_graph(system_prompt)
    _graph_cache[key] = graph
    return graph


def _get_or_build_stream_context(
    tutor: str, course: str, exercise: str
) -> tuple[object, str]:
    """Return ``(model, system_prompt)`` for the streaming path."""
    key = (tutor, course, exercise)
    cached = _stream_cache.get(key)
    if cached is not None:
        return cached
    assignment_text = build_assignment_text(course, exercise)
    system_prompt = load_system_prompt(tutor, assignment_override=assignment_text)
    model = build_tutor_model()
    _stream_cache[key] = (model, system_prompt)
    return model, system_prompt


def _history_to_langchain(history: list[dict]) -> list:
    """Convert [{role, content}, ...] dicts to LangChain BaseMessage instances."""
    messages: list = []
    for entry in history:
        role = entry["role"]
        content = entry["content"]
        if role == "student":
            messages.append(HumanMessage(content=content))
        elif role == "tutor":
            messages.append(AIMessage(content=content))
        else:
            raise ValueError(f"Unknown role: {role!r} (expected 'student' or 'tutor')")
    return messages


def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: zero-padded 2-digit exercise number (e.g. ``"04"``)
        tutor: tutor prompt stem (e.g. ``"tutor_05"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to

    Returns:
        ``{"reply": str, "reasoning": str | None}`` — reasoning is the
        tutor's hidden ``pedagogical-reasoning`` field; ``None`` if parsing
        the tutor's JSON failed.
    """
    graph = _get_or_build_graph(tutor, course, exercise)
    messages = _history_to_langchain(history)
    messages.append(HumanMessage(content=new_student_message))

    out_messages, reply_text = _upstream_get_tutor_reply(messages, graph=graph)

    reasoning: str | None = None
    if out_messages:
        last = out_messages[-1]
        if isinstance(last, AIMessage):
            raw = last.content if isinstance(last.content, str) else str(last.content)
            reasoning, _ = parse_tutor_response(raw)

    return {"reply": reply_text, "reasoning": reasoning}


def stream_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    Routes are responsible for re-shaping these into SSE frames.
    """
    model, system_prompt = _get_or_build_stream_context(tutor, course, exercise)
    messages = _history_to_langchain(history)
    messages.append(HumanMessage(content=new_student_message))

    full_raw: str | None = None
    for item in _upstream_stream_tutor_reply(
        messages, model=model, system_prompt=system_prompt
    ):
        if isinstance(item, tuple) and item and item[0] == "__done__":
            full_raw = item[1]
            break
        if isinstance(item, str) and item:
            yield {"type": "delta", "text": item}

    reasoning: str | None = None
    reply_text = ""
    if full_raw:
        reasoning, answer = parse_tutor_response(full_raw)
        reply_text = answer or ""
    yield {"type": "done", "reply": reply_text, "reasoning": reasoning}
