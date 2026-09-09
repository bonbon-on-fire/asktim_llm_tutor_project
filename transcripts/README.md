# Transcripts

Generated tutor–student conversation transcripts for the AskTIM LLM Tutor project.

The corpus currently on disk is a **head-to-head comparison study**, not a
single-tutor sample: every conversation was run under one of two tutor
implementations so the two can be graded on the same problems and scored side by
side.

- **`asktim`** — the current AskTIM tutor (`tutor_07`, RAG context per turn).
- **`stem`** — the vendored MIT `open_learning_ai_tutor` baseline (no course
  context; `context_mode = "none"`). The comparison charts label these two arms
  "New AskTIM" and "STEM AskTIM".

The study spans two courses ("rounds"):

| Round token | Course | Problems | Kind |
| ----------- | ------ | -------- | ---- |
| `cmp` | `supply_chain_design` (MIT CTL.SC2x) | practices 1–3 | `practice` |
| `phys` | `physics_iii_vibrations_and_waves` | exercises 11–13 | `exercise` |

## Folder Structure

Current on-disk layout. Each persona-type folder holds **four** comparison
subfolders — one per `{round}_{arm}` combination — plus a legacy empty
`_judge/` folder:

```text
transcripts/
├── chaotic/                             # Chaotic student persona type
│   ├── chaotic_cmp_asktim/              # Supply Chain · New AskTIM  (9 raw + 9 graded)
│   ├── chaotic_cmp_stem/                # Supply Chain · STEM AskTIM (9 raw + 9 graded)
│   ├── chaotic_phys_asktim/             # Physics III · New AskTIM   (9 raw + 9 graded)
│   ├── chaotic_phys_stem/               # Physics III · STEM AskTIM  (9 raw + 9 graded)
│   └── chaotic_judge/                   # legacy (empty; .gitkeep only)
├── cooperative/                         # …same four + _judge/
├── clueless/                            # …same four + _judge/
└── README.md
```

Each `{round}_{arm}` folder contains **9 conversations** = 3 persona variants
(`_01`/`_02`/`_03`) × 3 problems × 1 trial. Across 3 persona types × 4
folders that is **108 conversations** total — the exact set the comparison
charts read (`visualization/run_comparison_viz.py`).

> **`_judge/` is legacy.** It is the output folder of the older single-tutor
> pipeline (`internal_testing.run_transcript_judge`), which grades into
> `{persona}_judge/` under the raw filename. The comparison study does not use
> it — it grades **in place** (see below) — so these folders are empty (a
> `.gitkeep` placeholder only). An earlier version of this README described a
> `_raw/` + `_judge/` corpus of 648 transcripts; that corpus is gone.

## File Naming

Inside each `{round}_{arm}` folder, every conversation is a **pair** of files
that share a stem:

- **`transcript_NN.json`** — the raw (ungraded) conversation.
- **`transcript_NN_graded.json`** — a copy with a top-level `grade` object
  appended by the judge. Written **next to** the raw file (in-place), *not* to a
  separate `_judge/` folder.

`NN` is a two-digit sequential index (`transcript_01` … `transcript_09`),
assigned per folder by `_next_transcript_number()` in
[`internal_testing/run_transcript_rag.py`](../internal_testing/run_transcript_rag.py).

> Note: older, now-removed corpora used two-, three-, or four-digit padding
> (`transcript_1`, `transcript_001`, `transcript_0001`). Mixed forms may
> coexist in a folder.

## Transcript JSON Schema

Every raw transcript follows this structure (values shown are from a real
`cmp_asktim` file):

```json
{
  "tutor_provider": "claude",
  "tutor_prompt": "tutor_07",
  "tutor_impl": "asktim",
  "student_persona": "chaotic_01",
  "course": "supply_chain_design",
  "exercise_number": "2",
  "exercise_kind": "practice",
  "context_mode": "rag",
  "figures": [],
  "turn_size": 10,
  "context": "Short course description (course.txt)...",
  "exercise": "Problem prompt + run configuration...",
  "turns": 10,
  "cost_estimate": { "total_usd": 0.21, "by_component_usd": { "...": "..." } },
  "exchanges": [
    {
      "turn": 1,
      "student": "Student message...",
      "tutor": "Tutor response...",
      "pedagogical_reasoning": "Internal tutor reasoning...",
      "retrieved": [ { "source": "...", "score": 0.45, "chars": 1005, "text": "..." } ],
      "cost": { "usd": 0.0167, "calls": { "student": {}, "tutor": {}, "embedding": {} } }
    }
  ]
}
```

The graded copy (`transcript_NN_graded.json`) is identical plus a top-level
`grade` object:

```json
{
  "grade": {
    "sections": {
      "1_pedagogy": { "criteria": { "1.1": {}, "1.2": {}, "1.3": {} }, "base": { "score": 18, "max": 20 } },
      "2_dialogue_quality": { "criteria": { "2.1": {}, "2.2": {} }, "base": { "score": 11, "max": 12 } },
      "3_communication_quality": { "criteria": { "3.1": {}, "3.2": {} }, "base": { "score": 8, "max": 8 } }
    },
    "total_base_score": 37,
    "max_base_score": 40,
    "overview": "Brief evidence-based overview.",
    "judge_reasoning": "Explicit rationale for major deductions and score.",
    "total_score": 37,
    "max_score": 40,
    "model": { "provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0 },
    "judge_llm_calls": 1
  }
}
```

