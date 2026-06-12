"""
Build transcript grading visualizations.

Reads judged transcripts from:
    transcripts/<persona_type>/<persona_type>_claude/transcript_*.json

Each run generates every configured chart (no prompts). Currently: Claude total
score per transcript (all transcripts, plus one chart per persona family).

Usage:
    python -m visualization.run_visualization
"""

from __future__ import annotations

import json
import math
import re
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Romain hand vs Claude chart: drop these workbook rows (persona type, transcript number).
ROMAIN_HAND_VS_CLAUDE_EXCLUDED: frozenset[tuple[str, int]] = frozenset(
    {("chaotic", 228), ("chaotic", 243)}
)


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


@dataclass(frozen=True)
class HandGradeRow:
    """Manual grade row from hand_grade_workbook.xlsx."""

    persona_type: str
    transcript_number: int
    grader_name: str
    total_score: float
    subsection_deductions: dict[str, float] = field(default_factory=dict)


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
        section_scores=section_scores,
        section_maxes=section_maxes,
        subsection_scores=subsection_scores,
        subsection_maxes=subsection_maxes,
        sub_subsection_scores=sub_subsection_scores,
    )


def _read_provider_rows_variant(transcripts_dir: Path, provider_suffix: str, folder_suffix: str = "") -> list[GradeRow]:
    """Scan all *_{provider_suffix}{folder_suffix}/transcript_*.json files and return GradeRow list."""
    rows: list[GradeRow] = []
    for path in sorted(transcripts_dir.glob(f"*/*_{provider_suffix}{folder_suffix}/transcript_*.json")):
        row = _read_judged_transcript(path)
        if row is not None:
            rows.append(row)
    return rows


def _read_provider_rows(transcripts_dir: Path, provider_suffix: str) -> list[GradeRow]:
    """Backward-compatible reader for non-v2 graded transcript folders."""
    return _read_provider_rows_variant(transcripts_dir, provider_suffix, "")


