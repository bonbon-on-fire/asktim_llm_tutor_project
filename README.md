# Humanities LLM Tutor Project 2026

## Quick Start

### Prerequisites
- **Python**: 3.11 or higher
- **OpenAI API key**: `$env:OPENAI_API_KEY = "your-key"`
- **Anthropic API key** (for Claude): `$env:ANTHROPIC_API_KEY = "your-key"`

### 1. Clone and Install
```powershell
git clone https://github.com/yourusername/humanities_llm_tutor_project_2026.git
cd humanities_llm_tutor_project_2026
pip install -r requirements.txt
```

### 2. Generate Conversations
```powershell
# Edit TUTOR_PROMPTS, STUDENT_PERSONAS, COURSE_EXERCISES in ui/run_ui_raw.py, then:
python -m ui.run_ui_raw
```

### 3. Grade Transcripts
```powershell
python -m ui.run_ui_gpt     # Grade all raw transcripts with GPT
python -m ui.run_ui_claude  # Grade all raw transcripts with Claude
```

### 4. Browse Results
```powershell
python -m dashboard_ui.run_dashboard_ui
# Open http://127.0.0.1:5001
```

## Project Overview

### What I Built

I designed and built an end-to-end LLM tutoring research platform for MIT OpenCourseWare (OCW) humanities and social sciences courses. The system simulates Socratic tutoring conversations between an AI tutor and AI student bots, grades those conversations using a second LLM acting as a judge, and produces side-by-side GPT vs Claude score comparisons for analysis.

The tutor is constrained to never give direct answers — it uses guided discovery, bite-sized responses, and formative feedback to walk students through assignments on topics like the trolley problem in philosophy or climate geography in urban studies. To stress-test the tutor, I built a set of adversarial student personas — each one probing a specific failure mode: giving away answers under pressure, going off-topic, or lecturing a student who is genuinely lost.

The result is a complete research pipeline: generate conversations in bulk across all persona × course × exercise combinations, grade them automatically with GPT and Claude using a structured rubric, and visualize where the two judges agree or diverge.

### Why I Built It

- **Research goal**: Evaluate whether LLM tutors can reliably maintain Socratic dialogue across different student personalities, subjects, and difficulty levels — and whether GPT and Claude score those conversations consistently.
- **Engineering goal**: Build a reproducible, parallelized experiment framework where every conversation, grade, and comparison is saved to disk and inspectable through a dashboard.

## Technical Overview

### System Architecture

The system has four loosely coupled layers:

- **Conversation pipeline**: Two LangGraph agents (tutor + student) trade messages in a structured multi-turn loop. Each agent is independently configurable via system prompt files.
- **Judge pipeline**: A separate LangGraph agent reads a finished transcript and returns a structured JSON grade against a rubric. Supports both single-transcript and batch (holistic, 3-transcript) grading.
- **Batch experiment system**: Three experiment types — consistency, cross-exercise, persona differentiation — each covering 198 pre-generated batch files with zero transcript overlap.
- **Dashboard + visualization**: A Flask web app for browsing transcripts side-by-side with GPT/Claude grades, and a matplotlib chart module for Pearson r / Spearman rho correlation analysis.

### Key Components

**Tutor Agent (`tutor/run_tutor.py`)**: A LangGraph graph with a single node that calls GPT and returns a two-field JSON response — internal pedagogical reasoning (hidden from students) and a student-facing answer. The system prompt is loaded from a versioned `.txt` file and can be overridden with an assignment block at runtime.

**Student Bot (`students/run_student.py`)**: Shares the same LangGraph infrastructure as the tutor, but uses a persona prompt from `students/personas/` to simulate a specific type of student. Includes a heuristic guard and automatic retry if the bot starts sounding like a tutor.

**Judge (`judge/run_judge_gpt.py`, `run_judge_claude.py`)**: Reads a transcript, constructs a grading prompt by injecting the rubric and output schema, and calls the model. Validates the JSON response against the rubric spec, auto-repairs on failure (up to 3 attempts), and writes the grade back into the transcript file.

**Batch Judge (`judge/run_judge_batch_gpt.py`, `run_judge_batch_claude.py`)**: Combines 3 transcripts into one prompt for holistic, comparative grading — allowing the judge to evaluate consistency or persona differentiation across a set.

**UI Runners (`ui/`)**: Five parallelized batch runners (ThreadPoolExecutor, default 6 workers) for raw generation and GPT/Claude judging of individual and batch transcripts. All accept `--prompt` and `--rubric` CLI flags.

**Dashboard (`dashboard_ui/`)**: Flask app that discovers all transcripts and batch files on disk, loads GPT and Claude grades for each, and serves a sortable comparison table and per-transcript detail view via a single-page JS frontend.

## Code in Action: Conversation Example

### 1. Tutor Prompt (excerpt from `tutor/prompts/tutor_03.txt`)

```
You are a Socratic tutor. Never state the answer directly.
Use guided questions to help the student arrive at insights themselves.
Keep responses short — one or two focused questions or observations per turn.
```

