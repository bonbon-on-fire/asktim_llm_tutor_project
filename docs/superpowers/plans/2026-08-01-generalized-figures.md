# Generalized Figures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make curriculum figures work for lectures and practices (not just exercises), attaching a lecture/practice figure as vision content only on turns where that item's chunk was retrieved.

**Architecture:** Generalize the figure-naming convention to `<kind>_<id>_<slug>.<ext>` (`kind ∈ {exercise, lecture, practice}`). `utils/figures.py` gains a source-driven discovery helper that maps retrieved RAG chunk labels (`local:lecture_5_...`) to their sibling figures. Exercise figures stay bound once at graph-build time (unchanged); lecture/practice figures flow per-turn through a new `TutorState.turn_figures` field and are attached to the same student message. The tutor-judge unions in the per-turn figures reconstructed from each exchange's persisted `retrieved` records so it grades against the same images.

**Tech Stack:** Python 3, LangGraph/LangChain, standalone (non-pytest) test harness run via `python -m utils.test_figures`.

## Global Constraints

- Figure filenames: `<kind>_<id>_<slug>.<png|jpg|jpeg>`, `kind ∈ {exercise, lecture, practice}`, extension case-insensitive, `<id>` = the number in the sibling `.txt` stem. Copied verbatim from the spec.
- `discover_figures(course, exercise_number)` MUST remain exercise-only and byte-for-byte behavior-compatible — every existing caller depends on it.
- Figures are always optional and back-compatible: a missing folder / no match returns `[]` and the message shape is identical to today.
- RAG chunk source labels have the form `local:<stem>` (e.g. `local:lecture_5_introducing_the_case_study_cities`); the retrieved-record dict shape is `{"source", "score", "chars", "text"}`.
- Tests use the repo's standalone harness (`_check(...)`, registered in `main()`), NOT pytest. Run with `python -m utils.test_figures`.
- Commit style: Conventional Commits; do NOT add a `Co-Authored-By: Claude` trailer.

---

### Task 1: Generalize figure discovery in `utils/figures.py`

**Files:**
- Modify: `utils/figures.py` (regex at line 26; `discover_figures` at 35-65; module docstring 11-14; add new helper + source regex)
- Test: `utils/test_figures.py` (add tests + register in `main()`)

**Interfaces:**
- Consumes: `course_dir(course, curriculum_root)` from `utils.curriculum` (already imported).
- Produces:
  - `discover_figures(course, exercise_number, curriculum_root=None) -> list[Path]` — unchanged signature/behavior: returns only `exercise_<N>_*` figures.
  - `discover_figures_for_sources(course, sources, curriculum_root=None) -> list[Path]` — `sources` is an iterable of RAG source labels (`local:lecture_5_...` or bare stems); returns deduped, filename-sorted sibling figures for the exercise/lecture/practice items named. Empty when nothing matches.

- [ ] **Step 1: Write the failing tests**

Add these four test functions to `utils/test_figures.py` (after `test_discovery_filters_and_isolates_by_exercise`, before the `image_to_data_url` section):