### `asktim` vs `stem` fields

The two arms record slightly different context:

- **`asktim`** — `context_mode = "rag"`; the tutor's context is retrieved per
  turn, so each `exchanges[i]` carries a **`retrieved`** array (the chunks RAG
  pulled that turn: `[{source, score, chars, text}]`). `context` is just the
  short course description; the full lecture dump is **not** written in
  (the RAG tutor never saw it as one block).
- **`stem`** — `tutor_impl = "stem"`, `tutor_prompt = "open_learning_ai_tutor
  (vendored)"`, `context_mode = "none"`; the baseline gets no course context, so
  its exchanges have an empty `retrieved`.

Both arms carry a per-turn **`cost`** and a top-level **`cost_estimate`**
(`{total_usd, by_component_usd, by_model, rates_note}`), which the comparison
"tutor cost" chart reads.

### Key Fields

| Field | Description |
| ----- | ----------- |
| `tutor_impl` | Which tutor produced the run: `asktim` (ours) or `stem` (vendored baseline). Drives the two comparison arms. |
| `tutor_prompt` | Tutor system prompt version (`tutor_07` for `asktim`; `open_learning_ai_tutor (vendored)` for `stem`). |
| `tutor_provider` | LLM provider backing the tutor (`claude`). |
| `context_mode` | `rag` for `asktim`, `none` for `stem`. |
| `student_persona` | Persona identifier including its numeric variant (e.g. `chaotic_01`). |
| `course` | Course folder under `curriculum/` (`supply_chain_design` or `physics_iii_vibrations_and_waves`). |
| `exercise_kind` | `practice` (Supply Chain round) or `exercise` (Physics round). |
| `exercise_number` | Problem identifier within the course (non-padded). |
| `figures` | Curriculum figure filenames attached as multimodal input; `[]` when none. The judge re-resolves these to re-attach the same images at grading time. |
| `turn_size` / `turns` | Planned vs actual number of exchanges. |
| `exchanges` | Array of student–tutor exchange objects. |
| `grade.total_score` / `grade.max_score` | Judge score / maximum (40 for `rubric_08`). |

## Student Personas

| Type | Behavior |
| ---- | -------- |
| **chaotic** | Academic-integrity / tutor-vs-assistant boundary stressing (persistent answer-extraction, anti-capitulation). |
| **cooperative** | Good-student baseline: sincere, imperfect, non-adversarial. |
| **clueless** | Lost student, diagnosis-first: holds a stated misconception until specifically corrected. |

Each type has **three numbered variants** (`_01`/`_02`/`_03`) that probe the
same failure mode with a different strategy — `_01` scripted, `_02` unscripted,
`_03` strategy-sweep. Transcripts record the full variant in `student_persona`
(e.g. `chaotic_02`). See [`students/README.md`](../students/README.md) for the
persona definitions.

## How Transcripts Are Generated

Raw transcripts come from the RAG-context simulation runner, one invocation per
`{round}_{arm}` folder, selecting the arm with `--tutor-impl` and the folder
with `--output-suffix`:

```powershell
# Supply Chain round — New AskTIM arm (RAG, tutor_07)
python -m internal_testing.run_transcript_rag `
  --course supply_chain_design --tutor-impl asktim `
  --output-suffix cmp_asktim

# Supply Chain round — STEM AskTIM baseline (vendored, no context)
python -m internal_testing.run_transcript_rag `
  --course supply_chain_design --tutor-impl stem `
  --output-suffix cmp_stem

# Physics III round uses --course physics_iii_vibrations_and_waves and
# --output-suffix phys_asktim / phys_stem the same way.
```

The `stem` arm is driven through `internal_testing/stem_tutor_adapter.py`, which
wraps the vendored `open_learning_ai_tutor` so it can be run turn-by-turn against
the same simulated students.

## How Transcripts Are Graded

Grading is done by the tutor judge (`eval/tutor_judge/`) and written **in place**
as `transcript_NN_graded.json` next to each raw file (via the judge's
`output_name="transcript_NN_graded"`), so every folder holds the raw/graded pair.
The whole comparison corpus was graded by **`claude-sonnet-4-6`** against
**`rubric_08`** (40 points).

> The single-tutor runner `internal_testing.run_transcript_judge` uses a
> different convention — it copies raw transcripts into `{persona}_judge/` under
> the *same* filename. That path produced the older corpus and is why the empty
> `_judge/` folders still exist; it is not what the comparison study uses.

## Visualization

Two visualization entry points read this corpus:

```powershell
# The four-chart comparison deck (New AskTIM vs STEM AskTIM):
#   score by course, score by student type, answer-giving failures, tutor cost.
python -m visualization.run_comparison_viz

# The full single-tutor rubric profile (11 charts) for one arm's transcripts.
python -m visualization.run_visualization
```

Comparison charts land in `visualization/outputs/comparison/`. See
[`visualization/README.md`](../visualization/README.md) for the full chart list.
