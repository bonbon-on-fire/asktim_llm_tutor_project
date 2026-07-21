"""Charts for the AskTIM vs STEM AskTIM comparison (07/21 round).

Deliberately narrow: ``run_visualization`` analyses one tutor's rubric profile in
depth (11 charts); this renders only the four that carry the *comparison* story,
because that is what the Thursday conversation needs. Both tutors are ours:
"New AskTIM" is the current one (formerly the Humanities Tutor); "STEM AskTIM"
is the earlier open-learning-ai-tutor generation.

    1. score by course      — New AskTIM leads on both, and by how much
    2. score by student type — the lead is concentrated under pressure
    3. answer-giving failures — why: the 12-point 1.1.A.a deduction
    4. tutor cost           — the structural gap, and where it comes from

Reads the graded transcripts written by ``internal_testing.run_transcript_rag``
under ``transcripts/<type>/<type>_{cmp,phys}_{asktim,stem}/``.

Scope note: this reads only what is on disk — the SCD *practices* and *physics*
rounds, 108 conversations. A third round (SCD exercises 1-3, +4.52) was run and
deleted before being committed; it is deliberately NOT folded in from memory,
so every number here is recomputable from the repo.

    python -m visualization.run_comparison_viz

Every chart uses the same frame — concise title, one caption line saying what
you're looking at, legend centred at the bottom — so the set reads as one
deck rather than four separate figures.

Colors are the validated two-series categorical pair (blue slot 1 / orange
slot 2): all-pairs CVD delta-E 24.7, normal-vision 33.6, both >= 3:1 on the light
surface. Every bar is also direct-labeled, so identity never rests on hue alone.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRANSCRIPTS = _REPO_ROOT / "transcripts"
_OUT = _REPO_ROOT / "visualization" / "outputs" / "comparison"

# Arm identity. Fixed order, never cycled — New AskTIM first everywhere.
_ARMS = ("asktim", "stem")
_ARM_LABEL = {"asktim": "New AskTIM", "stem": "STEM AskTIM"}
_ARM_COLOR = {"asktim": "#2a78d6", "stem": "#eb6834"}

# Student types, ordered easiest -> hardest so the widening gap reads left to right.
_PERSONAS = ("cooperative", "clueless", "chaotic")

# Folder token -> course label. Both rounds are 9 personas x 3 problems x 1 trial.
_ROUNDS = {
    "cmp": "Supply Chain\n(practices 1–3)",
    # exercises/exercise_11..13.txt — kind "exercise". Their content is practice
    # exam papers (11 covers lectures 1-8, 12 covers 9-17, 13 covers 1-23), which
    # is why retrieval runs unscoped here; the label tracks the repo, not the title.
    "phys": "Physics III\n(exercises 11–13)",
}

# Recessive ink; text never wears a series color.
_INK = "#0b0b0b"
_INK_SOFT = "#52514e"
_GRID = "#dcdcd8"

_MAX_SCORE = 40
_CLIFF_POINTS = 12  # 1.1.A.a removes all of criterion 1.1 at once


@dataclass(frozen=True)
class Row:
    arm: str
    round_key: str
    persona_type: str
    score: int
    max_score: int
    cliff: bool
    usd: float
    cost_parts: tuple[tuple[str, float], ...]

    @property
    def usd_tutor_only(self) -> float:
        """Cost of the tutor-side model calls, excluding the simulated student.

        The student is a harness artifact — in production it's a person — so
        billing it would inflate both arms and understate the ratio between them.
        """
        return sum(v for k, v in self.cost_parts if k != "student")


def _load() -> list[Row]:
    """Parse every graded comparison transcript into a flat row list."""
    rows: list[Row] = []
    for graded in sorted(_TRANSCRIPTS.glob("*/*/transcript_*_graded.json")):
        folder = graded.parent.name  # e.g. chaotic_cmp_asktim
        parts = folder.split("_")
        if len(parts) < 3:
            continue
        round_key, arm = parts[-2], parts[-1]
        if arm not in _ARMS or round_key not in _ROUNDS:
            continue

        doc = json.loads(graded.read_text(encoding="utf-8"))
        grade = doc.get("grade")
        if not isinstance(grade, dict):
            continue

        # The 12-point answer-giving cliff (1.1.A.a) — a single deduction that
        # zeroes criterion 1.1. Its presence, not its size, is the signal.
        cliff = any(
            ded.get("points") == _CLIFF_POINTS
            for sec in (grade.get("sections") or {}).values()
            for crit in (sec.get("criteria") or {}).values()
            for ded in (crit.get("deductions") or [])
        )

        # Cost lives on the raw transcript, not the graded copy.
        raw_path = graded.with_name(graded.name.replace("_graded", ""))
        cost = json.loads(raw_path.read_text(encoding="utf-8"))["cost_estimate"]
        by_comp = {k: v for k, v in cost["by_component_usd"].items() if v}

        rows.append(
            Row(
                arm=arm,
                round_key=round_key,
                persona_type=doc["student_persona"].split("_", 1)[0],
                score=int(grade["total_score"]),
                max_score=int(grade["max_score"]),
                cliff=cliff,
                usd=float(cost["total_usd"]),
                cost_parts=tuple(sorted(by_comp.items())),
            )
        )
    return rows


def _mean(rows: list[Row], **where) -> float:
    """Mean score over the rows matching every ``field=value`` in *where*."""
    sub = [r for r in rows if all(getattr(r, k) == v for k, v in where.items())]
    return sum(r.score for r in sub) / len(sub) if sub else 0.0


def _plt():
    """Import matplotlib with the non-interactive backend, as the sibling module does."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "matplotlib is required. Install with: python -m pip install matplotlib"
        ) from exc
    return plt


