"""
Build transcript-level GPT vs Claude score comparison chart.

Usage:
    python -m visualization.run_visualization
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeRow:
    # Source metadata copied from judged transcript JSON files.
    tutor_prompt: str
    student_persona: str
    course: str
    exercise_number: str
    judge_prompt: str
    judge_rubric: str
    transcript_name: str
    total_score: float
    max_score: float

    @property
    def persona_type(self) -> str:
        # chaotic_04 -> chaotic
        return (self.student_persona.split("_", 1)[0] or self.student_persona).strip()

    @property
    def transcript_key(self) -> str:
        # Key chosen to align the same run across model outputs.
        return "|".join(
            [
                self.student_persona,
                self.course,
                self.exercise_number,
                self.transcript_name,
            ]
        )


def _parse_score(x: str) -> float:
    try:
        return float(str(x or "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _read_judged_transcript_json(path: Path) -> GradeRow | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    grade = raw.get("grade")
    if not isinstance(grade, dict):
        return None

    return GradeRow(
        tutor_prompt=str(raw.get("tutor_prompt", "")).strip(),
        student_persona=str(raw.get("student_persona", "")).strip(),
        course=str(raw.get("course", "")).strip(),
        exercise_number=str(raw.get("exercise_number", "")).strip(),
        judge_prompt=str(raw.get("judge_prompt", "")).strip(),
        judge_rubric=str(raw.get("judge_rubric", "")).strip(),
        transcript_name=path.stem.strip(),
        total_score=_parse_score(grade.get("total_score")),
        max_score=_parse_score(grade.get("max_score")),
    )


def _read_provider_rows(
    *,
    transcripts_dir: Path,
    provider_suffix: str,
) -> list[GradeRow]:
    # provider_suffix examples: "gpt", "claude"
    # Path pattern: transcripts/<persona_type>/<persona_type>_<provider_suffix>/transcript_XX.json
    rows: list[GradeRow] = []
    pattern = f"*/*_{provider_suffix}/transcript_*.json"
    for transcript_path in sorted(transcripts_dir.glob(pattern)):
        row = _read_judged_transcript_json(transcript_path)
        if row is None:
            continue
        rows.append(row)

    return rows


def _sort_key(row: GradeRow) -> tuple:
    # Stable ordering across charts.
    tnum = int(row.transcript_name.split("_")[-1]) if "_" in row.transcript_name else 0
    ex_num = int(row.exercise_number) if row.exercise_number.isdigit() else 0
    return (row.persona_type, row.student_persona, row.course, ex_num, tnum)


def _safe_import_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for visualization. "
            "Install with: python -m pip install matplotlib"
        ) from e
    return plt


def _pearson_correlation(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values):
        return None
    if len(x_values) < 2:
        return None

    n = len(x_values)
    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n

    sum_cov = 0.0
    sum_var_x = 0.0
    sum_var_y = 0.0
    for x, y in zip(x_values, y_values):
        dx = x - mean_x
        dy = y - mean_y
        sum_cov += dx * dy
        sum_var_x += dx * dx
        sum_var_y += dy * dy

    denom = math.sqrt(sum_var_x * sum_var_y)
    if denom == 0:
        return None
    return sum_cov / denom


def _average_ranks(values: list[float]) -> list[float]:
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda iv: iv[1])
    ranks = [0.0] * n

    i = 0
    while i < n:
        j = i
        v = indexed[i][1]
        while j + 1 < n and indexed[j + 1][1] == v:
            j += 1

        # Average rank for ties, with 1-based rank indexing.
        avg_rank = ((i + 1) + (j + 1)) / 2.0
        for k in range(i, j + 1):
            orig_idx = indexed[k][0]
            ranks[orig_idx] = avg_rank
        i = j + 1

    return ranks


def _spearman_correlation(x_values: list[float], y_values: list[float]) -> float | None:
    if len(x_values) != len(y_values):
        return None
    if len(x_values) < 2:
        return None

    x_ranks = _average_ranks(x_values)
    y_ranks = _average_ranks(y_values)
    return _pearson_correlation(x_ranks, y_ranks)


def _line_chart_grades_per_transcript(
    *,
    gpt_rows: list[GradeRow],
    claude_rows: list[GradeRow],
    out_dir: Path,
) -> None:
    plt = _safe_import_matplotlib()

    # Align transcript series by composite key so lines are comparable.
    gpt_by_key = {r.transcript_key: r for r in gpt_rows}
    claude_by_key = {r.transcript_key: r for r in claude_rows}

    all_keys = sorted(set(gpt_by_key.keys()) | set(claude_by_key.keys()))
    all_keys = sorted(
        all_keys,
        key=lambda k: _sort_key(gpt_by_key.get(k) or claude_by_key[k]),
    )

    x = list(range(len(all_keys)))
    y_gpt = [gpt_by_key[k].total_score if k in gpt_by_key else float("nan") for k in all_keys]
    y_claude = [claude_by_key[k].total_score if k in claude_by_key else float("nan") for k in all_keys]

    # Correlation uses only transcript keys that exist in both providers with finite scores.
    paired_gpt: list[float] = []
    paired_claude: list[float] = []
    for key in all_keys:
        gpt_row = gpt_by_key.get(key)
        claude_row = claude_by_key.get(key)
        if gpt_row is None or claude_row is None:
            continue
        if not math.isfinite(gpt_row.total_score) or not math.isfinite(claude_row.total_score):
            continue
        paired_gpt.append(gpt_row.total_score)
        paired_claude.append(claude_row.total_score)
    pearson_corr = _pearson_correlation(paired_gpt, paired_claude)
    spearman_corr = _spearman_correlation(paired_gpt, paired_claude)

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(x, y_gpt, label="GPT", color="#a65dea", linewidth=1.8, marker="o", markersize=3)
    ax.plot(x, y_claude, label="Claude", color="#ff893a", linewidth=1.8, marker="o", markersize=3)
    ax.set_title("Grades Per Transcript: GPT vs Claude")
    ax.set_xlabel("Transcript Index (sorted by persona/course/exercise/transcript)")
    ax.set_ylabel("Total Score")
    ax.grid(True, alpha=0.3)
    ax.legend()

    pearson_text = (
        f"Pearson Correlation: {pearson_corr:.3f}"
        if pearson_corr is not None
        else "Pearson Correlation: N/A"
    )
    spearman_text = (
        f"Spearman Correlation: {spearman_corr:.3f}"
        if spearman_corr is not None
        else "Spearman Correlation: N/A"
    )
    corr_text = f"{pearson_text}\n{spearman_text}"
    ax.text(
        0.01,
        0.98,
        corr_text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.8, "edgecolor": "#cccccc"},
    )

    fig.tight_layout()
    fig.savefig(out_dir / "grades_per_transcript_gpt_vs_claude.png", dpi=150)
    plt.close(fig)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    transcripts_dir = repo_root / "transcripts"
    out_dir = repo_root / "visualization" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    gpt_rows = _read_provider_rows(transcripts_dir=transcripts_dir, provider_suffix="gpt")
    claude_rows = _read_provider_rows(transcripts_dir=transcripts_dir, provider_suffix="claude")

    if not gpt_rows and not claude_rows:
        raise RuntimeError(
            "No judged transcript JSON files found for GPT or Claude under transcripts/<persona_type>/."
        )

    _line_chart_grades_per_transcript(
        gpt_rows=gpt_rows,
        claude_rows=claude_rows,
        out_dir=out_dir,
    )
    print(f"[Done] Wrote visualizations to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
