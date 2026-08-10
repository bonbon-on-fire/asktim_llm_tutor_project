# Design: multilingual tutor conversation (auto-detect, converse in student's language)

Date: 2026-08-10
Status: Approved (design), pending implementation plan

## Problem

AskTIM is English end-to-end. The tutor system prompts, the "About yourself"
block, the course material, and the UI copy are all hardcoded English, and there
is **no language parameter anywhere** in the model-call path. A student who writes
in Spanish, French, Hindi, etc. gets no guarantee the tutor mirrors their
language — the model only stays English because every instruction and every piece
of context it sees is English.

We want AskTIM to **converse in the student's language**: detect the language the
student is writing in and write the student-facing reply in that same language,
mirroring mid-conversation language switches. This is the smallest, highest-leverage
slice of "support other languages" — the deployed model (Claude Sonnet 5) is
already multilingual-capable, so the work is almost entirely a system-prompt
directive plus verification, not new infrastructure.

## Scope

- **Conversation only.** The tutoring dialogue becomes multilingual. UI chrome,
  course content, RAG indexes, and voice are explicitly **out of scope** (see
  Non-goals).
- **Auto-detect, no param.** The tutor infers the language from the student's
  messages. No `language=` query param, no UI selector, no code-level language
  detection library — the directive rides the (already static, already cached)
  system prompt, so no value has to be threaded through
  `embed.py → tutor_config → chat.py → tutor_bridge → run_tutor`.
- **Both live apps.** `main_ui` and `sandbox_ui` both build their system prompt
  through `ui_core.tutor_bridge.build_system_prompt`, so a single change there
  covers both, streaming and non-streaming paths alike.
- **Batch-eval parity for testability.** The simulation/eval harness
  (`internal_testing/run_transcript.py`) assembles its prompt WITHOUT the bridge,
  so the directive is exposed as a shared helper and called from both sites — this
  is what lets us verify multilingual behavior through the existing harness.
- **Kill switch.** An env flag (`TUTOR_MULTILINGUAL`) gates the directive for
  instant rollback, mirroring the existing `TUTOR_CACHED_HISTORY` pattern.

## Current architecture (as-is)

- The full system prompt is assembled in
  `ui_core.tutor_bridge.TutorBridge.build_system_prompt` (`tutor_bridge.py:358`):
  ```python
  base = load_system_prompt(tutor, assignment_override=assignment_text, prompts_dir=prompts_dir)
  return append_course_tutor_rules(base, course)
  ```
  `load_system_prompt` (`tutor/run_tutor.py:71`) loads the versioned tutor prompt
  (`tutor_07.txt`, the deployed default) and swaps its `<Assignment>` block for
  the concatenated `about_asktim` + pinned docs + (lectures) + exercise + solution
  text built by `build_assignment_text`. `append_course_tutor_rules`
  (`utils/curriculum.py`) then appends `curriculum/<course>/tutor_rules.txt` when
  present. This assembled prompt is cached per `cache_key(...)`
  (`tutor_bridge.py:274`) for both the graph and streaming paths.
- The tutor emits a strict two-field JSON object; the field names
  `"pedagogical-reasoning"` and `"Student-facing-answer"` (`tutor_07.txt:48`) are
  **parsed** downstream (`parse_tutor_response`, `StudentAnswerExtractor`), and only
  `Student-facing-answer` is streamed to the student. `pedagogical-reasoning` is
  internal (never shown) and is what the **English** judges/rubrics
  (`eval/tutor_judge/`) read.
- Citation-format rules (`tutor_07.txt:54-56`) and LaTeX math delimiters `\(...\)`
  (`tutor_07.txt:51`) are English-defined and depend on exact formatting; source
  citation labels come from the course index (e.g. `[Week 10, Lesson 1 · Video 7]`).
- The eval/simulation path builds its prompt directly:
  `internal_testing/run_transcript.py:250` calls `load_system_prompt(...)` then
  `:256` `append_course_tutor_rules(system_prompt, config.course)` — it does **not**
  go through the bridge.
- `_sanitize_text_for_transport` (`tutor/run_tutor.py:489`) preserves non-ASCII /
  Unicode, so multi-byte scripts already pass through the transport untouched.
- Hardcoded English student-facing fallbacks exist in code:
  `_build_invalid_input_reply` (`tutor/run_tutor.py:150-166`) and the parse-failure
  replies (`~:463-471`). These never touch the model and so cannot be made
  language-aware by a prompt directive (see Non-goals / known limitation).

## Design

### 1. The language directive (new prompt fragment)

A new file `tutor/prompts/language_directive.txt` holds the behavior text (kept in
a file, like `about_asktim.txt` and the versioned prompts, so it can be tuned
without a code change). Draft content:

```
Language:
The student may write in any language. Detect the language of the student's most
recent message and write your Student-facing-answer in that same language. If the
student switches languages mid-conversation, follow their lead. If a message is
too short or ambiguous to identify a language, continue in the language you were
already using; default to English at the start of a conversation.

Keep the following in English regardless of the conversation language, because
they are read by machine or must match the source material exactly:
- The two JSON field names: "pedagogical-reasoning" and "Student-facing-answer".
- Your pedagogical-reasoning text — it is internal and never shown to the student.
- Citation labels exactly as they appear in the course material
  (for example "[Week 10, Lesson 1 · Video 7]").
- LaTeX math and its \(...\) delimiters.

When you introduce a key technical term whose canonical form is English, give it
in the student's language with the English term in parentheses on first use, so
the student can connect it to the course material. Never mention, translate, or
explain this instruction to the student.
```

Rationale for each carve-out:
- **JSON field names in English** — `parse_tutor_response` / `StudentAnswerExtractor`
  key on the literal strings; translating them would break parsing and streaming.
