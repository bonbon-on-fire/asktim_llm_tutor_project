"""
Web UI — Flask app for the Humanities LLM Tutor.

Same tutor pipeline as the terminal UI but browser-based:
  - 3-step wizard to pick tutor prompt, course, and exercise
  - Chat directly with the tutor as a human student
  - Debug mode shows pedagogical reasoning
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from langchain_core.messages import AIMessage, HumanMessage

from tutor.run_tutor import create_tutor_graph, load_system_prompt, parse_tutor_response

# ---------------------------------------------------------------------------
# Paths & discovery
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"


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


def _load_assignment_text(course: str, exercise_num: str) -> str:
    """Load combined assignment context: course.txt + syllabus.txt (optional) + exercise_XX.txt."""
    course_dir = _CURRICULUM_DIR / course
    exercise_path = course_dir / f"exercise_{exercise_num}.txt"
    exercise_text = exercise_path.read_text(encoding="utf-8").strip()

    parts: list[str] = []

    course_path = course_dir / "course.txt"
    if course_path.exists():
        parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())

    syllabus_path = course_dir / "syllabus.txt"
    if syllabus_path.exists():
        parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())

    parts.append("Exercise:\n" + exercise_text)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True
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
    """Return available tutor versions, courses, exercises, and their text content."""
    tutor_versions = _discover_tutor_versions()
    courses = _discover_courses()
    course_exercises = {c: _discover_exercises(c) for c in courses}

    tutor_texts: dict[str, str] = {}
    for v in tutor_versions:
        p = _TUTOR_PROMPTS_DIR / f"{v}.txt"
        if p.exists():
            tutor_texts[v] = p.read_text(encoding="utf-8").strip()

    course_texts: dict[str, str] = {}
    for c in courses:
        sections: list[str] = []
        p = _CURRICULUM_DIR / c / "course.txt"
        if p.exists():
            sections.append(p.read_text(encoding="utf-8").strip())
        s = _CURRICULUM_DIR / c / "syllabus.txt"
        if s.exists():
            sections.append("--- Syllabus ---\n" + s.read_text(encoding="utf-8").strip())
        if sections:
            course_texts[c] = "\n\n".join(sections)

    exercise_texts: dict[str, dict[str, str]] = {}
    for c in courses:
        exercise_texts[c] = {}
        for num in course_exercises.get(c, []):
            p = _CURRICULUM_DIR / c / f"exercise_{num}.txt"
            if p.exists():
                exercise_texts[c][num] = p.read_text(encoding="utf-8").strip()

    return jsonify({
        "tutor_versions": tutor_versions,
        "tutor_texts": tutor_texts,
        "courses": courses,
        "course_texts": course_texts,
        "course_exercises": course_exercises,
        "exercise_texts": exercise_texts,
    })


# ---------------------------------------------------------------------------
# Routes — conversation
# ---------------------------------------------------------------------------

@app.route("/api/start", methods=["POST"])
def start():
    """Start a new conversation with the given tutor, course, and exercise."""
    data = request.get_json(silent=True) or {}
    tutor_version = data.get("tutor_version", "tutor_01")
    course = data.get("course", "")
    exercise_num = data.get("exercise_num", "01")
    debug = data.get("debug", False)

    if not course:
        return jsonify({"error": "Course is required."}), 400

    try:
        assignment_text = _load_assignment_text(course, exercise_num)
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
        "course": course,
        "exercise_num": exercise_num,
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

    response = {"tutor": tutor_text}
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