### 2. Student Persona (excerpt from `students/personas/chaotic_01.txt`)

```
You are a student who wants the tutor to just give you the answer.
Push back when the tutor asks questions. Try asking directly: "Can you just tell me the answer?"
If the tutor refuses, complain that the class is too hard and that Socratic method is unhelpful.
```

### 3. Resulting Conversation (from `transcripts/chaotic/chaotic_raw/transcript_01.json`)

```
Turn 1
Student: Can you just tell me what act consequentialism says? I don't have time for the back and forth.
Tutor: What do you think "consequences" means in everyday language — what does it focus on?

Turn 2
Student: Ugh, fine. It means what happens after. But why can't you just explain it?
Tutor: You're already halfway there. If act consequentialism focuses on what happens after — whose "what happens" are we measuring?

Turn 3
Student: I guess everyone affected? This feels like a lot of work for one definition.
Tutor: Exactly — everyone affected. So if an action helps the most people overall, what does that say about whether the action is right or wrong?
```

### 4. Judge Output (grade written into the transcript JSON)

```json
{
  "grade": {
    "sections": {
      "1_pedagogy": { "base": { "score": 20, "max": 24 } },
      "2_dialogue_quality": { "base": { "score": 10, "max": 12 } },
      "3_communication_quality": { "base": { "score": 8, "max": 10 } }
    },
    "total_score": 38,
    "max_score": 46,
    "overview": ["Tutor maintained Socratic stance under pressure. Good use of short questions. Could scaffold more on the student's frustration."],
    "model": { "provider": "openai", "model": "gpt-5.4" }
  }
}
```

## How the Workflow Runs

**1. Load prompts and build agents**

```python
system_prompt = load_system_prompt("tutor_03", assignment_override=assignment_text)
tutor_graph = create_tutor_graph(system_prompt)
student_graph = build_graph(prompt_name="chaotic_01")
```

**2. Run the multi-turn conversation loop**

```python
for turn_index in range(config.turn_size):
    student_msg = get_next_student_message(student_messages, graph=student_graph)
    tutor_messages, tutor_text = get_tutor_reply(tutor_messages, graph=tutor_graph)
```

**3. Save the raw transcript to disk**

```python
payload = {
    "tutor_prompt": "tutor_03", "student_persona": "chaotic_01",
    "course": "philosophy", "exercise_number": "01",
    "exchanges": transcript_exchanges,
}
transcript_path.write_text(json.dumps(payload, indent=2))
```

**4. Grade the transcript with the judge**

```python
result = judge_transcript(
    "chaotic/chaotic_gpt/transcript_01",
    prompt_name="judge_05",
    rubric_name="rubric_05",
)
print(result.total_score, result.max_score)  # e.g. 38, 46
```

**5. Grade a batch of 3 transcripts together**

```python
result = judge_transcript_batch(
    "transcripts/batches/batches_raw/batch_01/batch_001.txt",
    prompt_name="judge_05",
    rubric_name="rubric_05",
    output_path="transcripts/batches/batches_gpt/batch_01/batch_001.json",
)
```

**6. Generate score comparison charts**

```powershell
python -m visualization.run_visualization
# Output: visualization/outputs/individual_grades_gpt_vs_claude.png
```

## Project Structure & File Guide

### Directory Overview

```text
humanities_llm_tutor_project_2026/
│
├── curriculum/
│   ├── philosophy/          # course.txt + exercise_01.txt (trolley problem)
│   └── urban_studies/       # course.txt + exercise_01..03.txt (climate data)
│
├── students/
│   ├── run_student.py       # Shared LangGraph engine for all personas
│   └── personas/            # chaotic_01..06, chitchat_01..06, clueless_01..06
│
├── tutor/
│   ├── run_tutor.py         # LangGraph engine + prompt loading + response parsing
│   └── prompts/             # tutor_01.txt, tutor_02.txt, tutor_03.txt
│
├── judge/
│   ├── run_judge_gpt.py          # Single-transcript GPT judge
│   ├── run_judge_claude.py       # Single-transcript Claude judge
│   ├── run_judge_batch_gpt.py    # Batch GPT judge
│   ├── run_judge_batch_claude.py # Batch Claude judge
│   ├── prompts/             # judge_01..06.txt
│   └── rubrics/             # rubric_01..06.md (current: rubric_05)
│
├── ui/
│   ├── run_ui_raw.py        # Generate raw transcripts (edit config at top)
│   ├── run_ui_gpt.py        # Grade all raw transcripts with GPT
│   ├── run_ui_claude.py     # Grade all raw transcripts with Claude
│   ├── run_ui_batch_gpt.py  # Grade batch bundles with GPT
│   └── run_ui_batch_claude.py  # Grade batch bundles with Claude
│
├── transcripts/
│   ├── chaotic/             # chaotic_raw/, chaotic_gpt/, chaotic_claude/
│   ├── chitchat/            # chitchat_raw/, chitchat_gpt/, chitchat_claude/
│   ├── clueless/            # clueless_raw/, clueless_gpt/, clueless_claude/
│   └── batches/             # batches_raw/, batches_gpt/, batches_claude/
│
├── dashboard_ui/
│   ├── run_dashboard_ui.py  # Flask app: routes, data loading, grade summaries
│   └── static/app.js        # Frontend: routing, sortable table, Chart.js histograms
│
├── visualization/
│   └── run_visualization.py # Line charts: GPT vs Claude scores, Pearson r, Spearman rho
│
└── utils/
    └── parsing.py           # Shared JSON extraction helper
```

