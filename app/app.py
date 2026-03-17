"""
Transcript viewer — Flask app to navigate and read tutor transcripts with grades.
"""
import os
import json
from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory

app = Flask(__name__, static_folder="static", template_folder="templates")

# Transcripts directory: try env, then repo root, then cwd
BASE_DIR = Path(__file__).resolve().parent.parent
if os.environ.get("TRANSCRIPTS_DIR"):
    TRANSCRIPTS_DIR = Path(os.environ["TRANSCRIPTS_DIR"]).resolve()
else:
    _candidates = [
        BASE_DIR / "transcripts",
        Path.cwd() / "transcripts",
        Path.cwd().parent / "transcripts",
    ]
    TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
    for p in _candidates:
        if p.is_dir() and (p / "chaotic").is_dir():
            TRANSCRIPTS_DIR = p
            break

# Persona bases (folders without _claude)
PERSONA_BASES = ["chaotic", "chitchat", "clueless"]


def _load_json(path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _grade_summary(data):
    if not data or "grade" not in data:
        return None
    g = data["grade"]
    return {
        "total_score": g.get("total_score"),
        "max_score": g.get("max_score"),
        "total_base_score": g.get("total_base_score"),
        "max_base_score": g.get("max_base_score"),
        "total_bonus": g.get("total_bonus", 0),
        "max_bonus": g.get("max_bonus", 0),
        "model": g.get("model"),
        "overview": g.get("overview", []),
        "sections": g.get("sections"),
    }


def list_transcripts():
    """List all transcripts with GPT and Claude grades."""
    out = []
    for persona in PERSONA_BASES:
        base_path = TRANSCRIPTS_DIR / persona
        if not base_path.is_dir():
            continue
        for f in sorted(base_path.glob("transcript_*.json")):
            num = f.stem.replace("transcript_", "")
            gpt_path = TRANSCRIPTS_DIR / persona / f"transcript_{num}.json"
            claude_path = TRANSCRIPTS_DIR / f"{persona}_claude" / f"transcript_{num}.json"
            gpt_data = _load_json(gpt_path)
            claude_data = _load_json(claude_path)
            gpt_grade = _grade_summary(gpt_data) if gpt_data else None
            claude_grade = _grade_summary(claude_data) if claude_data else None
            meta = (gpt_data or claude_data or {}).copy()
            meta.pop("exchanges", None)
            meta.pop("grade", None)
            out.append({
                "persona": persona,
                "number": num,
                "metadata": meta,
                "gpt_grade": gpt_grade,
                "claude_grade": claude_grade,
                "gpt_score": gpt_grade["total_score"] if gpt_grade else None,
                "gpt_max": gpt_grade["max_score"] if gpt_grade else None,
                "claude_score": claude_grade["total_score"] if claude_grade else None,
                "claude_max": claude_grade["max_score"] if claude_grade else None,
            })
    return out


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/transcripts")
def api_list_transcripts():
    data = list_transcripts()
    return jsonify(data)


@app.route("/api/transcripts/<persona>/<num>")
def api_get_transcript(persona, num):
    if persona not in PERSONA_BASES:
        return jsonify({"error": "Unknown persona"}), 404
    gpt_path = TRANSCRIPTS_DIR / persona / f"transcript_{num}.json"
    claude_path = TRANSCRIPTS_DIR / f"{persona}_claude" / f"transcript_{num}.json"
    gpt_data = _load_json(gpt_path)
    if not gpt_data:
        return jsonify({"error": "Transcript not found"}), 404
    claude_data = _load_json(claude_path)
    grade_gpt = _grade_summary(gpt_data)
    grade_claude = _grade_summary(claude_data) if claude_data else None
    return jsonify({
        "persona": persona,
        "number": num,
        "metadata": {k: v for k, v in gpt_data.items() if k not in ("exchanges", "grade")},
        "exchanges": gpt_data.get("exchanges", []),
        "grade_gpt": grade_gpt,
        "grade_claude": grade_claude,
    })


@app.route("/transcript/<persona>/<num>")
def transcript_page(persona, num):
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