def _read_hand_grade_rows(xlsx_path: Path, *, grader_name: str) -> list[HandGradeRow]:
    """Read manual rows from Excel sheet and return only the requested grader's rows."""
    try:
        load_workbook = importlib.import_module("openpyxl").load_workbook
    except ModuleNotFoundError:
        return []

    try:
        wb = load_workbook(xlsx_path, data_only=False)
    except OSError:
        return []

    target = grader_name.strip().lower()
    preferred_sheet = f"{target} grading"
    if preferred_sheet in wb.sheetnames:
        ws = wb[preferred_sheet]
    elif "compiled grading" in wb.sheetnames:
        ws = wb["compiled grading"]
    else:
        return []
    if ws.max_row < 2:
        return []

    headers = [str(c.value or "").strip().lower() for c in ws[1]]
    try:
        idx_persona = headers.index("persona type")
        idx_transcript = headers.index("transcript number")
        idx_total = headers.index("total score")
    except ValueError:
        return []

    idx_grader = headers.index("grader name") if "grader name" in headers else None
    deduction_columns = [
        (i, h.upper())
        for i, h in enumerate(headers)
        if re.match(r"^\d+\.\d+\.[a-z]$", h)
    ]
    deduction_indices = [i for i, _ in deduction_columns]
    max_total_score = 40.0
    rows: list[HandGradeRow] = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        persona = str(r[idx_persona] or "").strip().lower()
        grader = target if idx_grader is None else str(r[idx_grader] or "").strip().lower()
        transcript_raw = r[idx_transcript]
        total = _parse_score(r[idx_total])
        if grader != target or not persona:
            continue
        try:
            transcript_num = int(transcript_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(total):
            deduction_sum = 0.0
            for didx in deduction_indices:
                d = _parse_score(r[didx])
                if math.isfinite(d):
                    deduction_sum += d
            total = max_total_score - deduction_sum
        subsection_deductions: dict[str, float] = {}
        for didx, sid in deduction_columns:
            d = _parse_score(r[didx])
            subsection_deductions[sid] = d if math.isfinite(d) else 0.0
        rows.append(
            HandGradeRow(
                persona_type=persona,
                transcript_number=transcript_num,
                grader_name=grader,
                total_score=total,
                subsection_deductions=subsection_deductions,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _sort_key(row: GradeRow) -> tuple:
    """Sorting key for GradeRow: by persona type, persona name, course, exercise number, transcript number."""
    tnum = int(row.transcript_name.split("_")[-1]) if "_" in row.transcript_name else 0
    ex_num = int(row.exercise_number) if row.exercise_number.isdigit() else 0
    return (row.persona_type, row.student_persona, row.course, ex_num, tnum)


def _transcript_num(row: GradeRow) -> int:
    """Extract numeric suffix from transcript_name like transcript_17."""
    if "_" in row.transcript_name:
        try:
            return int(row.transcript_name.split("_")[-1])
        except ValueError:
            return 0
    return 0


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson r for paired lists; returns None if fewer than 2 pairs."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    d = math.sqrt(vx * vy)
    return cov / d if d else None


def _avg_ranks(values: list[float]) -> list[float]:
    """Assign average ranks to a list of values, handling ties by averaging tied positions."""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda iv: iv[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = ((i + 1) + (j + 1)) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Compute Spearman rho as Pearson r of the rank lists; returns None if fewer than 2 pairs."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return _pearson(_avg_ranks(xs), _avg_ranks(ys))


def _pearson_finite_pairs(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation computed only on finite paired values."""
    paired_x: list[float] = []
    paired_y: list[float] = []
    for x, y in zip(xs, ys):
        if math.isfinite(x) and math.isfinite(y):
            paired_x.append(x)
            paired_y.append(y)
    return _pearson(paired_x, paired_y)


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
# Chart: Line chart — individual transcript scores
# ---------------------------------------------------------------------------

def _chart_line_scores(
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    persona_label: str,
    output_name: str,
    chart_idx: int,
) -> None:
    """Generate a line chart comparing GPT vs Claude total scores for individual transcripts, including Pearson r and Spearman rho annotations."""
    plt = _safe_import_matplotlib()

    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}
    all_keys = sorted(
        set(gpt_by_key) | set(claude_by_key),
        key=lambda k: _sort_key(gpt_by_key.get(k) or claude_by_key[k]),
    )

    x = list(range(len(all_keys)))
    y_gpt = [gpt_by_key[k].total_score if k in gpt_by_key else float("nan") for k in all_keys]
    y_claude = [claude_by_key[k].total_score if k in claude_by_key else float("nan") for k in all_keys]

    paired_g, paired_c = [], []
    for k in all_keys:
        g, c = gpt_by_key.get(k), claude_by_key.get(k)
        if g and c and math.isfinite(g.total_score) and math.isfinite(c.total_score):
            paired_g.append(g.total_score)
            paired_c.append(c.total_score)

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.4, marker="o", markersize=2.5)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.4, marker="o", markersize=2.5)
    ax.set_title(f"Total Score Per Transcript ({persona_label}): GPT vs Claude")
    ax.set_xlabel("Transcript index (sorted by persona / course / exercise)")
    ax.set_ylabel("Total Score")
    ax.grid(True, alpha=0.3)
    ax.legend()

    pearson_v = _pearson(paired_g, paired_c)
    spearman_v = _spearman(paired_g, paired_c)
    lines = []
    lines.append(f"Pearson r = {pearson_v:.3f}" if pearson_v is not None else "Pearson r = N/A")
    lines.append(f"Spearman ρ = {spearman_v:.3f}" if spearman_v is not None else "Spearman ρ = N/A")
    lines.append(f"Paired transcripts: {len(paired_g)}")
    if paired_g:
        lines.append(f"GPT mean: {sum(paired_g)/len(paired_g):.1f}   Claude mean: {sum(paired_c)/len(paired_c):.1f}")
    ax.text(
        0.01, 0.98, "\n".join(lines), transform=ax.transAxes, ha="left", va="top",
        fontsize=9, bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#ccc"},
    )

    fig.tight_layout()
    fig.savefig(out_dir / output_name, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {output_name}")


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


def _chart_hand_grader_vs_claude(
    hand_rows: list[HandGradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    grader_label: str,
    output_name: str,
    chart_idx: int,
) -> None:
    """Line chart: hand total score vs Claude total score on exact (persona type, transcript number) matches."""
    plt = _safe_import_matplotlib()
    from matplotlib.ticker import MaxNLocator

    hand_by_key: dict[tuple[str, int], HandGradeRow] = {}
    for r in hand_rows:
        hand_by_key[(r.persona_type.lower(), r.transcript_number)] = r

    claude_by_key: dict[tuple[str, int], GradeRow] = {}
    for r in claude_rows:
        claude_by_key[(r.persona_type.lower(), _transcript_num(r))] = r

    matched_keys = sorted(
        set(hand_by_key).intersection(set(claude_by_key)),
        key=lambda k: (k[0], k[1]),
    )
    if not matched_keys:
        print(f"  [{chart_idx}] {output_name} (skipped: no hand/Claude transcript overlap)")
        return

    x = list(range(len(matched_keys)))
    y_hand = [hand_by_key[k].total_score for k in matched_keys]
    y_claude = [claude_by_key[k].total_score for k in matched_keys]

    paired_h: list[float] = []
    paired_c: list[float] = []
    for k in matched_keys:
        h, c = hand_by_key[k].total_score, claude_by_key[k].total_score
        if math.isfinite(h) and math.isfinite(c):
            paired_h.append(h)
            paired_c.append(c)

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_hand, label=f"{grader_label} (hand)", color="#2ca02c", linewidth=1.4, marker="o", markersize=2.5)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.4, marker="o", markersize=2.5)
    ax.set_title(f"{grader_label} vs Claude — total score (matched transcripts)")
    ax.set_xlabel("Matched transcript index (sorted by persona type, transcript number)")
    ax.set_ylabel("Total score")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    ax.legend()

    pearson_v = _pearson(paired_h, paired_c)
    spearman_v = _spearman(paired_h, paired_c)
    lines = [
        f"Paired transcripts: {len(paired_h)}",
        f"Pearson Correlation = {pearson_v:.3f}" if pearson_v is not None else "Pearson Correlation = N/A",
        f"Spearman ρ = {spearman_v:.3f}" if spearman_v is not None else "Spearman ρ = N/A",
    ]
    if paired_h:
        lines.append(
            f"{grader_label} mean: {sum(paired_h) / len(paired_h):.1f}   "
            f"Claude mean: {sum(paired_c) / len(paired_c):.1f}"
        )
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


def _chart_faizan_vs_gpt_vs_claude(
    faizan_rows: list[HandGradeRow],
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    output_name: str,
    chart_idx: int,
) -> None:
    """Generate line chart for Faizan manual grades vs GPT and Claude on exact transcript matches."""
    plt = _safe_import_matplotlib()
    from matplotlib.ticker import MaxNLocator

    faizan_by_key: dict[tuple[str, int], HandGradeRow] = {}
    for r in faizan_rows:
        faizan_by_key[(r.persona_type.lower(), r.transcript_number)] = r

    gpt_by_key: dict[tuple[str, int], GradeRow] = {}
    for r in gpt_rows:
        gpt_by_key[(r.persona_type.lower(), _transcript_num(r))] = r

    claude_by_key: dict[tuple[str, int], GradeRow] = {}
    for r in claude_rows:
        claude_by_key[(r.persona_type.lower(), _transcript_num(r))] = r

    matched_keys = sorted(
        set(faizan_by_key).intersection(set(gpt_by_key)).intersection(set(claude_by_key)),
        key=lambda k: (k[0], k[1]),
    )
    if not matched_keys:
        print(f"  [{chart_idx}] {output_name} (skipped: no exact Faizan/GPT/Claude transcript overlap)")
        return

    # Omit transcripts where Faizan gave a perfect score.
    faizan_scores_all = [faizan_by_key[k].total_score for k in matched_keys if math.isfinite(faizan_by_key[k].total_score)]
    if not faizan_scores_all:
        print(f"  [{chart_idx}] {output_name} (skipped: Faizan scores are missing/non-finite)")
        return
    perfect_score = max(faizan_scores_all)
    filtered_keys = [k for k in matched_keys if faizan_by_key[k].total_score < perfect_score]
    removed_count = len(matched_keys) - len(filtered_keys)
    if not filtered_keys:
        print(f"  [{chart_idx}] {output_name} (skipped: all matched transcripts have Faizan perfect score={perfect_score:g})")
        return

    x = list(range(len(filtered_keys)))
    y_faizan = [faizan_by_key[k].total_score for k in filtered_keys]
    y_gpt = [gpt_by_key[k].total_score for k in filtered_keys]
    y_claude = [claude_by_key[k].total_score for k in filtered_keys]

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_faizan, label="Faizan (hand grade)", color="#2ca02c", linewidth=1.6, marker="o", markersize=3)
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.4, marker="o", markersize=2.5)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.4, marker="o", markersize=2.5)
    ax.set_title("Exact Transcript Comparison: Faizan vs GPT vs Claude (excluding Faizan perfect scores)")
    ax.set_xlabel("Matched transcript index (sorted by persona, transcript number)")
    ax.set_ylabel("Total Score")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    ax.legend()

    p_faizan_gpt = _pearson(y_faizan, y_gpt)
    p_faizan_claude = _pearson(y_faizan, y_claude)
    s_faizan_gpt = _spearman(y_faizan, y_gpt)
    s_faizan_claude = _spearman(y_faizan, y_claude)
    lines = [
        f"Matched transcripts: {len(filtered_keys)} (removed perfect={removed_count}, score={perfect_score:g})",
        f"Faizan↔GPT Pearson r = {p_faizan_gpt:.3f}" if p_faizan_gpt is not None else "Faizan↔GPT Pearson r = N/A",
        f"Faizan↔Claude Pearson r = {p_faizan_claude:.3f}" if p_faizan_claude is not None else "Faizan↔Claude Pearson r = N/A",
        f"Faizan↔GPT Spearman ρ = {s_faizan_gpt:.3f}" if s_faizan_gpt is not None else "Faizan↔GPT Spearman ρ = N/A",
        f"Faizan↔Claude Spearman ρ = {s_faizan_claude:.3f}" if s_faizan_claude is not None else "Faizan↔Claude Spearman ρ = N/A",
        f"Means — Faizan: {sum(y_faizan)/len(y_faizan):.1f}, GPT: {sum(y_gpt)/len(y_gpt):.1f}, Claude: {sum(y_claude)/len(y_claude):.1f}",
    ]
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


def _level3_sort_key(sid: str) -> tuple[int, int, str]:
    """Sort ids like 1.3.A by numeric prefix then lexical suffix."""
    parts = sid.split(".")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]), parts[2])
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]), "")
    return (999, 999, sid)


def _collapse_deep_deductions_to_level3(scores: dict[str, float]) -> dict[str, float]:
    """Collapse deep ids like 1.3.A.a to level-3 ids like 1.3.A."""
    out: dict[str, float] = {}
    for sid, val in scores.items():
        sid3 = _to_level3_subsection_id(sid)
        if sid3 is None or not math.isfinite(val):
            continue
        out[sid3] = out.get(sid3, 0.0) + val
    return out


def _chart_faizan_vs_claude_subsection_heatmap(
    faizan_rows: list[HandGradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    output_name: str,
    chart_idx: int,
) -> None:
    """Heatmap of cross-correlation: Faizan subsection deductions vs Claude subsection deductions (X.X.X)."""
    plt = _safe_import_matplotlib()

    faizan_by_key = {(r.persona_type.lower(), r.transcript_number): r for r in faizan_rows}
    claude_by_key = {(r.persona_type.lower(), _transcript_num(r)): r for r in claude_rows}
    matched_keys = sorted(
        set(faizan_by_key).intersection(set(claude_by_key)),
        key=lambda k: (k[0], k[1]),
    )
    if len(matched_keys) < 2:
        print(f"  [{chart_idx}] {output_name} (skipped: not enough matched transcripts)")
        return

    # Exclude transcripts where Faizan assigned a perfect total score.
    faizan_scores = [faizan_by_key[k].total_score for k in matched_keys if math.isfinite(faizan_by_key[k].total_score)]
    if not faizan_scores:
        print(f"  [{chart_idx}] {output_name} (skipped: Faizan scores missing/non-finite)")
        return
    perfect_score = max(faizan_scores)
    filtered_keys = [k for k in matched_keys if faizan_by_key[k].total_score < perfect_score]
    removed_count = len(matched_keys) - len(filtered_keys)
    if len(filtered_keys) < 2:
        print(
            f"  [{chart_idx}] {output_name} "
            f"(skipped: too few transcripts after removing perfect Faizan scores={perfect_score:g})"
        )
        return

    claude_level3_by_key: dict[tuple[str, int], dict[str, float]] = {}
    for key in filtered_keys:
        claude_level3_by_key[key] = _collapse_deep_deductions_to_level3(claude_by_key[key].sub_subsection_scores)

    faizan_ids = sorted(
        set(sid for key in filtered_keys for sid in faizan_by_key[key].subsection_deductions.keys()),
        key=_level3_sort_key,
    )
    claude_ids = sorted(
        set(sid for key in filtered_keys for sid in claude_level3_by_key[key].keys()),
        key=_level3_sort_key,
    )
    axis_ids = sorted(set(faizan_ids).union(set(claude_ids)), key=_level3_sort_key)
    if not axis_ids:
        print(f"  [{chart_idx}] {output_name} (skipped: missing subsection deductions)")
        return

    faizan_series = {
        sid: [faizan_by_key[k].subsection_deductions.get(sid, 0.0) for k in filtered_keys]
        for sid in axis_ids
    }
    claude_series = {
        sid: [claude_level3_by_key[k].get(sid, 0.0) for k in filtered_keys]
        for sid in axis_ids
    }

    corr_matrix: list[list[float]] = []
    for sid_f in axis_ids:
        row: list[float] = []
        for sid_c in axis_ids:
            c = _pearson(faizan_series[sid_f], claude_series[sid_c])
            row.append(c if c is not None else float("nan"))
        corr_matrix.append(row)

    fig, ax = plt.subplots(figsize=(11, 8))
    im = ax.imshow(corr_matrix, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_title(
        "Faizan vs Claude Subsection Deduction Correlation Heatmap (X.X.X)\n"
        f"Regular Claude grading only | n={len(filtered_keys)} "
        f"(removed perfect={removed_count}, score={perfect_score:g})"
    )
    ax.set_xlabel("Claude subsection id")
    ax.set_ylabel("Faizan subsection id")
    ax.set_xticks(list(range(len(axis_ids))))
    ax.set_yticks(list(range(len(axis_ids))))
    ax.set_xticklabels(axis_ids, rotation=45, ha="right")
    ax.set_yticklabels(axis_ids)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Pearson correlation")
    fig.tight_layout()
    fig.savefig(out_dir / output_name, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {output_name}")


# ---------------------------------------------------------------------------
# Chart: Provider self-consistency across repeated runs
# ---------------------------------------------------------------------------

def _chart_provider_self_consistency(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    provider_label: str,
    chart_idx: int,
) -> None:
    """Heatmap of run-vs-run score correlation for repeated runs within one provider."""
    plt = _safe_import_matplotlib()

    grouped: dict[tuple[str, str, str], list[GradeRow]] = {}
    for row in rows:
        key = (row.student_persona, row.course, row.exercise_number)
        grouped.setdefault(key, []).append(row)

    if not grouped:
        print(f"  [{chart_idx}] self_consistency_{provider_label.lower()}_run_correlation.png (skipped: no rows)")
        return

    for key in grouped:
        grouped[key] = sorted(grouped[key], key=_transcript_num)

    max_runs = max(len(v) for v in grouped.values())
    if max_runs < 2:
        print(
            f"  [{chart_idx}] self_consistency_{provider_label.lower()}_run_correlation.png "
            "(skipped: fewer than 2 runs per setup)"
        )
        return

    run_vectors: list[list[float]] = [[] for _ in range(max_runs)]
    for rows_for_key in grouped.values():
        for idx in range(max_runs):
            if idx < len(rows_for_key):
                run_vectors[idx].append(rows_for_key[idx].total_score)
            else:
                run_vectors[idx].append(float("nan"))

    corr_matrix: list[list[float]] = [[float("nan")] * max_runs for _ in range(max_runs)]
    n_matrix: list[list[int]] = [[0] * max_runs for _ in range(max_runs)]

    for i in range(max_runs):
        for j in range(max_runs):
            if i == j:
                corr_matrix[i][j] = 1.0
                n_matrix[i][j] = len([v for v in run_vectors[i] if math.isfinite(v)])
                continue
            xs, ys = run_vectors[i], run_vectors[j]
            paired_x, paired_y = [], []
            for x, y in zip(xs, ys):
                if math.isfinite(x) and math.isfinite(y):
                    paired_x.append(x)
                    paired_y.append(y)
            n_matrix[i][j] = len(paired_x)
            corr = _pearson(paired_x, paired_y)
            corr_matrix[i][j] = corr if corr is not None else float("nan")

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr_matrix, cmap="coolwarm", vmin=-1, vmax=1)
    labels = [f"run_{i+1}" for i in range(max_runs)]
    ax.set_xticks(list(range(max_runs)))
    ax.set_yticks(list(range(max_runs)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_title(f"{provider_label} vs Itself: Run Correlation Heatmap")
    ax.set_xlabel("Run index within same setup")
    ax.set_ylabel("Run index within same setup")

    for i in range(max_runs):
        for j in range(max_runs):
            c = corr_matrix[i][j]
            n = n_matrix[i][j]
            text = f"{c:.2f}\nn={n}" if math.isfinite(c) else f"N/A\nn={n}"
            ax.text(j, i, text, ha="center", va="center", fontsize=8)

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Pearson correlation")
    fig.tight_layout()
    filename = f"self_consistency_{provider_label.lower()}_run_correlation.png"
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


# ---------------------------------------------------------------------------
# Chart: Bar chart — rubric section discrepancies (individual transcripts)
# ---------------------------------------------------------------------------

def _chart_section_discrepancies(
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    chart_idx: int,
    output_name: str = "section_discrepancy_by_rubric_section_gpt_vs_claude.png",
) -> None:
    """Generate a bar chart of mean absolute section-score differences (GPT vs Claude)."""
    plt = _safe_import_matplotlib()

    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}
    paired_keys = sorted(set(gpt_by_key).intersection(set(claude_by_key)))

    # section_id -> {"abs_sum": float, "signed_sum": float, "count": int}
    stats: dict[str, dict[str, float]] = {}

    for key in paired_keys:
        g = gpt_by_key[key]
        c = claude_by_key[key]
        section_ids = set(g.section_scores.keys()).intersection(set(c.section_scores.keys()))
        for sid in section_ids:
            g_score = g.section_scores.get(sid, float("nan"))
            c_score = c.section_scores.get(sid, float("nan"))
            if not math.isfinite(g_score) or not math.isfinite(c_score):
                continue
            d = g_score - c_score
            if sid not in stats:
                stats[sid] = {"abs_sum": 0.0, "signed_sum": 0.0, "count": 0.0}
            stats[sid]["abs_sum"] += abs(d)
            stats[sid]["signed_sum"] += d
            stats[sid]["count"] += 1.0

    if not stats:
        print(f"  [{chart_idx}] {output_name} (skipped: no section data)")
        return

    def _section_sort_key(sid: str) -> tuple[int, str]:
        """Sort section ids by numeric prefix when available (e.g. ``1_*`` before ``2_*``)."""

        prefix = sid.split("_", 1)[0]
        try:
            return (int(prefix), sid)
        except ValueError:
            return (999, sid)

    section_ids_sorted = sorted(stats.keys(), key=_section_sort_key)
    mean_abs = [stats[sid]["abs_sum"] / stats[sid]["count"] for sid in section_ids_sorted]
    mean_signed = [stats[sid]["signed_sum"] / stats[sid]["count"] for sid in section_ids_sorted]
    counts = [int(stats[sid]["count"]) for sid in section_ids_sorted]

    x = list(range(len(section_ids_sorted)))
    fig, ax = plt.subplots(figsize=(12, 7))
    bars = ax.bar(x, mean_abs, color="#6f42c1", alpha=0.8)
    ax.set_title("Rubric Section Discrepancy (GPT vs Claude)")
    ax.set_xlabel("Rubric Section")
    ax.set_ylabel("Mean Absolute Score Difference")
    ax.set_xticks(x)
    ax.set_xticklabels(section_ids_sorted)
    ax.grid(True, axis="y", alpha=0.3)

    # Add compact annotations per section: n and signed direction.
    for i, bar in enumerate(bars):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"n={counts[i]}\nΔ={mean_signed[i]:+.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    fig.tight_layout()
    filename = output_name
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


# ---------------------------------------------------------------------------
# Charts: Subsection discrepancies (individual transcripts)
# ---------------------------------------------------------------------------

def _subsection_sort_key(cid: str) -> tuple[int, int, str]:
    """Sort subsection ids like '1.2' numerically; unknown patterns go last."""
    parts = cid.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]), cid)
    if len(parts) >= 1 and parts[0].isdigit():
        return (int(parts[0]), 999, cid)
    return (999, 999, cid)


def _chart_subsection_discrepancies(
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    chart_idx: int,
    output_name: str = "subsection_discrepancy_by_subsection_gpt_vs_claude.png",
) -> None:
    """Generate a bar chart of mean absolute subsection-score differences (GPT vs Claude)."""
    plt = _safe_import_matplotlib()

    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}
    paired_keys = sorted(set(gpt_by_key).intersection(set(claude_by_key)))

    # subsection_id -> {"abs_sum": float, "signed_sum": float, "count": int}
    stats: dict[str, dict[str, float]] = {}

    for key in paired_keys:
        g = gpt_by_key[key]
        c = claude_by_key[key]
        subsection_ids = set(g.subsection_scores.keys()).intersection(set(c.subsection_scores.keys()))
        for cid in subsection_ids:
            g_score = g.subsection_scores.get(cid, float("nan"))
            c_score = c.subsection_scores.get(cid, float("nan"))
            if not math.isfinite(g_score) or not math.isfinite(c_score):
                continue
            d = g_score - c_score
            if cid not in stats:
                stats[cid] = {"abs_sum": 0.0, "signed_sum": 0.0, "count": 0.0}
            stats[cid]["abs_sum"] += abs(d)
            stats[cid]["signed_sum"] += d
            stats[cid]["count"] += 1.0

    if not stats:
        print(f"  [{chart_idx}] {output_name} (skipped: no subsection data)")
        return

    subsection_ids_sorted = sorted(stats.keys(), key=_subsection_sort_key)
    mean_abs = [stats[cid]["abs_sum"] / stats[cid]["count"] for cid in subsection_ids_sorted]
    mean_signed = [stats[cid]["signed_sum"] / stats[cid]["count"] for cid in subsection_ids_sorted]
    counts = [int(stats[cid]["count"]) for cid in subsection_ids_sorted]

    x = list(range(len(subsection_ids_sorted)))
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(x, mean_abs, color="#2f7ed8", alpha=0.85)
    ax.set_title("Subsection Discrepancy (GPT vs Claude)")
    ax.set_xlabel("Rubric Subsection")
    ax.set_ylabel("Mean Absolute Score Difference")
    ax.set_xticks(x)
    ax.set_xticklabels(subsection_ids_sorted)
    ax.grid(True, axis="y", alpha=0.3)

    for i, bar in enumerate(bars):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"n={counts[i]}\nΔ={mean_signed[i]:+.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    fig.tight_layout()
    filename = output_name
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


def _chart_subsection_discrepancy_per_transcript(
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
    *,
    chart_idx: int,
) -> None:
    """Generate a multi-line chart of per-subsection absolute discrepancy per paired transcript."""
    plt = _safe_import_matplotlib()

    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}
    paired_keys = sorted(
        set(gpt_by_key).intersection(set(claude_by_key)),
        key=lambda k: _sort_key(gpt_by_key[k]),
    )

    subsection_ids = sorted(
        set(cid for row in gpt_rows for cid in row.subsection_scores.keys()).intersection(
            set(cid for row in claude_rows for cid in row.subsection_scores.keys())
        ),
        key=_subsection_sort_key,
    )

    if not subsection_ids or not paired_keys:
        print(f"  [{chart_idx}] subsection_discrepancy_per_transcript_gpt_vs_claude.png (skipped: no paired transcript data)")
        return

    x = list(range(len(paired_keys)))
    series_by_subsection: dict[str, list[float]] = {}
    for cid in subsection_ids:
        y_vals: list[float] = []
        for key in paired_keys:
            g = gpt_by_key[key]
            c = claude_by_key[key]
            g_score = g.subsection_scores.get(cid, float("nan"))
            c_score = c.subsection_scores.get(cid, float("nan"))
            if math.isfinite(g_score) and math.isfinite(c_score):
                y_vals.append(abs(g_score - c_score))
            else:
                y_vals.append(float("nan"))
        series_by_subsection[cid] = y_vals

    fig, ax = plt.subplots(figsize=(16, 7))
    for cid in subsection_ids:
        ax.plot(
            x,
            series_by_subsection[cid],
            linewidth=1.2,
            marker="o",
            markersize=2.0,
            label=cid,
        )
    ax.set_title("Subsection Discrepancy Per Transcript (GPT vs Claude)")
    ax.set_xlabel("Paired transcript index")
    ax.set_ylabel("Absolute Subsection Score Difference")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Subsection", ncol=4, fontsize=8, title_fontsize=9)

    fig.tight_layout()
    filename = "subsection_discrepancy_per_transcript_gpt_vs_claude.png"
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


# ---------------------------------------------------------------------------
# Charts: Subsection correlation heatmaps (normalized scores)
# ---------------------------------------------------------------------------

def _normalized_subsection_scores(row: GradeRow) -> dict[str, float]:
    """Return subsection normalized scores (score/max) for valid finite max > 0 entries."""
    values: dict[str, float] = {}
    for cid, score in row.subsection_scores.items():
        max_v = row.subsection_maxes.get(cid, float("nan"))
        if not math.isfinite(score) or not math.isfinite(max_v) or max_v <= 0:
            continue
        values[cid] = score / max_v
    return values


def _chart_subsection_correlation_heatmap(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    provider_label: str,
    persona_label: str,
    chart_idx: int,
    output_name: str | None = None,
) -> None:
    """Generate subsection-pair correlation heatmap on normalized subsection scores."""
    plt = _safe_import_matplotlib()

    normalized_rows = [_normalized_subsection_scores(r) for r in rows]
    subsection_ids = sorted(
        set(cid for values in normalized_rows for cid in values.keys()),
        key=_subsection_sort_key,
    )
    if len(subsection_ids) < 2:
        fallback_name = output_name or f"subsection_correlation_heatmap_{provider_label.lower()}_{persona_label}_normalized.png"
        print(
            f"  [{chart_idx}] {fallback_name} "
            "(skipped: insufficient subsection coverage)"
        )
        return

    # Build value vectors per subsection across transcripts; missing values become NaN.
    series: dict[str, list[float]] = {}
    hits: dict[str, int] = {}
    for cid in subsection_ids:
        vals: list[float] = []
        hit_count = 0
        for values in normalized_rows:
            v = values.get(cid, float("nan"))
            if math.isfinite(v):
                hit_count += 1
            vals.append(v)
        series[cid] = vals
        hits[cid] = hit_count

    n = len(subsection_ids)
    corr_matrix: list[list[float]] = [[float("nan")] * n for _ in range(n)]
    for i, cid_i in enumerate(subsection_ids):
        for j, cid_j in enumerate(subsection_ids):
            if i == j:
                corr_matrix[i][j] = 1.0
            elif j < i:
                corr_matrix[i][j] = corr_matrix[j][i]
            else:
                corr = _pearson_finite_pairs(series[cid_i], series[cid_j])
                corr_matrix[i][j] = corr if corr is not None else float("nan")

    fig, ax = plt.subplots(figsize=(10, 8))
    filename = output_name or f"subsection_correlation_heatmap_{provider_label.lower()}_{persona_label}_normalized.png"
    im = ax.imshow(corr_matrix, cmap="coolwarm", vmin=-1, vmax=1)
    nonempty_rows = sum(1 for values in normalized_rows if values)
    ax.set_title(
        f"Subsection Correlation Heatmap ({provider_label}, {persona_label})\n"
        f"Normalized subsection scores | n={nonempty_rows}"
    )
    ax.set_xticks(list(range(n)))
    ax.set_yticks(list(range(n)))
    labels = [f"{cid}\n(n={hits[cid]})" for cid in subsection_ids]
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Pearson correlation")

    fig.tight_layout()
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


def _sub_subsection_sort_key(sid: str) -> tuple[int, int, str, str]:
    """Sort deep ids like 1.3.A.a by numeric prefix then lexical suffix."""
    parts = sid.split(".")
    if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]), parts[2], parts[3])
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return (int(parts[0]), int(parts[1]), "", sid)
    return (999, 999, "", sid)


def _to_level3_subsection_id(sid: str) -> str | None:
    """Collapse deep ids (e.g., 1.3.A.a) to level-3 ids (e.g., 1.3.A)."""
    parts = sid.split(".")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        return ".".join(parts[:3])
    return None


def _chart_sub_subsection_correlation_heatmap(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    provider_label: str,
    chart_idx: int,
) -> None:
    """Generate correlation heatmap at level-3 ids like 1.3.A."""
    plt = _safe_import_matplotlib()

    # Aggregate deep deduction signals to level-3 buckets (e.g., 1.3.A).
    level3_rows: list[dict[str, float]] = []
    for row in rows:
        collapsed: dict[str, float] = {}
        for sid, pts in row.sub_subsection_scores.items():
            sid3 = _to_level3_subsection_id(sid)
            if sid3 is None or not math.isfinite(pts):
                continue
            collapsed[sid3] = collapsed.get(sid3, 0.0) + pts
        level3_rows.append(collapsed)

    sub_ids = sorted(
        set(sid for r in level3_rows for sid in r.keys()),
        key=_sub_subsection_sort_key,
    )
    if len(sub_ids) < 2:
        print(
            f"  [{chart_idx}] subsection_level3_correlation_heatmap_{provider_label.lower()}_all_personas.png "
            "(skipped: insufficient deep rubric ids)"
        )
        return

    # Build vectors of deduction points by transcript. Missing ids are 0 (no deduction on that bucket).
    series: dict[str, list[float]] = {}
    hits: dict[str, int] = {}
    for sid in sub_ids:
        vals: list[float] = []
        hit_count = 0
        for row_vals in level3_rows:
            v = row_vals.get(sid, 0.0)
            if math.isfinite(v) and v > 0:
                hit_count += 1
            vals.append(v if math.isfinite(v) else 0.0)
        series[sid] = vals
        hits[sid] = hit_count

    n = len(sub_ids)
    corr_matrix: list[list[float]] = [[float("nan")] * n for _ in range(n)]
    for i, sid_i in enumerate(sub_ids):
        for j, sid_j in enumerate(sub_ids):
            if i == j:
                corr_matrix[i][j] = 1.0
            elif j < i:
                corr_matrix[i][j] = corr_matrix[j][i]
            else:
                corr = _pearson_finite_pairs(series[sid_i], series[sid_j])
                corr_matrix[i][j] = corr if corr is not None else 0.0

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(corr_matrix, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_title(
        f"Sub-Subsection Correlation Heatmap ({provider_label}, all personas)\n"
        "Level-3 rubric buckets (e.g., 1.3.A) using deduction-point signals"
    )
    ax.set_xticks(list(range(n)))
    ax.set_yticks(list(range(n)))
    labels = [f"{sid}\n(n={hits[sid]})" for sid in sub_ids]
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Pearson correlation")

    fig.tight_layout()
    filename = f"subsection_level3_correlation_heatmap_{provider_label.lower()}_all_personas.png"
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {filename}")


# ---------------------------------------------------------------------------
# Chart: Original vs mini transcript score comparison
# ---------------------------------------------------------------------------

def _chart_original_vs_mini(
    original_rows: list[GradeRow],
    mini_rows: list[GradeRow],
    out_dir: Path,
    *,
    persona_label: str,
    output_name: str,
    chart_idx: int,
) -> None:
    """Grouped bar chart comparing original Claude grades vs mini-continuation grades
    for matched transcripts (matched by transcript stem)."""
    plt = _safe_import_matplotlib()
    from matplotlib.ticker import MaxNLocator

    original_by_stem = {r.transcript_name: r for r in original_rows}
    mini_by_stem = {r.transcript_name: r for r in mini_rows}

    matched_stems = sorted(
        set(original_by_stem).intersection(set(mini_by_stem)),
        key=lambda s: int(s.split("_")[-1]) if s.split("_")[-1].isdigit() else 0,
    )

    if not matched_stems:
        print(f"  [{chart_idx}] {output_name} (skipped: no matched transcripts)")
        return

    labels = [s.replace("transcript_", "") for s in matched_stems]
    y_orig = [original_by_stem[s].total_score for s in matched_stems]
    y_mini = [mini_by_stem[s].total_score for s in matched_stems]
    max_score = max(
        (r.max_score for r in [*original_rows, *mini_rows] if math.isfinite(r.max_score)),
        default=46,
    )

    x = list(range(len(matched_stems)))
    width = 0.38

    fig, ax = plt.subplots(figsize=(max(10, len(matched_stems) * 0.9 + 2), 6))
    bars_orig = ax.bar(
        [xi - width / 2 for xi in x], y_orig, width,
        label=f"Original (tutor_04, claude)", color="#ff893a", alpha=0.85,
    )
    bars_mini = ax.bar(
        [xi + width / 2 for xi in x], y_mini, width,
        label=f"Mini (tutor_05, claude)", color="#1f77b4", alpha=0.85,
    )

    # Annotate each bar with its score.
    for bar in bars_orig:
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
            str(int(bar.get_height())), ha="center", va="bottom", fontsize=8,
        )
    for bar in bars_mini:
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
            str(int(bar.get_height())), ha="center", va="bottom", fontsize=8,
        )

    ax.set_title(f"Original vs Mini-Continuation Grade Comparison ({persona_label.capitalize()})")
    ax.set_xlabel("Transcript number")
    ax.set_ylabel("Total Score")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0, max_score + 4)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.axhline(max_score, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()

    finite_orig = [v for v in y_orig if math.isfinite(v)]
    finite_mini = [v for v in y_mini if math.isfinite(v)]
    deltas = [m - o for o, m in zip(y_orig, y_mini) if math.isfinite(o) and math.isfinite(m)]
    lines = [
        f"Matched transcripts: {len(matched_stems)}",
        f"Original mean: {sum(finite_orig)/len(finite_orig):.1f}  Mini mean: {sum(finite_mini)/len(finite_mini):.1f}" if finite_orig and finite_mini else "",
        f"Mean Δ (mini − original): {sum(deltas)/len(deltas):+.1f}" if deltas else "",
    ]
    ax.text(
        0.01, 0.98, "\n".join(l for l in lines if l),
        transform=ax.transAxes, ha="left", va="top", fontsize=9,
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
    output_name: str = "claude_score_histogram_all.png",
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
# Chart: Mean score by course
# ---------------------------------------------------------------------------

_COURSE_LABELS: dict[str, str] = {
    "cities_and_climate_change": "Cities &\nClimate Change",
    "intro_to_international_development_planning": "Intl Dev\nPlanning",
    "mathematics_for_cs": "Math for CS",
    "physics_iii_vibrations_and_waves": "Physics III",
    "meaning_of_life": "Meaning\nof Life",
}


def _chart_mean_score_by_course(
    rows: list[GradeRow],
    out_dir: Path,
    *,
    output_name: str = "claude_mean_score_by_course.png",
    chart_idx: int,
) -> None:
    """Bar chart of mean Claude total score per course (± standard deviation), with n labels.

    Shows how consistently the tutor scores across subjects.
    """
    plt = _safe_import_matplotlib()
    from matplotlib.ticker import MaxNLocator

    by_course: dict[str, list[float]] = {}
    for r in rows:
        if not r.course or not math.isfinite(r.total_score):
            continue
        by_course.setdefault(r.course, []).append(r.total_score)
    if not by_course:
        print(f"  [{chart_idx}] {output_name} (skipped: no course data)")
        return

    max_score = max((r.max_score for r in rows if math.isfinite(r.max_score)), default=40.0)
    courses = sorted(by_course, key=lambda c: sum(by_course[c]) / len(by_course[c]), reverse=True)
    means = [sum(by_course[c]) / len(by_course[c]) for c in courses]
    stds = [
        (sum((v - m) ** 2 for v in by_course[c]) / len(by_course[c])) ** 0.5
        for c, m in zip(courses, means)
    ]
    counts = [len(by_course[c]) for c in courses]
    labels = [_COURSE_LABELS.get(c, c.replace("_", " ").title()) for c in courses]

    x = list(range(len(courses)))
    fig, ax = plt.subplots(figsize=(max(9, len(courses) * 1.7), 6))
    bars = ax.bar(x, means, yerr=stds, capsize=4, color="#2bcbb9", alpha=0.9, edgecolor="white")
    for i, b in enumerate(bars):
        ax.text(
            b.get_x() + b.get_width() / 2,
            b.get_height() + (stds[i] if math.isfinite(stds[i]) else 0) + 0.3,
            f"{means[i]:.1f}\n(n={counts[i]})", ha="center", va="bottom", fontsize=9,
        )
    ax.set_title(f"Mean Tutor Score by Course (Claude judge, out of {int(round(max_score))})")
    ax.set_ylabel(f"Mean total score (out of {int(round(max_score))})")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, max_score + 4)
    ax.axhline(max_score, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / output_name, dpi=150)
    plt.close(fig)
    print(f"  [{chart_idx}] {output_name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: load Claude-graded transcripts and generate all configured charts."""
    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "transcripts"
    out_dir = repo_root / "visualization" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    claude_all_rows = _read_provider_rows(transcripts_dir, "claude")
    print(f"Loaded Claude: {len(claude_all_rows)} transcripts")

    if not claude_all_rows:
        print(
            "No Claude judged transcripts found under "
            "transcripts/<persona>/<persona>_claude/transcript_*.json. "
            "Run the judge for Claude first."
        )
        return 1

    claude_mini_rows = _read_provider_rows_variant(transcripts_dir, "claude", "_mini")
    print(f"Loaded Claude mini: {len(claude_mini_rows)} transcripts")

    claude_tutor05_rows = _read_provider_rows_variant(transcripts_dir, "claude", "_tutor_05")
    print(f"Loaded Claude tutor_05: {len(claude_tutor05_rows)} transcripts")

    chart_idx = 1

    _chart_score_histogram(
        claude_all_rows,
        out_dir,
        output_name="claude_score_histogram_all.png",
        chart_idx=chart_idx,
    )
    chart_idx += 1

    _chart_mean_score_by_course(
        claude_all_rows,
        out_dir,
        output_name="claude_mean_score_by_course.png",
        chart_idx=chart_idx,
    )
    chart_idx += 1

    _chart_provider_total_scores_per_transcript(
        claude_all_rows,
        out_dir,
        provider_label="claude",
        scope_label="all transcripts",
        output_name="claude_grades_all_transcripts.png",
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
                output_name=f"claude_grades_{persona}_transcripts.png",
                chart_idx=chart_idx,
            )
            chart_idx += 1

    hand_grade_path = repo_root / "judge" / "hand_grade_workbook.xlsx"
    try:
        importlib.import_module("openpyxl")
    except ModuleNotFoundError:
        print(
            "Skipping hand vs Claude charts: openpyxl is not installed "
            f"(cannot read {hand_grade_path.name}). Install with: pip install openpyxl"
        )
    else:
        for grader_key, grader_label in (
            ("faizan", "Faizan"),
            ("romain", "Romain"),
            ("nishita", "Nishita"),
        ):
            hand_rows = _read_hand_grade_rows(hand_grade_path, grader_name=grader_key)
            if grader_key == "romain" and hand_rows:
                hand_rows = [
                    r
                    for r in hand_rows
                    if (r.persona_type.lower(), r.transcript_number)
                    not in ROMAIN_HAND_VS_CLAUDE_EXCLUDED
                ]
            if hand_rows:
                _chart_hand_grader_vs_claude(
                    hand_rows,
                    claude_all_rows,
                    out_dir,
                    grader_label=grader_label,
                    output_name=f"hand_grades_{grader_key}_vs_claude.png",
                    chart_idx=chart_idx,
                )
                chart_idx += 1
            else:
                print(
                    f"No hand-grade rows for '{grader_key}' in {hand_grade_path.name} "
                    f"(missing sheet '{grader_key} grading' / 'compiled grading', wrong headers, "
                    "or no rows for that grader). Skipping chart."
                )

    for persona in ("chaotic", "clueless", "cooperative"):
        subset_05 = _filter_individual_rows(claude_tutor05_rows, {persona})
        if subset_05:
            _chart_provider_total_scores_per_transcript(
                subset_05,
                out_dir,
                provider_label="claude",
                scope_label=f"{persona} — tutor_05",
                output_name=f"claude_tutor_05_grades_{persona}.png",
                chart_idx=chart_idx,
            )
            chart_idx += 1

    for persona in ("chaotic", "clueless"):
        orig_subset = _filter_individual_rows(claude_all_rows, {persona})
        mini_subset = _filter_individual_rows(claude_mini_rows, {persona})
        if orig_subset and mini_subset:
            _chart_original_vs_mini(
                orig_subset,
                mini_subset,
                out_dir,
                persona_label=persona,
                output_name=f"original_vs_mini_claude_{persona}.png",
                chart_idx=chart_idx,
            )
            chart_idx += 1

    print(f"\n[Done] Charts saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