### File & Format Details

#### 1. Tutor and Student Prompts

- **Location:** `tutor/prompts/<name>.txt`, `students/personas/<name>.txt`
- **Format:** Plain text system prompts. Selected by name at runtime (e.g. `tutor_03`, `chaotic_01`). Tutor prompts include an `<Assignment>...</Assignment>` block that gets replaced with the exercise text.

#### 2. Rubric Files

- **Location:** `judge/rubrics/<name>.md`
- **Format:** Markdown rubric injected into the judge system prompt at runtime. Current rubric is `rubric_05` (46 points, 3 sections, no malus deductions).

| Section | Criteria | Max |
| ------- | -------- | --- |
| 1. Pedagogy | Socratic method, scaffolding, meta-learning | 24 |
| 2. Dialogue quality | Redundancy, assignment anchoring | 12 |
| 3. Communication quality | Bite-sized responses, tone | 10 |

#### 3. Transcript Files

- **Location:** `transcripts/<persona>/<persona>_raw/transcript_NN.json`
- **Format:** JSON with run metadata, `exchanges` array, and (after grading) a `grade` object. See `transcripts/README.md` for the full schema.

#### 4. Batch Files

- **Location:** `transcripts/batches/batches_raw/batch_XX/batch_NNN.txt`
- **Format:** Plain text, one transcript path stem per line (comments with `#` are skipped). Three paths per file.

#### 5. UI Runner Config

- **Location:** Top of each `ui/run_ui_*.py` file
- **Format:** Python constants (`TUTOR_PROMPTS`, `STUDENT_PERSONAS`, `COURSE_EXERCISES`, `TRIALS`, `PARALLEL_WORKERS`). Edit directly before running.

## Current Status

The full pipeline is working end-to-end, with:

- 3 persona families × 6 variants each (chaotic, chitchat, clueless) — 18 student personas total
- 2 courses: `philosophy` (1 exercise) and `urban_studies` (3 exercises)
- 288 raw transcripts × 3 persona types = 864 total transcript files (raw + GPT-graded + Claude-graded)
- 198 batch files across 3 experiment types (72 + 54 + 72), covering 594 unique transcripts
- Rubric versioned up to `rubric_06` (current default: `rubric_05`, 46 pts)
- Dashboard fully functional for side-by-side GPT/Claude grade comparison
- Visualization outputs Pearson r and Spearman rho between GPT and Claude scores

## Challenges and How I Solved Them

**Keeping the tutor in Socratic mode**: Getting GPT to never reveal answers required extensive prompt engineering. Added pedagogical-reasoning as a separate JSON field so the model "thinks out loud" before answering, which consistently improves restraint.

**Adversarial student bots that sound like tutors**: The student LangGraph node includes a heuristic that detects tutor-like phrasing (numbered agendas, coaching frameworks) and auto-retries with a correction message before returning the response.

**LLM judge output validation**: Judge responses sometimes came back with float scores, missing fields, or malformed JSON. Built a multi-strategy extraction pipeline (raw JSON → fenced code block → brace extraction → `ast.literal_eval`) with up to 3 repair-and-retry cycles.

**Batch experiment design**: Ensuring zero transcript overlap within each batch type while maintaining balanced coverage across personas and courses required a careful grouping algorithm. Each of the 198 batches contains exactly 3 unique transcripts, and no transcript appears twice in the same batch type.

**GPT vs Claude grade alignment**: Initial rubric versions produced high inter-judge variance. Migrating to `rubric_05` (simplified scoring, no malus deductions, mandatory sub-criterion IDs on deductions) measurably improved GPT/Claude correlation.

## Future Possibilities

- Statistical analysis of batch experiment results (score variance, exercise difficulty effects, persona differentiation scores)
- Additional student persona families and course subjects
- Human-in-the-loop evaluation to calibrate the LLM judge against human graders
- Streaming live conversations through the dashboard UI
- ML-assisted rubric refinement based on judge disagreement patterns

## TL;DR

I built a full research pipeline that simulates adversarial Socratic tutoring conversations between an LLM tutor and student bots, grades those conversations automatically using GPT and Claude as judges, and compares the two judges across 864 transcripts and 198 batch experiment files — with a web dashboard for browsing results and a visualization module for correlation analysis.

---

**Project Duration:** Spring 2026  
**Technologies:** Python, LangGraph, LangChain, OpenAI API, Anthropic API, Flask, Chart.js, matplotlib, Git
