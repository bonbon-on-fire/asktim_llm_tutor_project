"""
Web UI — Flask app for the Humanities LLM Tutor.

Same pipeline as the terminal UI but browser-based:
  - Configure tutor prompt, student persona, course, exercise
  - Chat with the tutor directly or let a student bot generate messages
  - Debug mode shows pedagogical reasoning
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from langchain_core.messages import AIMessage, HumanMessage

from students.run_student import get_next_student_message, list_personas
from tutor.run_tutor import create_tutor_graph, load_system_prompt, parse_tutor_response

# ---------------------------------------------------------------------------
# Paths & discovery
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_PERSONAS_DIR = _REPO_ROOT / "students" / "personas"

_PERSONA_TYPES: tuple[str, ...] = ("chaotic", "chitchat", "clueless")


def _discover_tutor_versions() -> list[str]:
    if not _TUTOR_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def _discover_courses() -> list[str]:
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(d.name for d in _CURRICULUM_DIR.iterdir() if d.is_dir())


def _discover_exercises(course: str) -> list[str]:
    course_dir = _CURRICULUM_DIR / course
    if not course_dir.exists():
        return []
    numbers: list[str] = []
    for p in sorted(course_dir.glob("exercise_*.txt")):
        m = re.match(r"^exercise_(\d{2})\.txt$", p.name)
        if m:
            numbers.append(m.group(1))
    return numbers


def _discover_persona_versions(persona_type: str) -> list[str]:
    versions: list[str] = []
    for p in sorted(_PERSONAS_DIR.glob(f"{persona_type}_*.txt")):
        m = re.match(rf"^{re.escape(persona_type)}_(\d{{2}})\.txt$", p.name)
        if m:
            versions.append(m.group(1))
    return versions


def _load_assignment_text(course: str, exercise_num: str, turn_size: int | None = None) -> str:
    """Load combined assignment context: course.txt + exercise_XX.txt (+ optional turn size)."""
    course_dir = _CURRICULUM_DIR / course
    course_path = course_dir / "course.txt"
    exercise_path = course_dir / f"exercise_{exercise_num}.txt"

    course_text = course_path.read_text(encoding="utf-8").strip()
    exercise_text = exercise_path.read_text(encoding="utf-8").strip()
    assignment_text = (
        "Course context:\n"
        f"{course_text}\n\n"
        "Exercise:\n"
        f"{exercise_text}"
    )
    if isinstance(turn_size, int) and turn_size > 0:
        assignment_text += (
            "\n\nRun configuration:\n"
            f"- Planned conversation length: {turn_size} student+tutor exchanges."
        )
    return assignment_text


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

# In-memory session store: sid -> session data
_sessions: dict[str, dict] = {}


def _get_session_data() -> dict:
    sid = session.get("sid")
    if not sid or sid not in _sessions:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        _sessions[sid] = {
            "conv": [],
            "tutor_graph": None,
            "config": None,
        }
    return _sessions[sid]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_tutor_msgs(conv: list) -> list:
    result = []
    for m in conv:
        if m["role"] == "student":
            result.append(HumanMessage(content=m["content"]))
        else:
            tutor_content = m.get("raw_content") or m["content"]
            result.append(AIMessage(content=tutor_content))
    return result


def _to_student_msgs(conv: list) -> list:
    result = []
    for m in conv:
        if m["role"] == "tutor":
            result.append(HumanMessage(content=m["content"]))
        else:
            result.append(AIMessage(content=m["content"]))
    return result


def _invoke_tutor(sess: dict, messages: list) -> tuple[str, str, str | None]:
    """Invoke tutor graph. Returns (tutor_text, raw_content, reasoning)."""
    result = sess["tutor_graph"].invoke({"messages": messages})
    out_messages = result["messages"]
    last = out_messages[-1] if out_messages else None

    if isinstance(last, AIMessage):
        raw_content = last.content if isinstance(last.content, str) else str(last.content)
        reasoning, student_facing = parse_tutor_response(raw_content)
        tutor_text = student_facing if student_facing is not None else raw_content
    else:
        tutor_text = ""
        raw_content = ""
        reasoning = None

    return tutor_text, raw_content, reasoning


# ---------------------------------------------------------------------------
# Routes — config
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config-options", methods=["GET"])
def config_options():
    """Return all available configuration options for the UI dropdowns."""
    tutor_versions = _discover_tutor_versions()
    courses = _discover_courses()

    course_exercises: dict[str, list[str]] = {}
    for c in courses:
        course_exercises[c] = _discover_exercises(c)

    persona_versions: dict[str, list[str]] = {}
    for pt in _PERSONA_TYPES:
        persona_versions[pt] = _discover_persona_versions(pt)

    return jsonify({
        "tutor_versions": tutor_versions,
        "persona_types": list(_PERSONA_TYPES),
        "persona_versions": persona_versions,
        "courses": courses,
        "course_exercises": course_exercises,
    })


# ---------------------------------------------------------------------------
# Routes — conversation
# ---------------------------------------------------------------------------

@app.route("/api/start", methods=["POST"])
def start():
    """Start a new conversation with the given config."""
    data = request.get_json(silent=True) or {}
    tutor_version = data.get("tutor_version", "tutor_01")
    persona_type = data.get("persona_type", "chaotic")
    persona_version = data.get("persona_version", "01")
    course = data.get("course", "")
    exercise_num = data.get("exercise_num", "01")
    turn_size_raw = data.get("turn_size")
    debug = data.get("debug", False)

    if not course:
        return jsonify({"error": "Course is required."}), 400

    turn_size: int | None = None
    if turn_size_raw is not None:
        try:
            parsed_turn_size = int(turn_size_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "turn_size must be a positive integer."}), 400
        if parsed_turn_size <= 0:
            return jsonify({"error": "turn_size must be a positive integer."}), 400
        turn_size = parsed_turn_size

    try:
        assignment_text = _load_assignment_text(course, exercise_num, turn_size)
    except FileNotFoundError:
        return jsonify(
            {"error": f"Missing curriculum file for {course}: course.txt or exercise_{exercise_num}.txt"}
        ), 400

    system_prompt = load_system_prompt(tutor_version, assignment_override=assignment_text)
    tutor_graph = create_tutor_graph(system_prompt)

    sess = _get_session_data()
    sess["conv"] = []
    sess["tutor_graph"] = tutor_graph
    sess["config"] = {
        "tutor_version": tutor_version,
        "persona_type": persona_type,
        "persona_version": persona_version,
        "prompt_name": f"{persona_type}_{persona_version}",
        "course": course,
        "exercise_num": exercise_num,
        "turn_size": turn_size,
        "assignment_text": assignment_text,
    }

    seed = [HumanMessage(content="Hello, I'd like to get started on my assignment.")]
    tutor_text, raw_content, reasoning = _invoke_tutor(sess, seed)

    sess["conv"].append({
        "role": "tutor", "content": tutor_text,
        "raw_content": raw_content, "reasoning": reasoning,
    })

    response = {"tutor": tutor_text}
    if debug and reasoning:
        response["reasoning"] = reasoning
    return jsonify(response)


@app.route("/api/chat", methods=["POST"])
def chat():
    """Receive a user-typed message, forward to tutor, return reply."""
    data = request.get_json(silent=True) or {}
    user_msg = data.get("message", "").strip()
    debug = data.get("debug", False)
    if not user_msg:
        return jsonify({"error": "Empty message."}), 400

    sess = _get_session_data()
    if sess["tutor_graph"] is None:
        return jsonify({"error": "No active conversation. Start one first."}), 400

    sess["conv"].append({"role": "student", "content": user_msg})
    tutor_msgs = _to_tutor_msgs(sess["conv"])
    tutor_text, raw_content, reasoning = _invoke_tutor(sess, tutor_msgs)

    sess["conv"].append({
        "role": "tutor", "content": tutor_text,
        "raw_content": raw_content, "reasoning": reasoning,
    })

    response = {"student": user_msg, "tutor": tutor_text}
    if debug and reasoning:
        response["reasoning"] = reasoning
    return jsonify(response)


@app.route("/api/student-turn", methods=["POST"])
def student_turn():
    """Generate a student-bot message then get the tutor's reply."""
    data = request.get_json(silent=True) or {}
    debug = data.get("debug", False)

    sess = _get_session_data()
    if sess["tutor_graph"] is None or sess["config"] is None:
        return jsonify({"error": "No active conversation. Start one first."}), 400

    conv = sess["conv"]
    if not conv or conv[-1]["role"] != "tutor":
        return jsonify({"error": "A tutor message must be the last in the conversation."}), 400

    cfg = sess["config"]
    student_msgs = _to_student_msgs(conv)
    bot_msg = get_next_student_message(
        student_msgs,
        prompt_name=cfg["prompt_name"],
        assignment=cfg["assignment_text"],
        turn_size=cfg.get("turn_size"),
    )
    student_text = bot_msg.content if isinstance(bot_msg.content, str) else str(bot_msg.content)
    conv.append({"role": "student", "content": student_text})

    tutor_msgs = _to_tutor_msgs(conv)
    tutor_text, raw_content, reasoning = _invoke_tutor(sess, tutor_msgs)
    conv.append({
        "role": "tutor", "content": tutor_text,
        "raw_content": raw_content, "reasoning": reasoning,
    })

    response = {"student": student_text, "tutor": tutor_text}
    if debug and reasoning:
        response["reasoning"] = reasoning
    return jsonify(response)


@app.route("/api/reasoning", methods=["GET"])
def get_reasoning():
    """Get reasoning for all tutor messages in the conversation."""
    sess = _get_session_data()
    reasoning_list = []
    for msg in sess["conv"]:
        if msg["role"] == "tutor":
            reasoning = msg.get("reasoning")
            if not reasoning and msg.get("raw_content"):
                reasoning, _ = parse_tutor_response(msg["raw_content"])
            reasoning_list.append(reasoning)
        else:
            reasoning_list.append(None)
    return jsonify({"reasoning": reasoning_list})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
