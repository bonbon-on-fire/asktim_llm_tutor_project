---
name: Project overview
description: Core architecture, goals, and current state of the Humanities LLM Tutor Project 2026
type: project
---

Socratic LLM tutor for MIT OpenCourseWare (OCW) humanities/social sciences courses. Never gives answers directly — uses guided discovery and Socratic questioning.

**Why:** Deployment goal = reliable Socratic tutor for OCW students. Validation goal = reproducible eval framework to test/grade tutor behavior before deployment.

**Four layers:**
1. Conversation pipeline — LangGraph tutor + student agents trading messages
2. Judge pipeline — separate LangGraph agent scores finished transcripts against a rubric (JSON grade, up to 3 repair retries)
3. UI runners — `ui/run_ui_raw.py` (bulk transcript generation), `ui/run_ui_judge.py` (grading), `ui/run_ui_raw_mini.py` (single-transcript resume/replay)
4. Dashboard + visualization — Flask app for browsing GPT/Claude grades side-by-side; matplotlib correlation charts

**Current rubric:** `rubric_05` (46 pts): Pedagogy (24), Dialogue Quality (12), Communication Quality (10)

**Scale:** 18 personas (chaotic/cooperative/clueless × 6), 2 courses (philosophy + urban_studies), 864 total transcripts, graded by both GPT and Claude judges.

**Active work (as of 05/01/2026):**
- Iterating on tutor prompt (tutor_05 current)
- Human testing via web UI to surface issues AI-student runs miss
- Simulating turn-specific reference issues with `run_ui_raw_mini_batch.py` (25 mini runs, all in `*_mini/` with `_01`/`_02` suffix)
- Dashboard shows all `*_mini/` files against their raw source (mini-centric view)

**Removed:** `run_ui_judge_mini`, `run_ui_raw_two_layer`, `judge/run_judge_mini.py`, `tutor/run_tutor_two_layer.py` — two-layer tutor and comparison mini judge are not pursued.

**How to apply:** Frame suggestions around the LangGraph architecture, prompt-file versioning pattern, and rubric-driven evaluation workflow.
