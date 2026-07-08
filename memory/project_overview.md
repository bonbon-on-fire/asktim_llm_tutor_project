---
name: Project overview
description: Core architecture, goals, and current state of the AskTIM LLM Tutor Project 2026
metadata:
  type: project
---

Socratic LLM tutor for MIT OpenCourseWare (OCW) humanities/social-science courses. Never gives answers directly — guided discovery, bite-sized replies, formative feedback. Headline deliverable is **AskTIM**, an iframe-embeddable chat app **deployed on Railway** for Spring 2026 *MIT 11.270x Cities and Climate Change*.

**Why:** Deployment goal = reliable Socratic tutor for OCW students. Validation goal = reproducible eval framework to test/grade tutor behavior before deployment.

**Six loosely-coupled layers:**
1. Conversation pipeline — LangGraph tutor + adversarial student agents trading messages (`tutor/run_tutor.py`, `students/run_student.py`)
2. Judge pipeline — separate LangGraph agent scores transcripts against a rubric (validated JSON, up to 3 repair retries) (`eval/tutor_judge/run_judge.py`)
3. Internal runners — `internal_testing/run_transcript.py` (bulk generation), `run_transcript_judge.py` (grading); parallelized via ThreadPoolExecutor
4. Dashboard + visualization — Flask grade browser (port 5002) + matplotlib correlation charts
5. `main_ui/` — production AskTIM: Postgres (`asktim`, Alembic), SSE token streaming, bcrypt email+password identity, cross-browser history, sanitized markdown. **Deployed on Railway** (`Dockerfile_main`, entrypoint normalizes DATABASE_URL to `postgresql+psycopg://`).
6. `sandbox_ui/` — "AskTIM Sandbox" for devs/TAs: mirrors main_ui + Edit-context switcher + Create-context wizard, own `asktim_test` DB (`create_all`, no Alembic), teal `#126f9a`, port 5000. Railway deploy deferred (local-only).

**Rubric:** latest `judge_08`/`rubric_08` (40 pts: Pedagogy 20 / Dialogue 12 / Communication 8). In-code DEFAULT is still older `rubric_05` (46 pts). Active tutor prompt `tutor_05`. Claude is primary judge; GPT judging paused.

**Scale:** 3 personas (chaotic, cooperative, clueless — one per type, variety from `temperature=0.7`), **5 courses** (cities_and_climate_change live in AskTIM; plus intro_to_international_development_planning, mathematics_for_cs, physics_iii_vibrations_and_waves, meaning_of_life as June-2026 test contexts). ~927 graded transcripts migrated to canonical criterion format.

**Phase status (PLANNING.md):** Phases 1–5, 8, 9, 10 COMPLETE. **Phase 6 (figures/multimodal) and Phase 7 (human image uploads) PROPOSED, NOT STARTED** — `utils/figures.py` does not exist; main_ui ships text-only. Phase 6 is the prerequisite for image inputs. See [[tutor-context-expansion]].

**How to apply:** Frame suggestions around the LangGraph architecture, prompt-file versioning pattern, and rubric-driven evaluation workflow. Don't run git ops — see [[git-no-remote-ops]].