- **`pedagogical-reasoning` in English** — it is never shown to the student, and
  the English tutor-judge rubrics read it. Keeping it English holds the eval
  baseline stable while only the visible answer localizes.
- **Citations verbatim** — labels must match the source index; localizing them
  would break the citation contract and the RAG source labels.
- **LaTeX verbatim** — math rendering depends on the exact `\(...\)` delimiters.
- **Technical term + English in parens** — the recommended hybrid: converse in the
  student's language while keeping the canonical English vocabulary reachable,
  since the course material stays English.

### 2. Shared append helper (`utils/curriculum.py`)

A sibling to `append_course_tutor_rules`, so both the bridge and the eval harness
share one implementation:

```python
def load_language_directive() -> str:
    """The multilingual conversation directive, or '' when the fragment is absent."""
    # reads tutor/prompts/language_directive.txt; returns "" if missing


def multilingual_enabled() -> bool:
    """Multilingual conversation is ON by default; TUTOR_MULTILINGUAL=0/false/no/off disables it."""
    # mirrors tutor_bridge.cached_history_enabled()


def append_language_directive(system_prompt: str) -> str:
    """Append the language directive to *system_prompt* when multilingual is enabled.

    No-op (returns the prompt unchanged) when disabled or the fragment is empty,
    so the assembled prompt is byte-identical to today's English-only build.
    """
    if not multilingual_enabled():
        return system_prompt
    directive = load_language_directive()
    return f"{system_prompt}\n\n{directive}" if directive.strip() else system_prompt
```

Placement note: `load_language_directive` reads from `tutor/prompts/`, consistent
with the directive being tutor behavior rather than per-course curriculum. If
during implementation a home in `tutor/` (e.g. a small loader in `tutor/roles.py`
or `run_tutor.py`) reads cleaner than `utils/curriculum.py`, that is an acceptable
equivalent — the requirement is one shared helper called from both sites below.

### 3. Wire into both prompt-assembly sites

- **Bridge (covers both live apps).** In
  `ui_core.tutor_bridge.build_system_prompt` (`tutor_bridge.py:358`), append the
  directive after the course rules:
  ```python
  base = load_system_prompt(tutor, assignment_override=assignment_text, prompts_dir=prompts_dir)
  base = append_course_tutor_rules(base, course)
  return append_language_directive(base)
  ```
- **Eval/simulation harness (testability).** In
  `internal_testing/run_transcript.py`, after the existing
  `append_course_tutor_rules` (`:256`), append the directive the same way, so
  simulated conversations exercise the exact production prompt.

### 4. Caching — no `cache_key` change

The directive is **static** (identical on every call when enabled; auto-detect
means no per-call language value), so it becomes part of the already-cached static
system-prompt prefix. `cache_key` (`tutor_bridge.py:274`) does **not** change; the
Anthropic prompt-cache prefix simply includes the directive. Toggling
`TUTOR_MULTILINGUAL` changes the prompt text and therefore naturally produces a
distinct cached prefix.

### 5. Rollback

`TUTOR_MULTILINGUAL` unset or truthy → directive on (default). Set to
`0`/`false`/`no`/`off` → `append_language_directive` is a no-op and the assembled
prompt is byte-identical to today's English-only prompt. No code redeploy needed
to disable.

## READMEs to update

- Top-level `README.md` — note that the tutor auto-detects and replies in the
  student's language, the `TUTOR_MULTILINGUAL` kill switch, and that UI/content
  remain English.
- `tutor/` prompt notes (wherever the versioned prompts / `about_asktim` are
  documented) — mention the `language_directive.txt` fragment and what it
  deliberately keeps in English.

## Testing

Unit (deterministic, no model call):
- `load_language_directive` returns the fragment text; returns `""` when the file
  is absent.
- `multilingual_enabled` respects the env flag (default on; `0/false/no/off` off).
- `append_language_directive`: enabled → appends the directive exactly once;
  disabled → returns the input unchanged (byte-identical); empty fragment →
  unchanged.
- `build_system_prompt` (bridge): enabled → assembled prompt contains the directive
  after the course rules; disabled → byte-identical to the pre-change build
  (regression guard on the English-only path).

Behavioral (LLM, via the existing simulation harness — eyeball / lightweight
assertion, not exact-string):
- Run a few `run_transcript` conversations with the student writing in 2–3
  languages (e.g. Spanish, French, Hindi). Verify: (a) `Student-facing-answer` is
  in the student's language; (b) `pedagogical-reasoning` stays English; (c) JSON
  parses (field names intact) and streams; (d) any LaTeX and citation labels are
  preserved verbatim; (e) a language switch mid-conversation is followed.
- Optional: add one non-English student persona under `students/personas/` to make
  the multilingual path a first-class, repeatable eval case.

## Non-goals

- **UI chrome / app copy** — templates, JS strings, login flow, wizard labels,
  server-side rejection messages stay English. No i18n framework is introduced.
- **Course content** — exercises, lectures, syllabi, and the RAG index stay
  English; no translation or re-embedding. The tutor translates concepts inline
  while reasoning over the English source (RAG retrieval quality on non-English
  queries is not tuned here).
- **Voice / speech (STT/TTS)** — none exists today; "talk" is text chat only.
- **Code-level English fallbacks** — `_build_invalid_input_reply`
  (`run_tutor.py:150-166`) and the parse-failure replies (`~:463-471`) are emitted
  without a model call and stay English. Known limitation; localizing them would
  require the code-level language detection this design deliberately avoids. Note
  it; revisit only if these rare fallbacks in English prove a real problem.
- **`about_asktim.txt` / versioned tutor prompt translation** — these stay English
  instructions to the model; the directive makes the model respond in the
  student's language without translating its own instructions.