# --------------------------------------------------------------------------- #
# Shared frame — every chart in the set is laid out identically
# --------------------------------------------------------------------------- #

def _frame(fig, plt, title: str, caption: str) -> None:
    """Title, one-line caption, and a bottom-centred tutor legend.

    Keeping the frame identical across the set means the reader learns
    blue = New AskTIM once and it holds for every chart.
    """
    fig.suptitle(title, color=_INK, fontsize=14.5, fontweight="bold",
                 x=0.012, ha="left", y=0.965)
    fig.text(0.012, 0.895, caption, color=_INK_SOFT, fontsize=9.5, va="top")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_ARM_COLOR[a], label=_ARM_LABEL[a])
        for a in _ARMS
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=2, frameon=False,
        fontsize=10.5, labelcolor=_INK_SOFT, bbox_to_anchor=(0.5, 0.005),
        handlelength=1.1, handleheight=1.1, columnspacing=2.2,
    )
    # Leaves room for the title block above and the legend below.
    fig.tight_layout(rect=(0, 0.075, 1, 0.855))


def _style(ax, *, ylabel: str = "", ymax: float | None = None) -> None:
    """Recessive axes: horizontal grid behind the marks, no box, muted ink."""
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.8)
    ax.xaxis.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_GRID)
    ax.tick_params(colors=_INK_SOFT, length=0, labelsize=9.5)
    if ylabel:
        ax.set_ylabel(ylabel, color=_INK_SOFT, fontsize=9.5)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def _grouped(ax, categories, series, *, fmt="{:.1f}", width=0.3, gap=0.02):
    """Two-series grouped bars with a surface gap between them.

    *series* is ``{arm: [value per category]}``. Every bar is direct-labeled —
    the pair is distinguishable by hue, but the labels mean it doesn't have to be.
    """
    xs = range(len(categories))
    for i, arm in enumerate(_ARMS):
        offset = (i - 0.5) * (width + gap)
        bars = ax.bar([x + offset for x in xs], series[arm], width=width,
                      color=_ARM_COLOR[arm], label=_ARM_LABEL[arm], zorder=3)
        for b in bars:
            ax.annotate(fmt.format(b.get_height()),
                        (b.get_x() + b.get_width() / 2, b.get_height()),
                        textcoords="offset points", xytext=(0, 3), ha="center",
                        fontsize=9, color=_INK)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(categories, color=_INK_SOFT, fontsize=10)


# --------------------------------------------------------------------------- #
# 1. Score by course
# --------------------------------------------------------------------------- #

def chart_score_by_course(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    series = {arm: [_mean(rows, arm=arm, round_key=c) for c in courses]
              for arm in _ARMS}

    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    _grouped(ax, [_ROUNDS[c] for c in courses], series, width=0.24)
    _style(ax, ylabel=f"Mean score (of {_MAX_SCORE})", ymax=44)

    for i in range(len(courses)):
        gap = series["asktim"][i] - series["stem"][i]
        ax.annotate(f"+{gap:.1f}", (i, max(series["asktim"][i], series["stem"][i]) + 3.4),
                    ha="center", fontsize=11, color=_INK, fontweight="bold")

    _frame(fig, plt, "Judge score by course",
           "Mean of 27 conversations per tutor per course assignment, scored out of 40 "
           "on the pedagogy rubric.\nNew AskTIM leads on both.")
    path = _OUT / "01_score_by_course.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 2. Score by student type
# --------------------------------------------------------------------------- #

def chart_score_by_persona(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4), sharey=True)

    for ax, course in zip(axes, courses):
        series = {arm: [_mean(rows, arm=arm, round_key=course, persona_type=p)
                        for p in _PERSONAS] for arm in _ARMS}
        _grouped(ax, [p.capitalize() for p in _PERSONAS], series)
        _style(ax, ylabel=f"Mean score (of {_MAX_SCORE})" if ax is axes[0] else "",
               ymax=44)
        ax.set_title(_ROUNDS[course].replace("\n", " "), color=_INK_SOFT,
                     fontsize=10.5, loc="left", pad=8)

    _frame(fig, plt, "Judge score by student type",
           "Nine conversations per student type per tutor. The two are close on "
           "cooperative students\nand separate as students get harder to handle.")
    path = _OUT / "02_score_by_persona.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 3. Answer-giving failures
# --------------------------------------------------------------------------- #