```python
# ---------------------------------------------------------------------------
# discover_figures_for_sources (lectures + practices)
# ---------------------------------------------------------------------------

def test_discover_for_sources_matches_lecture_and_practice() -> None:
    """Assert source labels map to their sibling lecture/practice figures."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "lecture_5_two_cities.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_5_extra.jpg").write_bytes(b"\xff\xd8\xff")
        (figdir / "practice_3_diagram.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_6_unrelated.png").write_bytes(b"\x89PNG\r\n")

        # A retrieved chunk from lecture 5 pulls both of lecture 5's figures.
        names = figure_filenames(
            discover_figures_for_sources(
                "demo", ["local:lecture_5_introducing_the_cities"], curriculum_root=root
            )
        )
        _check(
            "lecture source -> sorted sibling figures",
            names == ["lecture_5_extra.jpg", "lecture_5_two_cities.png"],
            f"got {names}",
        )

        # Multiple sources (lecture + practice) union their figures.
        names2 = figure_filenames(
            discover_figures_for_sources(
                "demo",
                ["local:lecture_5_intro", "local:practice_3_x", "local:key_concepts"],
                curriculum_root=root,
            )
        )
        _check(
            "lecture+practice sources union; key_concepts contributes nothing",
            names2 == ["lecture_5_extra.jpg", "lecture_5_two_cities.png", "practice_3_diagram.png"],
            f"got {names2}",
        )


def test_discover_for_sources_dedupes_repeated_sources() -> None:
    """Assert the same lecture retrieved twice yields each figure once."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "lecture_5_a.png").write_bytes(b"\x89PNG\r\n")
        names = figure_filenames(
            discover_figures_for_sources(
                "demo",
                ["local:lecture_5_intro", "local:lecture_5_intro"],
                curriculum_root=root,
            )
        )
        _check("repeated source dedupes figures", names == ["lecture_5_a.png"], f"got {names}")


def test_discover_for_sources_empty_and_nonitem_sources() -> None:
    """Assert non-item sources and a missing figures dir yield []."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "lecture_5_a.png").write_bytes(b"\x89PNG\r\n")
        _check(
            "non-item sources -> []",
            discover_figures_for_sources("demo", ["local:key_concepts", ""], curriculum_root=root) == [],
        )
        _check(
            "empty source list -> []",
            discover_figures_for_sources("demo", [], curriculum_root=root) == [],
        )
        _check(
            "missing figures dir -> []",
            discover_figures_for_sources("no_such_course", ["local:lecture_1_x"], curriculum_root=root) == [],
        )


def test_discover_figures_ignores_non_exercise_kinds() -> None:
    """Assert exercise-only discover_figures never returns lecture/practice figures."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "exercise_5_ex.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_5_lec.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "practice_5_prac.png").write_bytes(b"\x89PNG\r\n")
        names = figure_filenames(discover_figures("demo", "5", curriculum_root=root))
        _check(
            "discover_figures stays exercise-only",
            names == ["exercise_5_ex.png"],
            f"got {names}",
        )
```

Add `discover_figures_for_sources` to the import block at the top of the file:

```python
from utils.figures import (
    build_multimodal_content,
    discover_figures,
    discover_figures_for_sources,
    figure_filenames,
    image_to_data_url,
    resolve_figure_filenames,
)
```

Register the four new tests in `main()`'s `tests` list (after `test_discovery_filters_and_isolates_by_exercise`):

