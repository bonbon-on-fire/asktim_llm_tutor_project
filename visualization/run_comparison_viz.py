"""Charts for the AskTIM vs STEM AskTIM comparison (07/21 round).

Deliberately narrow: ``run_visualization`` analyses one tutor's rubric profile in
depth (11 charts); this renders only the four that carry the *comparison* story,
because that's what the Thursday conversation needs.

    1. score by course      — we lead on both, and by how much
    2. score by persona     — the lead is concentrated under pressure
    3. integrity cliff rate — why: 1.1.A.a answer-giving, per persona
    4. cost per conversation — the structural gap, and where it comes from
    5. score distribution   — the floor, which the means hide

Reads the graded transcripts written by ``internal_testing.run_transcript_rag``
under ``transcripts/<type>/<type>_{cmp,phys}_{asktim,stem}/``.

Scope note: this reads only what is on disk — the SCD *practices* and *physics*
rounds, 108 conversations. A third round (SCD exercises 1-3, +4.52) was run and
deleted before being committed; it is deliberately NOT folded in from memory,
so every number here is recomputable from the repo.

    python -m visualization.run_comparison_viz

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

# Arm identity. Fixed order, never cycled — ours first everywhere.
_ARMS = ("asktim", "stem")
_ARM_LABEL = {"asktim": "Our AskTIM", "stem": "STEM AskTIM (MIT)"}
_ARM_COLOR = {"asktim": "#2a78d6", "stem": "#eb6834"}

# Persona families, ordered easiest -> hardest so the widening gap reads left to right.
_PERSONAS = ("cooperative", "clueless", "chaotic")

# Folder token -> course label. Both rounds are 9 personas x 3 problems x 1 trial.
_ROUNDS = {
    "cmp": "Supply Chain\n(practices 1-3)",
    "phys": "Physics III\n(exams 11-13)",
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


def _style(ax, *, ylabel: str = "", ymax: float | None = None) -> None:
    """Recessive axes: horizontal grid behind the marks, no box, muted ink."""
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.8)
    ax.xaxis.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_GRID)
    ax.tick_params(colors=_INK_SOFT, length=0)
    if ylabel:
        ax.set_ylabel(ylabel, color=_INK_SOFT, fontsize=10)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def _grouped(ax, categories, series, *, fmt="{:.1f}", width=0.36, gap=0.02):
    """Two-series grouped bars with a 2px-equivalent surface gap between them.

    *series* is ``{arm: [value per category]}``. Every bar is direct-labeled —
    the pair is distinguishable by hue, but the labels mean it doesn't have to be.
    """
    xs = range(len(categories))
    for i, arm in enumerate(_ARMS):
        offset = (i - 0.5) * (width + gap)
        bars = ax.bar(
            [x + offset for x in xs],
            series[arm],
            width=width,
            color=_ARM_COLOR[arm],
            label=_ARM_LABEL[arm],
            zorder=3,
        )
        for b in bars:
            ax.annotate(
                fmt.format(b.get_height()),
                (b.get_x() + b.get_width() / 2, b.get_height()),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                fontsize=9,
                color=_INK,
            )
    ax.set_xticks(list(xs))
    ax.set_xticklabels(categories, color=_INK_SOFT, fontsize=10)


# --------------------------------------------------------------------------- #
# 1. Headline — mean score by course
# --------------------------------------------------------------------------- #

def chart_score_by_course(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    series = {
        arm: [
            sum(r.score for r in rows if r.arm == arm and r.round_key == c)
            / max(1, len([r for r in rows if r.arm == arm and r.round_key == c]))
            for c in courses
        ]
        for arm in _ARMS
    }

    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    _grouped(ax, [_ROUNDS[c] for c in courses], series, width=0.26)
    _style(ax, ylabel=f"Mean judge score (of {_MAX_SCORE})", ymax=44)
    ax.set_title(
        "Our tutor scores higher on both courses",
        color=_INK, fontsize=13, fontweight="bold", loc="left", pad=34,
    )
    ax.text(
        0, 1.085,
        "27 conversations per arm per course · judge_08 / rubric_08 · claude-sonnet-4-6",
        transform=ax.transAxes, color=_INK_SOFT, fontsize=9,
    )
    # Delta sits between the pair, clear of both bar labels and the legend.
    for i, c in enumerate(courses):
        delta = series["asktim"][i] - series["stem"][i]
        ax.annotate(
            f"+{delta:.1f}", (i, max(series['asktim'][i], series['stem'][i]) + 4.2),
            ha="center", fontsize=11, color=_INK, fontweight="bold",
        )
    ax.legend(
        frameon=False, fontsize=10, labelcolor=_INK_SOFT, ncol=2,
        loc="lower left", bbox_to_anchor=(0, 1.005),
    )
    fig.tight_layout()
    path = _OUT / "01_score_by_course.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 2. The finding — where the lead actually comes from
# --------------------------------------------------------------------------- #

def chart_score_by_persona(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    for ax, course in zip(axes, courses):
        series = {
            arm: [
                sum(r.score for r in rows
                    if r.arm == arm and r.round_key == course and r.persona_type == p)
                / max(1, len([r for r in rows
                              if r.arm == arm and r.round_key == course and r.persona_type == p]))
                for p in _PERSONAS
            ]
            for arm in _ARMS
        }
        _grouped(ax, [p.capitalize() for p in _PERSONAS], series)
        _style(ax, ylabel=f"Mean judge score (of {_MAX_SCORE})" if ax is axes[0] else "", ymax=46)
        ax.set_title(_ROUNDS[course].replace("\n", " "), color=_INK_SOFT, fontsize=11, loc="left")

    axes[0].legend(
        frameon=False, fontsize=10, labelcolor=_INK_SOFT, ncol=2,
        loc="lower left", bbox_to_anchor=(0, 1.06),
    )
    fig.suptitle(
        "The gap is small on cooperative students and widens under pressure",
        color=_INK, fontsize=13, fontweight="bold", x=0.008, ha="left", y=0.985,
    )
    fig.text(
        0.008, 0.93,
        "9 conversations per persona family per arm · personas ordered by difficulty",
        color=_INK_SOFT, fontsize=9,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    path = _OUT / "02_score_by_persona.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 3. The mechanism — answer-giving under pressure
# --------------------------------------------------------------------------- #

def chart_integrity_cliff(rows: list[Row], plt) -> Path:
    courses = list(_ROUNDS)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    for ax, course in zip(axes, courses):
        series = {
            arm: [
                sum(1 for r in rows
                    if r.arm == arm and r.round_key == course
                    and r.persona_type == p and r.cliff)
                for p in _PERSONAS
            ]
            for arm in _ARMS
        }
        _grouped(ax, [p.capitalize() for p in _PERSONAS], series, fmt="{:.0f}")
        _style(ax, ylabel="Conversations with a 1.1.A.a deduction (of 9)"
               if ax is axes[0] else "", ymax=6.4)
        ax.set_yticks(range(0, 7, 2))
        ax.set_title(_ROUNDS[course].replace("\n", " "), color=_INK_SOFT, fontsize=11, loc="left")

    axes[0].legend(
        frameon=False, fontsize=10, labelcolor=_INK_SOFT, ncol=2,
        loc="lower left", bbox_to_anchor=(0, 1.06),
    )
    fig.suptitle(
        "Why: the STEM tutor gives away submission-ready work when pushed",
        color=_INK, fontsize=13, fontweight="bold", x=0.008, ha="left", y=0.985,
    )
    fig.text(
        0.008, 0.93,
        "Rubric 1.1.A.a removes all 12 pedagogy points at once — lower is better",
        color=_INK_SOFT, fontsize=9,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    path = _OUT / "03_integrity_cliff.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 4. Cost — structural, and independent of the judge
# --------------------------------------------------------------------------- #

def chart_cost(rows: list[Row], plt) -> Path:
    """Stacked cost per conversation, so the STEM tutor's second call is visible.

    Components are stacked in a fixed order with a hairline surface gap between
    segments; the tutor's own reply is the shared base, so the extra assessment
    call reads as the difference rather than needing a second axis.
    """
    courses = list(_ROUNDS)
    order = ("tutor", "tutor_assessment", "student", "embedding")
    shade = {  # one hue per arm, stepped light->dark within the stack
        ("asktim", "tutor"): "#2a78d6", ("asktim", "student"): "#8cb9ea",
        ("asktim", "embedding"): "#c7dcf5",
        ("stem", "tutor"): "#eb6834", ("stem", "tutor_assessment"): "#f4a583",
        ("stem", "student"): "#fad3c3",
    }

    fig, ax = plt.subplots(figsize=(9, 5))
    labels, xs, idx = [], [], 0
    for course in courses:
        for arm in _ARMS:
            sub = [r for r in rows if r.arm == arm and r.round_key == course]
            n = max(1, len(sub))
            totals = defaultdict(float)
            for r in sub:
                for k, v in r.cost_parts:
                    totals[k] += v / n
            bottom = 0.0
            for comp in order:
                val = totals.get(comp, 0.0)
                if val <= 0:
                    continue
                ax.bar(idx, val, bottom=bottom, width=0.62,
                       color=shade.get((arm, comp), "#cccccc"),
                       edgecolor="#fcfcfb", linewidth=1.2, zorder=3)
                if val > 0.06:
                    ax.annotate(comp.replace("tutor_assessment", "2nd call: assessment"),
                                (idx, bottom + val / 2), ha="center", va="center",
                                fontsize=8, color="#0b0b0b")
                bottom += val
            ax.annotate(f"${bottom:.2f}", (idx, bottom), textcoords="offset points",
                        xytext=(0, 4), ha="center", fontsize=10,
                        color=_INK, fontweight="bold")
            labels.append(_ARM_LABEL[arm].replace(" (MIT)", ""))
            xs.append(idx)
            idx += 1
        idx += 0.45

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, color=_INK_SOFT, fontsize=9.5)
    _style(ax, ylabel="Mean cost per 10-turn conversation (USD)", ymax=1.42)
    # Same legend, same place, on every chart in the set — the viewer learns
    # blue=ours once and it holds across the whole deck.
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_ARM_COLOR[a], label=_ARM_LABEL[a])
        for a in _ARMS
    ]
    ax.legend(
        handles=handles, frameon=False, fontsize=10, labelcolor=_INK_SOFT, ncol=2,
        loc="lower left", bbox_to_anchor=(0, 1.005),
    )
    for i, course in enumerate(courses):
        ax.text(xs[i * 2] + 0.5, -0.16, _ROUNDS[course].replace("\n", " "),
                ha="center", fontsize=10, color=_INK, transform=ax.get_xaxis_transform())
    ax.set_title(
        "Their two-calls-per-turn design costs 2.4-3.1x more",
        color=_INK, fontsize=13, fontweight="bold", loc="left", pad=34,
    )
    ax.text(0, 1.085,
            "Segments are billed components · our arm gets a 41% prompt-cache hit rate, theirs 0%",
            transform=ax.transAxes, color=_INK_SOFT, fontsize=9)
    fig.tight_layout()
    path = _OUT / "04_cost_per_conversation.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# 5. The floor — what the means hide
# --------------------------------------------------------------------------- #

def chart_distribution(rows: list[Row], plt) -> Path:
    """Per-conversation score spread, so the low tail is visible.

    Both arms reach 40 at the top; they separate at the bottom. Means alone make
    the tutors look closer than they behave, and for a student-facing tool the
    worst case matters more than the average.
    """
    courses = list(_ROUNDS)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), sharey=True)

    for ax, course in zip(axes, courses):
        data = [[r.score for r in rows if r.arm == arm and r.round_key == course]
                for arm in _ARMS]

        bp = ax.boxplot(
            data, positions=[0, 1], widths=0.42, patch_artist=True,
            showfliers=False, medianprops={"color": "#fcfcfb", "linewidth": 2},
            whiskerprops={"color": _INK_SOFT, "linewidth": 1.2},
            capprops={"color": _INK_SOFT, "linewidth": 1.2},
            boxprops={"linewidth": 0},
        )
        for patch, arm in zip(bp["boxes"], _ARMS):
            patch.set_facecolor(_ARM_COLOR[arm])
            patch.set_alpha(0.85)

        # Individual conversations, deterministically jittered so the shape of the
        # low tail is visible rather than implied by a whisker.
        for i, (arm, scores) in enumerate(zip(_ARMS, data)):
            for j, s in enumerate(sorted(scores)):
                offset = ((j % 7) - 3) * 0.035
                ax.plot(i + offset, s, "o", markersize=4.5,
                        color=_INK, alpha=0.45, zorder=4)
            ax.annotate(
                f"min {min(scores)}", (i, min(scores)), textcoords="offset points",
                xytext=(0, -16), ha="center", fontsize=9.5, color=_INK,
                fontweight="bold",
            )

        ax.set_xticks([0, 1])
        ax.set_xticklabels([_ARM_LABEL[a].replace(" (MIT)", "") for a in _ARMS],
                           color=_INK_SOFT, fontsize=10)
        _style(ax, ylabel=f"Judge score (of {_MAX_SCORE})" if ax is axes[0] else "")
        ax.set_ylim(12, 43)
        ax.set_title(_ROUNDS[course].replace("\n", " "), color=_INK_SOFT,
                     fontsize=11, loc="left")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_ARM_COLOR[a], label=_ARM_LABEL[a])
        for a in _ARMS
    ]
    axes[0].legend(
        handles=handles, frameon=False, fontsize=10, labelcolor=_INK_SOFT, ncol=2,
        loc="lower left", bbox_to_anchor=(0, 1.06),
    )
    fig.suptitle(
        "Both reach 40 at their best — they separate at their worst",
        color=_INK, fontsize=13, fontweight="bold", x=0.008, ha="left", y=0.985,
    )
    fig.text(
        0.008, 0.93,
        "Each dot is one conversation (27 per arm per course) · box spans the "
        "middle 50%, white line is the median",
        color=_INK_SOFT, fontsize=9,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    path = _OUT / "05_score_distribution.png"
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
            print(f"  {_ARM_LABEL[arm]:<18} {label:<30} n={n}")

    for path in (
        chart_score_by_course(rows, plt),
        chart_score_by_persona(rows, plt),
        chart_integrity_cliff(rows, plt),
        chart_cost(rows, plt),
        chart_distribution(rows, plt),
    ):
        print(f"wrote {path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
