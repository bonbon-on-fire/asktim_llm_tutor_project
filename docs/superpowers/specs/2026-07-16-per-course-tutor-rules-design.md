# Per-course tutor rules (`tutor_rules.txt`) — design

**Date:** 2026-07-16

## Problem

Different courses have slightly different requirements for how the tutor should
behave (e.g. `supply_chain_design` wants spreadsheet/Excel assumed over Python,
and Solver problems shared as screenshots). We don't want to fork a whole new
tutor prompt version per course — the base prompt (`tutor_07`) should stay the
single, centrally-maintained source of truth.

## Approach: add-on delta

A course may drop a `curriculum/<course>/tutor_rules.txt` file containing **only
its course-specific rules**. At system-prompt build time we load the base prompt
as today, then, if that file exists and is non-empty, append its contents. No
file → base prompt unchanged. This is purely additive:

- The stored `conversations.tutor_prompt` stays `tutor_07` — DB, `_validation.py`,
  and `DEFAULT_TUTOR` are untouched.
- Improving the base to a future `tutor_08` reaches every course automatically;
  each course only maintains its small delta.

Rejected alternative: **full replacement** (`tutor.txt` IS the whole prompt).
Re-introduces the per-course duplication we're trying to avoid — a later base
improvement wouldn't reach any course that overrode it.

## Mechanism

Single shared helper in `utils.curriculum` (next to `read_solution`), so the
append logic isn't duplicated and `tutor/` stays unaware of curriculum layout:

```python
def read_course_tutor_rules(course, curriculum_root=None) -> str:
    """Return curriculum/<course>/tutor_rules.txt stripped, or '' if absent/empty."""

def append_course_tutor_rules(base_prompt, course, curriculum_root=None) -> str:
    """Append the course's tutor_rules under a header; return base unchanged if none."""
```

Append format (at the very end, after the assignment substitution has already
run — no fragile parsing of the base prompt):

```
<full tutor_07 with <Assignment> filled in>

## Course-specific rules:
<contents of curriculum/<course>/tutor_rules.txt>
```

End placement keeps the base centrally maintainable and gives the course delta
recency weight.

## Where it plugs in (apply everywhere — eval must mirror production)

1. **Both apps** — `ui_core.tutor_bridge.build_system_prompt`. Thread `course`
   into the method (it's currently a positional on `_get_or_build_graph` /
   `_get_or_build_stream_context`, not in `**ctx`); update those two call sites.
   `sandbox_ui` inherits the base method unchanged.
2. **Bulk-simulation runners** — `internal_testing/run_transcript.py` and
   `run_transcript_rag.py` call `load_system_prompt` directly, bypassing the
   bridge. Apply `append_course_tutor_rules(system_prompt, config.course)` right
   after they load the base, so judged transcripts reflect the exact deployed
   prompt.

## Caching

Safe as-is: the graph/stream `cache_key` already includes `course`, so a course
with rules gets its own cache entry — no cross-contamination.

## Seed file

Ship `curriculum/supply_chain_design/tutor_rules.txt` capturing the 07/16 notes'
course-specific behavior (spreadsheet-over-Python default; Solver → ask for a
screenshot). Doubles as the first real consumer and a test fixture.

## Edge cases

- Missing file → no-op (base only). Most courses won't have one.
- Empty / whitespace-only → treated as absent.
- File-not-found is never an error.

## Tests

- `read_course_tutor_rules`: present / absent / empty, via a temp curriculum dir.
- `append_course_tutor_rules` / `build_system_prompt`: base-only vs. base+appended.
