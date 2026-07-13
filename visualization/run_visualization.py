"""
Build transcript grading visualizations.

Reads judged transcripts from:
    transcripts/<persona_type>/<persona_type>_judge/transcript_*.json

Each run generates every configured chart (no prompts). Current charts:
    * Persona-type evaluation charts 01-06 (bar/heatmap/boxplot by persona
      and problem).
    * Score-distribution histogram across all graded transcripts (07).
    * Claude total score per transcript (08, plus one chart per persona family).

Usage:
    python -m visualization.run_visualization
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GradeRow:
    """Normalized grading row for one transcript, used by plotting routines."""

    tutor_prompt: str
    student_persona: str
    course: str
    exercise_number: str
    transcript_name: str
    total_score: float
    max_score: float
    kind: str = "?"  # "exercise" | "practice" | "?" — content kind for persona-type charts
    section_scores: dict[str, float] = field(default_factory=dict)
    section_maxes: dict[str, float] = field(default_factory=dict)
    subsection_scores: dict[str, float] = field(default_factory=dict)
    subsection_maxes: dict[str, float] = field(default_factory=dict)
    sub_subsection_scores: dict[str, float] = field(default_factory=dict)

    @property
    def persona_type(self) -> str:
        """Extract persona family prefix (e.g. 'chaotic') from the full persona identifier."""
        return (self.student_persona.split("_", 1)[0] or self.student_persona).strip()

    @property
    def transcript_key(self) -> str:
        """Composite key used to align GPT and Claude rows for the same conversation."""
        return "|".join([
            self.student_persona,
            self.course,
            self.exercise_number,
            self.transcript_name,
        ])


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _parse_score(x: Any) -> float:
    """Parse any value as a float score; returns NaN on failure."""
    try:
        return float(str(x or "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _extract_section_scores(grade: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Extract per-section (score, max) pairs from a grade dict; returns (scores_dict, maxes_dict)."""
    scores: dict[str, float] = {}
    maxes: dict[str, float] = {}
    sections = grade.get("sections")
    if not isinstance(sections, dict):
        return scores, maxes
    for sid, section in sections.items():
        if not isinstance(section, dict):
            continue
        base = section.get("base")
        if not isinstance(base, dict):
            continue
        scores[sid] = _parse_score(base.get("score"))
        maxes[sid] = _parse_score(base.get("max"))
    return scores, maxes


def _normalize_criterion_id(cid: str) -> str:
    """Normalize any criterion key to short ``X.Y`` dot-notation.

    Handles all observed model output variants:

    * ``'1.1'``                                    → ``'1.1'``  (already correct)
    * ``'1_1'``                                    → ``'1.1'``  (pure underscore)
    * ``'1.1_socratic_method_guided_discovery'``   → ``'1.1'``  (dot-prefix + description)
    * ``'1_1_socratic_method_guided_discovery'``   → ``'1.1'``  (underscore-prefix + description)

    Keys that do not start with a ``digit . digit`` or ``digit _ digit`` pattern
    (e.g. section keys like ``'1_pedagogy'``) are returned unchanged.
    """
    import re
    m = re.match(r"^(\d+)[._](\d+)", str(cid))
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return str(cid)


def _criterion_score_max(criterion: dict[str, Any]) -> tuple[Any, Any]:
    """Return (score, max) from a criterion dict, handling two schema variants.

    Schema A (newer runs): score nested under ``criterion["base"]``.
    Schema B (older runs): score directly in ``criterion`` as ``criterion["score"]``.
    Returns ``(None, None)`` when neither pattern is present.
    """
    if "score" in criterion or "max" in criterion:
        return criterion.get("score"), criterion.get("max")
    base = criterion.get("base")
    if isinstance(base, dict) and ("score" in base or "max" in base):
        return base.get("score"), base.get("max")
    return None, None