```python
        test_discovery_filters_and_isolates_by_exercise,
        test_discover_for_sources_matches_lecture_and_practice,
        test_discover_for_sources_dedupes_repeated_sources,
        test_discover_for_sources_empty_and_nonitem_sources,
        test_discover_figures_ignores_non_exercise_kinds,
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m utils.test_figures`
Expected: FAIL — `ImportError: cannot import name 'discover_figures_for_sources'` (the new symbol doesn't exist yet).

- [ ] **Step 3: Implement the generalization in `utils/figures.py`**

Replace the module docstring's naming paragraph (lines 11-14) with:

```python
Naming convention (strict): ``<kind>_<id>_<slug>.<ext>`` where ``<kind>`` is one
of ``exercise``, ``lecture``, ``practice``; ``<id>`` is the non-padded number in
the sibling ``.txt`` stem; and ``<ext>`` is one of ``png``, ``jpg``, ``jpeg``
(case-insensitive). Multiple figures per item are allowed and returned sorted by
filename. A figure serves exactly one content item.
```

Replace the regex definition (line 25-26) with both the widened figure regex and a source-label regex:

```python
# <kind>_<id>_<slug>.<png|jpg|jpeg>; kind in exercise|lecture|practice; ext case-insensitive.
_FIGURE_NAME_RE = re.compile(
    r"^(exercise|lecture|practice)_(\d+)_.+\.(png|jpe?g)$", re.IGNORECASE
)

# Retrieved RAG chunk labels look like "local:lecture_5_intro" (or a bare
# "lecture_5_intro" stem). Captures (kind, id) for the item the chunk came from.
_SOURCE_ITEM_RE = re.compile(
    r"^(?:local:)?(exercise|lecture|practice)_(\d+)_", re.IGNORECASE
)
```

Update the match check inside `discover_figures` (lines 62-64) so it stays exercise-only under the widened regex — `group(1)` is now the kind, `group(2)` the number:

```python
        m = _FIGURE_NAME_RE.match(path.name)
        if m and m.group(1).lower() == "exercise" and m.group(2) == target:
            matches.append(path)
```

Add the new helper immediately after `discover_figures` (after line 65):

```python
def discover_figures_for_sources(
    course: str,
    sources,
    curriculum_root: Path | str | None = None,
) -> list[Path]:
    """Return figures for the content items named by retrieved RAG *sources*.

    Each source is a chunk label like ``local:lecture_5_intro`` (or a bare
    ``lecture_5_intro`` stem). For every source that names an exercise, lecture,
    or practice item, this returns the sibling figures under
    ``<course>/figures/`` whose ``<kind>_<id>_`` prefix matches. Deduplicated and
    sorted by filename; empty when nothing matches or the folder is absent.

    This is how per-turn lecture/practice figures are attached: a figure is sent
    to the model only on turns where its item's chunk was actually retrieved.
    Sources that don't name an item (e.g. ``local:key_concepts``) contribute
    nothing.
    """
    wanted: set[tuple[str, str]] = set()
    for source in sources or []:
        m = _SOURCE_ITEM_RE.match(str(source).strip())
        if m:
            wanted.add((m.group(1).lower(), m.group(2)))
    if not wanted:
        return []

    figures_dir = course_dir(course, curriculum_root) / "figures"
    if not figures_dir.is_dir():
        return []

    matches: list[Path] = []
    for path in figures_dir.iterdir():
        if not path.is_file():
            continue
        m = _FIGURE_NAME_RE.match(path.name)
        if m and (m.group(1).lower(), m.group(2)) in wanted:
            matches.append(path)
    return sorted(matches, key=lambda p: p.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m utils.test_figures`
Expected: PASS — all tests (the original 11 plus the 4 new ones) pass, `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add utils/figures.py utils/test_figures.py
git commit -m "feat(figures): generalize discovery to lectures and practices"
```

---

### Task 2: Attach per-turn retrieved figures through the tutor graph

**Files:**
- Modify: `tutor/run_tutor.py` (`TutorState` 107-116; `tutor_node` 208-224; `get_tutor_reply` 636-660)
- Modify: `internal_testing/run_transcript_rag.py` (import 68; `_tutor_reply_with_retry` 202-220; the retrieval+reply block 301-313)

**Interfaces:**
- Consumes: `discover_figures_for_sources(course, sources, curriculum_root=None) -> list[Path]` from Task 1; `build_multimodal_content` / `_attach_figures_to_last_human` (existing).
- Produces:
  - `TutorState.turn_figures: list` — optional per-turn figures folded into the last human message by `tutor_node`, unioned with the graph-bound exercise `figures`.
  - `get_tutor_reply(..., turn_figures: list | None = None)` — forwards `turn_figures` into the graph invoke.
  - `_tutor_reply_with_retry(tutor_messages, tutor_graph, rebuild, retrieved_context="", turn_figures=None)` — forwards `turn_figures`.

**Note on testing:** `tutor/run_tutor.py` has no standalone unit-test harness and `tutor_node` requires a live model, so this task is verified by a focused import-and-attach test using the graph's helper in isolation (no network) plus a manual smoke assertion. Do not attempt to invoke a real model.

- [ ] **Step 1: Write the failing test**

Create `tutor/test_turn_figures.py` (standalone harness, mirrors `utils/test_figures.py` style):

```python
"""Standalone test for per-turn figure attachment in the tutor graph.

Run with:
    python -m tutor.test_turn_figures

Verifies that the last human message gets the UNION of static (exercise) and
per-turn (retrieved) figures, deduped, without invoking any model.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tutor.run_tutor import _attach_figures_to_last_human

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_union_of_static_and_turn_figures_deduped() -> None:
    """Assert static + per-turn figures attach to the last human message, deduped, ordered."""
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
        HumanMessage(content="explain figure"),
    ]
    static = ["data:image/png;base64,AAA"]
    turn = ["data:image/png;base64,BBB", "data:image/png;base64,AAA"]  # BBB new, AAA dup
    merged = list(dict.fromkeys([*static, *turn]))
    _attach_figures_to_last_human(messages, merged)

    last = messages[-1]
    urls = [b["image_url"]["url"] for b in last.content if b.get("type") == "image_url"]
    _check(
        "static+turn union attaches once each, static first",
        urls == ["data:image/png;base64,AAA", "data:image/png;base64,BBB"],
        f"got {urls}",
    )
    _check("text block preserved", last.content[0] == {"type": "text", "text": "explain figure"})


def main() -> int:
    tests = [test_union_of_static_and_turn_figures_deduped]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m tutor.test_turn_figures`
Expected: PASS on the helper itself IF `_attach_figures_to_last_human` already handles a data-url list (it does). This test is a guard for the merge/dedup contract Step 3 relies on. If it fails, stop and fix the helper understanding before proceeding. (The real behavioral change is wiring in Steps 3-4, which this contract underpins.)

- [ ] **Step 3: Add `turn_figures` to the tutor graph state and node**

In `tutor/run_tutor.py`, extend `TutorState` (after `retrieved_context: str`, line 116) and update its docstring:

```python
class TutorState(TypedDict, total=False):
    """LangGraph state: the accumulated message list plus this turn's RAG context.

    ``retrieved_context`` (optional) is the per-turn RAG grounding folded into the
    system message by ``tutor_node``; absent/empty outside RAG mode.
    ``turn_figures`` (optional) are figures for items retrieved THIS turn (lecture/
    practice), attached to the latest student message in addition to the graph-bound
    exercise ``figures``; absent/empty outside RAG mode.
    """

    messages: Annotated[list, operator.add]
    retrieved_context: str
    turn_figures: list
```

In `tutor_node` (line 222-223), replace the static-only attach with a union of the graph-bound `figures` and per-turn `state["turn_figures"]`, deduped preserving order (exercise figures first):

```python
        turn_figures = state.get("turn_figures") or []
        all_figures = list(dict.fromkeys([*(figures or []), *turn_figures]))
        if all_figures:
            _attach_figures_to_last_human(messages, all_figures)
```

(`dict.fromkeys` dedupes `Path`/str items while keeping first-seen order. Since exercise figures and retrieved figures are distinct on-disk paths in practice, this is a safe no-op when they don't overlap.)

- [ ] **Step 4: Forward `turn_figures` through `get_tutor_reply`**

In `tutor/run_tutor.py`, update `get_tutor_reply` (signature at 636-644 and the invoke at 660):

```python
def get_tutor_reply(
    messages: list,
    assignment_override: str | None = None,
    *,
    graph=None,
    prompt_name: str = "tutor_01",
    figures: list | None = None,
    retrieved_context: str = "",
    turn_figures: list | None = None,
) -> tuple[list, str]:
```

Update the invoke line (660):

```python
    result = graph.invoke(
        {
            "messages": messages,
            "retrieved_context": retrieved_context,
            "turn_figures": turn_figures or [],
        }
    )
```

Add one line to the docstring (after the `retrieved_context` paragraph):

```python
    *turn_figures* are figures for items retrieved this turn (lecture/practice),
    attached alongside any graph-bound exercise figures.
```

- [ ] **Step 5: Compute and pass `turn_figures` in `run_transcript_rag.py`**

In `internal_testing/run_transcript_rag.py`, extend the import (line 68):

```python
from utils.figures import discover_figures, discover_figures_for_sources, figure_filenames  # noqa: E402
```

Update `_tutor_reply_with_retry` (202-220) to forward `turn_figures`:

```python
def _tutor_reply_with_retry(tutor_messages, tutor_graph, rebuild, retrieved_context="", turn_figures=None):
    """Call the tutor, retrying transient failures (rate limits, payload parse)
    with linear backoff. Rebuilds the graph between attempts in case client
    state is corrupted. *retrieved_context* is this turn's RAG grounding, folded
    into the system message by the tutor graph; *turn_figures* are figures for
    items retrieved this turn, attached to the student message."""
    last_error: Exception | None = None
    for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 1):
        try:
            return upstream_get_tutor_reply(
                tutor_messages,
                graph=tutor_graph,
                retrieved_context=retrieved_context,
                turn_figures=turn_figures or [],
            )
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < _TUTOR_CALL_MAX_RETRIES:
                time.sleep(2 * attempt)
                tutor_graph = rebuild()
                continue
    raise RuntimeError(f"Tutor call failed after {_TUTOR_CALL_MAX_RETRIES} attempts: {last_error}")
```

In the conversation loop, right after `rag_block` is computed (line 302) and before the `if is_stem:` branch, compute the per-turn figures from what was retrieved:

```python
        rag_block = f"{RETRIEVED_CONTEXT_HEADER}\n\n{rc.text}" if rc.text else ""
        # Lecture/practice figures ride in only on turns where their item's chunk
        # was retrieved (rc.records carry the source labels). Exercise figures are
        # already bound into the graph. STEM arm doesn't retrieve -> stays empty.
        turn_figures = discover_figures_for_sources(
            config.course, [r.get("source", "") for r in rc.records]
        )
        tutor_messages.append(HumanMessage(content=student_text))
```

Update the tutor-reply call in the `else` branch (311-313):

```python
            tutor_messages, tutor_text = _tutor_reply_with_retry(
                tutor_messages, tutor_graph, _build_graph,
                retrieved_context=rag_block, turn_figures=turn_figures,
            )
```

- [ ] **Step 6: Run the contract test + a byte-compile check**

Run: `python -m tutor.test_turn_figures`
Expected: PASS, `0 failed`.

Run: `python -m py_compile tutor/run_tutor.py internal_testing/run_transcript_rag.py`
Expected: no output (both modules compile).

- [ ] **Step 7: Commit**

```bash
git add tutor/run_tutor.py tutor/test_turn_figures.py internal_testing/run_transcript_rag.py
git commit -m "feat(tutor): attach retrieved lecture/practice figures per turn"
```

---

### Task 3: Persist and replay per-turn figures for the judge

**Files:**
- Modify: `internal_testing/run_transcript_rag.py` (judge-payload `figure_names`, 433-437)
- Modify: `eval/tutor_judge/run_judge.py` (import 26; figure reconstruction 718-726)

**Interfaces:**
- Consumes: `discover_figures_for_sources` (Task 1); `figure_filenames`, `resolve_figure_filenames` (existing); each exchange's `retrieved` list of `{"source", ...}` records.
- Produces: the transcript's top-level `figures` field now holds the union of exercise figures and every retrieved-item figure across the conversation; the judge resolves that union to paths (and also reconstructs from `exchanges` for older transcripts).

**Note on testing:** both files are runner scripts without a standalone harness and require model/network access to run end-to-end. Verify with a byte-compile plus a focused JSON round-trip test of the reconstruction logic extracted into a small inline test.

- [ ] **Step 1: Write the failing test**

Create `eval/tutor_judge/test_judge_figures.py`:

```python
"""Standalone test: judge reconstructs per-turn figures from transcript exchanges.

Run with:
    python -m eval.tutor_judge.test_judge_figures
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from utils.figures import discover_figures, discover_figures_for_sources, figure_filenames

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _figures_for_transcript(course, exercise_number, exchanges, curriculum_root=None):
    """Union of exercise figures + every retrieved-item figure across exchanges.

    Mirrors the judge/payload reconstruction: exercise figures first, then the
    lecture/practice figures for items retrieved on any turn, deduped by name.
    """
    names = figure_filenames(discover_figures(course, exercise_number, curriculum_root))
    sources = []
    for ex in exchanges or []:
        for rec in ex.get("retrieved") or []:
            sources.append(rec.get("source", ""))
    names += figure_filenames(discover_figures_for_sources(course, sources, curriculum_root))
    return list(dict.fromkeys(names))


def test_union_exercise_and_retrieved_figures() -> None:
    """Assert transcript figure union = exercise figures + retrieved lecture figures."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "exercise_5_ex.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_5_two_cities.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_6_other.png").write_bytes(b"\x89PNG\r\n")

        exchanges = [
            {"retrieved": [{"source": "local:lecture_5_intro"}, {"source": "local:key_concepts"}]},
            {"retrieved": [{"source": "local:lecture_5_intro"}]},  # dup across turns
        ]
        names = _figures_for_transcript("demo", "5", exchanges, curriculum_root=root)
        _check(
            "exercise first, then retrieved lecture, deduped; unretrieved lecture_6 absent",
            names == ["exercise_5_ex.png", "lecture_5_two_cities.png"],
            f"got {names}",
        )


def main() -> int:
    tests = [test_union_exercise_and_retrieved_figures]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the test to verify it passes as a contract**

Run: `python -m eval.tutor_judge.test_judge_figures`
Expected: PASS — this test exercises the Task-1 helpers directly and pins the exact union/order/dedup contract that Steps 3-4 must implement in the runner + judge. If it fails, fix the helper usage before wiring.

- [ ] **Step 3: Include retrieved-item figures in the persisted transcript payload**

In `internal_testing/run_transcript_rag.py`, replace the `figure_names` assignment in the judge-payload builder (lines 433-437) with the union of exercise figures and every retrieved-item figure across the conversation:

```python
    # Figures the tutor actually saw: the exercise's figures (bound into the
    # graph) plus every lecture/practice figure whose chunk was retrieved on any
    # turn. Persisted by filename so the judge replays the same images.
    figure_names = (
        figure_filenames(discover_figures(config.course, config.number))
        if config.kind == "exercise"
        else []
    )
    _retrieved_sources = [
        rec.get("source", "")
        for ex in exchanges
        for rec in (ex.get("retrieved") or [])
    ]
    figure_names = list(
        dict.fromkeys(
            figure_names
            + figure_filenames(discover_figures_for_sources(config.course, _retrieved_sources))
        )
    )
```

- [ ] **Step 4: Reconstruct retrieved-item figures in the judge**

In `eval/tutor_judge/run_judge.py`, extend the import (line 26):

```python
from utils.figures import (
    build_multimodal_content,
    discover_figures_for_sources,
    figure_filenames,
    resolve_figure_filenames,
)
```

Replace the figure-reconstruction block (lines 718-726) so the judge unions the persisted `figures` list with figures rebuilt from each exchange's `retrieved` sources (covers transcripts written before Task 3, and keeps the judge faithful regardless):

```python
    # Re-attach the images the tutor saw so the judge grades against them.
    # Two sources, unioned: the transcript's recorded ``figures`` (filenames) and
    # the lecture/practice figures for items retrieved on any turn (reconstructed
    # from each exchange's ``retrieved`` records). Absent/empty fields = none.
    course = _sanitize_text(transcript.get("course")).strip()
    figure_names: list[str] = []
    recorded = transcript.get("figures")
    if isinstance(recorded, list):
        figure_names.extend(str(n) for n in recorded)
    if course:
        retrieved_sources = [
            str(rec.get("source", ""))
            for ex in exchanges
            if isinstance(ex, dict)
            for rec in (ex.get("retrieved") or [])
        ]
        figure_names.extend(
            figure_filenames(discover_figures_for_sources(course, retrieved_sources))
        )
    figure_names = list(dict.fromkeys(figure_names))
    figures: list = (
        resolve_figure_filenames(course, figure_names) if (course and figure_names) else []
    )
```

- [ ] **Step 5: Verify tests + byte-compile**

Run: `python -m eval.tutor_judge.test_judge_figures`
Expected: PASS, `0 failed`.

Run: `python -m py_compile internal_testing/run_transcript_rag.py eval/tutor_judge/run_judge.py`
Expected: no output (both compile).

Run the full figures suite again to confirm no regressions:
Run: `python -m utils.test_figures`
Expected: PASS, `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add internal_testing/run_transcript_rag.py eval/tutor_judge/run_judge.py eval/tutor_judge/test_judge_figures.py
git commit -m "feat(judge): grade against per-turn retrieved figures"
```

---

## Self-Review

**Spec coverage:**
- §1 Naming convention → Task 1 (widened regex, docstring).
- §2 `utils/figures.py` (widen regex, keep `discover_figures`, add `discover_figures_for_sources`, docstring) → Task 1.
- §3 Per-turn wiring (`TutorState.turn_figures`, union in `tutor_node`, compute from `rc.records`) → Task 2.
- §4 Non-RAG paths unchanged → no code change; covered by leaving `full_context`/no-index paths untouched (they never set `turn_figures`).
- §5 Judge matches the tutor (union per-turn figures, persist + reconstruct) → Task 3.
- §6 Tests (lecture/practice discovery, exercise backward-compat, non-item sources, dedup/order) → Task 1 tests + Task 3 union test.
- Out-of-scope items (PDF rendering, image indexing, `figures.json`) → not implemented, as intended.

**Placeholder scan:** No TBD/TODO/"handle edge cases" — every step has concrete code and exact run commands.

**Type consistency:** `discover_figures_for_sources(course, sources, curriculum_root=None) -> list[Path]` is defined in Task 1 and consumed with that exact signature in Tasks 2 and 3. `turn_figures` is the consistent name across `TutorState`, `tutor_node`, `get_tutor_reply`, and `_tutor_reply_with_retry`. `figure_filenames` returns names (str); `resolve_figure_filenames` maps names→paths — used consistently.

**Note on the STEM arm:** it doesn't retrieve, so `rc.records` is empty and `turn_figures` is `[]` — verified by the empty-source test in Task 1.