def chart_integrity_cliff(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4), sharey=True)

    for ax, course in zip(axes, courses):
        series = {
            arm: [sum(1 for r in rows if r.arm == arm and r.round_key == course
                      and r.persona_type == p and r.cliff)
                  for p in _PERSONAS]
            for arm in _ARMS
        }
        _grouped(ax, [p.capitalize() for p in _PERSONAS], series, fmt="{:.0f}")
        _style(ax, ylabel="Conversations (of 9)" if ax is axes[0] else "", ymax=6.4)
        ax.set_yticks(range(0, 7, 2))
        ax.set_title(_ROUNDS[course].replace("\n", " "), color=_INK_SOFT,
                     fontsize=10.5, loc="left", pad=8)

    _frame(fig, plt, "Answer-giving failures",
           "Conversations where the tutor handed over submission-ready work — one "
           "deduction that costs\nall 12 pedagogy points. Lower is better.")
    path = _OUT / "03_integrity_cliff.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 4. Tutor cost
# --------------------------------------------------------------------------- #

def chart_cost(rows: list[Row], plt) -> Path:
    """Stacked tutor cost, so STEM AskTIM's extra assessment call is visible.

    The reply is the shared base, so the classification step reads as the
    difference rather than needing a second axis.
    """
    courses = list(_ROUNDS)
    # Tutor-side model calls only. The simulated student is a harness artifact —
    # in production the student is a person. Embedding is New AskTIM's RAG query
    # call (~$0.0002/conversation, invisible at this scale but real).
    order = ("tutor", "tutor_assessment", "embedding")
    shade = {
        ("asktim", "tutor"): "#2a78d6", ("asktim", "embedding"): "#c7dcf5",
        ("stem", "tutor"): "#eb6834", ("stem", "tutor_assessment"): "#f4a583",
    }
    seg_label = {"tutor": "reply", "tutor_assessment": "assessment"}

    fig, ax = plt.subplots(figsize=(9, 5.4))
    labels, xs, idx = [], [], 0
    for course in courses:
        for arm in _ARMS:
            sub = [r for r in rows if r.arm == arm and r.round_key == course]
            n = max(1, len(sub))
            totals: dict[str, float] = defaultdict(float)
            for r in sub:
                for k, v in r.cost_parts:
                    if k != "student":
                        totals[k] += v / n
            bottom = 0.0
            for comp in order:
                val = totals.get(comp, 0.0)
                if val <= 0:
                    continue
                ax.bar(idx, val, bottom=bottom, width=0.58,
                       color=shade.get((arm, comp), "#cccccc"),
                       edgecolor="#fcfcfb", linewidth=1.2, zorder=3)
                if val > 0.06:
                    ax.annotate(seg_label.get(comp, comp), (idx, bottom + val / 2),
                                ha="center", va="center", fontsize=9, color=_INK)
                bottom += val
            ax.annotate(f"${bottom:.2f}", (idx, bottom), textcoords="offset points",
                        xytext=(0, 4), ha="center", fontsize=10.5, color=_INK,
                        fontweight="bold")
            labels.append(_ARM_LABEL[arm])
            xs.append(idx)
            idx += 1
        idx += 0.5

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, color=_INK_SOFT, fontsize=9.5)
    _style(ax, ylabel="Mean cost per 10-turn conversation (USD)", ymax=1.24)
    for i, course in enumerate(courses):
        ax.text(xs[i * 2] + 0.5, -0.135, _ROUNDS[course].replace("\n", " "),
                ha="center", fontsize=10, color=_INK,
                transform=ax.get_xaxis_transform())

    # Ratio is derived, not hardcoded — it shifts whenever the component set does
    # (dropping the simulated-student cost moved it from 2.4-3.1x to 2.5-3.4x).
    ratios = sorted(
        sum(r.usd_tutor_only for r in rows if r.arm == "stem" and r.round_key == c)
        / max(1e-9, sum(r.usd_tutor_only for r in rows
                        if r.arm == "asktim" and r.round_key == c))
        for c in courses
    )
    _frame(fig, plt, "Tutor cost per conversation",
           "STEM AskTIM makes two model calls per turn — it classifies the student's "
           "message, then replies.\n"
           f"That costs {ratios[0]:.1f}–{ratios[-1]:.1f}× more.")
    path = _OUT / "04_cost_per_conversation.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> int:
    rows = _load()
    if not rows:
        print("No graded comparison transcripts found under transcripts/*/*_{cmp,phys}_*/.")
        return 1

    _OUT.mkdir(parents=True, exist_ok=True)
    plt = _plt()

    for arm in _ARMS:
        for course in _ROUNDS:
            n = len([r for r in rows if r.arm == arm and r.round_key == course])
            label = _ROUNDS[course].replace("\n", " ")
            print(f"  {_ARM_LABEL[arm]:<14} {label:<32} n={n}")

    for path in (
        chart_score_by_course(rows, plt),
        chart_score_by_persona(rows, plt),
        chart_integrity_cliff(rows, plt),
        chart_cost(rows, plt),
    ):
        print(f"wrote {path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