def _extract_subsection_scores(grade: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Extract per-subsection (criterion) score/max pairs from grade sections.

    Handles all three schema variants observed in the corpus:

    * Schema A – newer runs: criterion value is ``{"deductions": [...], "base": {"score": N, "max": M}}``
      with short ``X.Y`` keys (e.g. ``"1.1"``).
    * Schema B – older runs: criterion value is ``{"deductions": [...], "score": N, "max": M}``
      with full underscore keys (e.g. ``"1_1_socratic_method_..."``).
    * Missing criteria – only ``"deductions"`` and ``"base"`` keys present at the section level;
      these sections are skipped because there is nothing to extract at the subsection level.

    Both flat keys (criteria directly in the section dict) and nested keys (criteria under
    ``section["criteria"]``) are supported.
    """
    scores: dict[str, float] = {}
    maxes: dict[str, float] = {}
    sections = grade.get("sections")
    if not isinstance(sections, dict):
        return scores, maxes

    for _, section in sections.items():
        if not isinstance(section, dict):
            continue

        criteria = section.get("criteria")
        if isinstance(criteria, dict):
            for cid, criterion in criteria.items():
                if not isinstance(criterion, dict):
                    continue
                score, max_ = _criterion_score_max(criterion)
                if score is None and max_ is None:
                    continue
                normalized = _normalize_criterion_id(str(cid))
                scores[normalized] = _parse_score(score)
                maxes[normalized] = _parse_score(max_)
            continue

        # Flat shape: subsection ids are direct keys under the section object.
        for cid, criterion in section.items():
            if cid in {"base", "deductions", "criteria"}:
                continue
            if not isinstance(criterion, dict):
                continue
            score, max_ = _criterion_score_max(criterion)
            if score is None and max_ is None:
                continue
            normalized = _normalize_criterion_id(str(cid))
            scores[normalized] = _parse_score(score)
            maxes[normalized] = _parse_score(max_)
    return scores, maxes


def _extract_sub_subsection_scores(grade: dict[str, Any]) -> dict[str, float]:
    """Extract deepest-level rubric ids (e.g., 1.3.A.a) from deductions as aggregated point values."""
    scores: dict[str, float] = {}
    sections = grade.get("sections")
    if not isinstance(sections, dict):
        return scores

    for _, section in sections.items():
        if not isinstance(section, dict):
            continue
        criteria = section.get("criteria")
        if not isinstance(criteria, dict):
            continue
        for _, criterion in criteria.items():
            if not isinstance(criterion, dict):
                continue
            deductions = criterion.get("deductions")
            if not isinstance(deductions, list):
                continue
            for deduction in deductions:
                if not isinstance(deduction, dict):
                    continue
                sub_id = deduction.get("sub_criterion_id")
                if not isinstance(sub_id, str) or not sub_id.strip():
                    continue
                points = _parse_score(deduction.get("points"))
                if not math.isfinite(points):
                    continue
                scores[sub_id] = scores.get(sub_id, 0.0) + points
    return scores


def _read_judged_transcript(path: Path) -> GradeRow | None:
    """Load a single graded transcript JSON and return a GradeRow, or None if unreadable or ungraded."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    grade = raw.get("grade")
    if not isinstance(grade, dict):
        return None

    section_scores, section_maxes = _extract_section_scores(grade)
    subsection_scores, subsection_maxes = _extract_subsection_scores(grade)
    sub_subsection_scores = _extract_sub_subsection_scores(grade)

    return GradeRow(
        tutor_prompt=str(raw.get("tutor_prompt", "")).strip(),
        student_persona=str(raw.get("student_persona", "")).strip(),
        course=str(raw.get("course", "")).strip(),
        exercise_number=str(raw.get("exercise_number", "")).strip(),
        transcript_name=path.stem.strip(),
        total_score=_parse_score(grade.get("total_score")),
        max_score=_parse_score(grade.get("max_score")),
        # RAG transcripts store the kind under "exercise_kind"; older runs used
        # "kind". Fall back so exercise/practice charts work for both.
        kind=str(raw.get("kind") or raw.get("exercise_kind") or "?").strip(),
        section_scores=section_scores,
        section_maxes=section_maxes,
        subsection_scores=subsection_scores,
        subsection_maxes=subsection_maxes,
        sub_subsection_scores=sub_subsection_scores,
    )


def _read_judged_rows(transcripts_dir: Path) -> list[GradeRow]:
    """Scan all *_judge/transcript_*.json files and return GradeRow list."""
    rows: list[GradeRow] = []
    for path in sorted(transcripts_dir.glob("*/*_judge/transcript_*.json")):
        row = _read_judged_transcript(path)
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _sort_key(row: GradeRow) -> tuple:
    """Sorting key for GradeRow: by persona type, persona name, course, exercise number, transcript number."""
    tnum = int(row.transcript_name.split("_")[-1]) if "_" in row.transcript_name else 0
    ex_num = int(row.exercise_number) if row.exercise_number.isdigit() else 0
    return (row.persona_type, row.student_persona, row.course, ex_num, tnum)


def _safe_import_matplotlib():
    """Import matplotlib with the non-interactive Agg backend; raises RuntimeError with install hint if missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for visualization. "
            "Install with: python -m pip install matplotlib"
        ) from e
    return plt


def _filter_individual_rows(rows: list[GradeRow], allowed_personas: set[str]) -> list[GradeRow]:
    """Keep transcript rows whose persona family is included in *allowed_personas*."""
    allowed = {p.lower() for p in allowed_personas}
    return [r for r in rows if r.persona_type.lower() in allowed]


# ---------------------------------------------------------------------------
# Chart: Line chart — per-transcript total scores
# ---------------------------------------------------------------------------

def _chart_provider_total_scores_per_transcript(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    provider_label: str,
    scope_label: str,
    output_name: str,
    chart_idx: int,
) -> None:
    """Line chart of total scores for one judge provider over sorted transcript rows."""
    plt = _safe_import_matplotlib()
    from matplotlib.ticker import MaxNLocator

    if not rows:
        print(f"  [{chart_idx}] {output_name} (skipped: no rows)")
        return

    sorted_rows = sorted(rows, key=_sort_key)
    x = list(range(len(sorted_rows)))
    y = [r.total_score for r in sorted_rows]
    finite = [v for v in y if math.isfinite(v)]

    fig, ax = plt.subplots(figsize=(16, 7))
    color = "#ff893a" if provider_label.lower() == "claude" else "#a65dea"
    ax.plot(x, y, label=provider_label.upper(), color=color, linewidth=1.4, marker="o", markersize=2.5)
    ax.set_title(f"{provider_label.upper()} total score per transcript ({scope_label})")
    ax.set_xlabel("Transcript index (sorted by persona / course / exercise)")
    ax.set_ylabel("Total score")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    ax.legend()

    lines = [f"Transcripts: {len(sorted_rows)}"]
    if finite:
        lines.append(f"Mean: {sum(finite) / len(finite):.1f}")
    ax.text(
        0.01,
        0.98,
        "\n".join(lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    fig.savefig(out_dir / output_name, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {output_name}")


# ---------------------------------------------------------------------------
# Chart: Score distribution histogram (all transcripts)
# ---------------------------------------------------------------------------

def _chart_score_histogram(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    output_name: str,
    chart_idx: int,
) -> None:
    """Histogram of Claude total scores across all graded transcripts.

    Shades the "answer-giving penalty zone" — scores at or below (max - 12), the
    band a transcript lands in once it loses the full 12-point section-1.1 penalty
    for producing near-submission-ready work.
    """
    plt = _safe_import_matplotlib()

    scores = [r.total_score for r in rows if math.isfinite(r.total_score)]
    if not scores:
        print(f"  [{chart_idx}] {output_name} (skipped: no scores)")
        return

    max_score = max((r.max_score for r in rows if math.isfinite(r.max_score)), default=40.0)
    max_int = int(round(max_score))
    bins = [b - 0.5 for b in range(0, max_int + 2)]  # one integer-wide bin per possible score

    mean_v = sum(scores) / len(scores)
    median_v = sorted(scores)[len(scores) // 2]
    perfect = sum(1 for s in scores if s >= max_score)
    penalty_threshold = max_score - 12.0
    penalized = sum(1 for s in scores if s <= penalty_threshold)

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.hist(scores, bins=bins, color="#ff893a", alpha=0.85, edgecolor="white")
    ax.axvspan(-0.5, penalty_threshold + 0.5, color="#fb5c66", alpha=0.10)
    ax.axvline(mean_v, color="#1f77b4", linewidth=1.6, linestyle="--", label=f"mean = {mean_v:.1f}")
    ax.set_title(f"Distribution of Tutor Scores (Claude judge, n={len(scores)}, out of {max_int})")
    ax.set_xlabel(f"Total score (out of {max_int})")
    ax.set_ylabel("Number of conversations")
    ax.set_xlim(-0.5, max_score + 0.5)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper left")

    ax.text(
        penalty_threshold / 2, ax.get_ylim()[1] * 0.92, "answer-giving\npenalty zone",
        ha="center", va="top", fontsize=8, color="#b03a44",
    )

    lines = [
        f"Transcripts: {len(scores)}",
        f"Mean: {mean_v:.1f}   Median: {median_v:.0f}",
        f"Perfect ({max_int}/{max_int}): {perfect} ({100 * perfect / len(scores):.0f}%)",
        f"<= {int(penalty_threshold)} pts: {penalized} ({100 * penalized / len(scores):.1f}%)",
    ]
    ax.text(
        0.99, 0.98, "\n".join(lines), transform=ax.transAxes, ha="right", va="top",
        fontsize=9, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    fig.savefig(out_dir / output_name, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {output_name}")


# ---------------------------------------------------------------------------
# Persona-type evaluation charts (01-06)
#
# These summarize tutor quality by student persona type from the shared GradeRow
# model — the same rows the 07-11 charts use, so transcripts are read only once.
# The current corpus is the MIT CTL.SC2x run (3 exercises + 3 practices x 18
# personas, graded by judge_08/rubric_08).
# ---------------------------------------------------------------------------

# Persona types in a fixed display order, with stable colors.
_PERSONA_TYPES = ["cooperative", "chaotic", "clueless"]
_PERSONA_TYPE_COLOR = {"cooperative": "#2ca25f", "chaotic": "#ff893a", "clueless": "#3a7bd5"}
_RUBRIC_SECTIONS = [
    ("1_pedagogy", "Pedagogy"),
    ("2_dialogue_quality", "Dialogue"),
    ("3_communication_quality", "Communication"),
]


def _mean(xs) -> float:
    """Mean of an iterable, or 0.0 when empty."""
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _num(x: float) -> float:
    """Numerator value: the score if finite, else 0.0."""
    return x if math.isfinite(x) else 0.0


def _den(x: float) -> float:
    """Denominator value: the max if finite and positive, else 1.0 (avoids /0)."""
    return x if math.isfinite(x) and x > 0 else 1.0


def _chart_total_by_type(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """01: Mean total score by persona type (with spread)."""
    fig, ax = plt.subplots(figsize=(7, 5))
    means, stds = [], []
    for t in _PERSONA_TYPES:
        vals = [_num(r.total_score) for r in rows if r.persona_type == t]
        m = _mean(vals)
        means.append(m)
        stds.append((_mean([(v - m) ** 2 for v in vals])) ** 0.5)
    bars = ax.bar(_PERSONA_TYPES, means, yerr=stds, capsize=6,
                  color=[_PERSONA_TYPE_COLOR[t] for t in _PERSONA_TYPES])
    ax.set_ylim(0, 40)
    ax.set_ylabel("Mean total score (/40)")
    ax.set_title("Tutor score by student persona type (Claude judge, 36 convos each)")
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m + 0.6, f"{m:.1f}", ha="center", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_dir / "01_total_by_persona_type.png", dpi=150)
    plt.close(fig)


def _chart_sections_by_type(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """02: Rubric-section attainment (% of max) by persona type."""
    import numpy as np
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(_RUBRIC_SECTIONS))
    width = 0.26
    for i, t in enumerate(_PERSONA_TYPES):
        trows = [r for r in rows if r.persona_type == t]
        pct = [
            100
            * _mean([_num(r.section_scores.get(sid, float("nan"))) for r in trows])
            / _mean([_den(r.section_maxes.get(sid, float("nan"))) for r in trows])
            for sid, _ in _RUBRIC_SECTIONS
        ]
        ax.bar(x + (i - 1) * width, pct, width, label=t, color=_PERSONA_TYPE_COLOR[t])
    ax.set_xticks(x)
    ax.set_xticklabels([
        f"{lbl}\n(/{int(_den(rows[0].section_maxes.get(sid, float('nan'))))})"
        for sid, lbl in _RUBRIC_SECTIONS
    ])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Attainment (% of section max)")
    ax.set_title("Where the tutor loses points: rubric section by persona type")
    ax.legend(title="Persona", loc="lower left")
    ax.axhline(100, color="#999", lw=0.7, ls="--")
    fig.tight_layout()
    fig.savefig(out_dir / "02_sections_by_persona_type.png", dpi=150)
    plt.close(fig)


def _chart_kind_by_type(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """03: Exercise vs practice attainment by persona type."""
    import numpy as np
    fig, ax = plt.subplots(figsize=(8, 5))
    kinds = ["exercise", "practice"]
    x = np.arange(len(_PERSONA_TYPES))
    width = 0.36
    for i, k in enumerate(kinds):
        pct = []
        for t in _PERSONA_TYPES:
            krows = [r for r in rows if r.persona_type == t and r.kind == k]
            pct.append(
                100
                * _mean([_num(r.total_score) for r in krows])
                / _mean([_den(r.max_score) for r in krows])
            )
        ax.bar(x + (i - 0.5) * width, pct, width, label=k,
               color="#6a51a3" if k == "exercise" else "#e6a000")
    ax.set_xticks(x)
    ax.set_xticklabels(_PERSONA_TYPES)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Mean total attainment (% of 40)")
    ax.set_title("Exercises vs practice problems, by persona type")
    ax.legend(title="Content kind", loc="lower left")
    fig.tight_layout()
    fig.savefig(out_dir / "03_exercise_vs_practice.png", dpi=150)
    plt.close(fig)


def _chart_distribution(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """04: Total-score distribution by persona type (boxplot)."""
    fig, ax = plt.subplots(figsize=(7, 5))
    data = [[_num(r.total_score) for r in rows if r.persona_type == t] for t in _PERSONA_TYPES]
    bp = ax.boxplot(data, tick_labels=_PERSONA_TYPES, patch_artist=True, showmeans=True)
    for patch, t in zip(bp["boxes"], _PERSONA_TYPES):
        patch.set_facecolor(_PERSONA_TYPE_COLOR[t]); patch.set_alpha(0.6)
    ax.set_ylim(0, 40)
    ax.set_ylabel("Total score (/40)")
    ax.set_title("Score distribution by persona type")
    fig.tight_layout()
    fig.savefig(out_dir / "04_score_distribution.png", dpi=150)
    plt.close(fig)


def _chart_heatmap(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """05: Heatmap of persona type x rubric section (% of max)."""
    import numpy as np
    grid = np.zeros((len(_PERSONA_TYPES), len(_RUBRIC_SECTIONS)))
    for i, t in enumerate(_PERSONA_TYPES):
        trows = [r for r in rows if r.persona_type == t]
        for j, (sid, _) in enumerate(_RUBRIC_SECTIONS):
            grid[i, j] = (
                100
                * _mean([_num(r.section_scores.get(sid, float("nan"))) for r in trows])
                / _mean([_den(r.section_maxes.get(sid, float("nan"))) for r in trows])
            )
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    im = ax.imshow(grid, cmap="RdYlGn", vmin=60, vmax=100, aspect="auto")
    ax.set_xticks(range(len(_RUBRIC_SECTIONS))); ax.set_xticklabels([l for _, l in _RUBRIC_SECTIONS])
    ax.set_yticks(range(len(_PERSONA_TYPES))); ax.set_yticklabels(_PERSONA_TYPES)
    for i in range(len(_PERSONA_TYPES)):
        for j in range(len(_RUBRIC_SECTIONS)):
            ax.text(j, i, f"{grid[i, j]:.0f}%", ha="center", va="center", fontweight="bold")
    ax.set_title("Attainment heatmap: persona type x rubric section (% of max)")
    fig.colorbar(im, ax=ax, label="% of max")
    fig.tight_layout()
    fig.savefig(out_dir / "05_heatmap_type_x_section.png", dpi=150)
    plt.close(fig)


def _chart_by_problem(plt, rows: list[GradeRow], out_dir: Path) -> None:
    """06: Mean attainment by problem (exercise/practice 01..03)."""
    fig, ax = plt.subplots(figsize=(9, 5))
    labels, pcts, colors = [], [], []
    for kind, color in (("exercise", "#6a51a3"), ("practice", "#e6a000")):
        for n in ("01", "02", "03"):
            nrows = [r for r in rows if r.kind == kind and r.exercise_number == n]
            if not nrows:
                continue
            labels.append(f"{kind[:4]} {int(n)}")
            pcts.append(
                100
                * _mean([_num(r.total_score) for r in nrows])
                / _mean([_den(r.max_score) for r in nrows])
            )
            colors.append(color)
    bars = ax.bar(labels, pcts, color=colors)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Mean attainment (% of 40, across 18 personas)")
    ax.set_title("Tutor score by problem (Week 1-3 exercises and practice)")
    for b, p in zip(bars, pcts):
        ax.text(b.get_x() + b.get_width() / 2, p + 1, f"{p:.0f}%", ha="center")
    fig.tight_layout()
    fig.savefig(out_dir / "06_by_problem.png", dpi=150)
    plt.close(fig)


def _render_charts(rows: list[GradeRow], out_dir: Path) -> int:
    """Generate the six persona-type charts (01-06) into *out_dir* from graded rows.

    Returns the number of rows used (0 when empty, in which case nothing is
    written).
    """
    if not rows:
        return 0
    plt = _safe_import_matplotlib()
    _chart_total_by_type(plt, rows, out_dir)
    _chart_sections_by_type(plt, rows, out_dir)
    _chart_kind_by_type(plt, rows, out_dir)
    _chart_distribution(plt, rows, out_dir)
    _chart_heatmap(plt, rows, out_dir)
    _chart_by_problem(plt, rows, out_dir)
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: load judged transcripts and generate all configured charts."""
    import argparse

    parser = argparse.ArgumentParser(description="Transcript grading visualizations.")
    parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "transcripts"
    out_dir = repo_root / "visualization" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    claude_all_rows = _read_judged_rows(transcripts_dir)
    print(f"Loaded judged transcripts: {len(claude_all_rows)}")

    if not claude_all_rows:
        print(
            "No judged transcripts found under "
            "transcripts/<persona>/<persona>_judge/transcript_*.json. "
            "Run the judge first."
        )
        return 1

    # Persona-type evaluation charts (01-06), from the same rows.
    n_persona = _render_charts(claude_all_rows, out_dir)
    print(f"  [1-6] persona-type charts from {n_persona} graded transcripts")

    # Charts are numbered with a zero-padded ``##_`` prefix that continues after
    # the persona-type charts (01-06); start at 07 to avoid colliding with them.
    chart_idx = 7

    _chart_score_histogram(
        claude_all_rows,
        out_dir,
        output_name=f"{chart_idx:02d}_score_histogram_all.png",
        chart_idx=chart_idx,
    )
    chart_idx += 1

    _chart_provider_total_scores_per_transcript(
        claude_all_rows,
        out_dir,
        provider_label="claude",
        scope_label="all transcripts",
        output_name=f"{chart_idx:02d}_grades_all_transcripts.png",
        chart_idx=chart_idx,
    )
    chart_idx += 1

    persona_families = sorted({r.persona_type.lower() for r in claude_all_rows})
    for persona in persona_families:
        subset = _filter_individual_rows(claude_all_rows, {persona})
        if subset:
            _chart_provider_total_scores_per_transcript(
                subset,
                out_dir,
                provider_label="claude",
                scope_label=f"{persona} only",
                output_name=f"{chart_idx:02d}_grades_{persona}_transcripts.png",
                chart_idx=chart_idx,
            )
            chart_idx += 1

    print(f"\n[Done] Charts saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
