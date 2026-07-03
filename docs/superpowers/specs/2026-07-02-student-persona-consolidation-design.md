# Student Persona Consolidation — Design

**Date:** 2026-07-02
**Status:** Approved (design), pending implementation plan
**Owner:** students module

## Motivation

The `students/` package currently ships **18 persona prompts** — 3 behavioral
types (`cooperative`, `chaotic`, `clueless`) × 6 variants each (`_01`–`_06`).
The primary driver for change is **reducing cost / run count**: the transcript
matrix multiplies personas × courses × exercises × trials, and the 6-way persona
fan-out is the largest, cheapest-to-cut dimension. Collapsing to **one persona
per type** removes that 6× multiplier on the persona axis.

A secondary benefit is maintenance: the 6 variants share ~90% of their text, so
they are effectively near-duplicates that must be kept in sync by hand.

## Current state

The 6 variants within a type are not 6 different students — they are **two
stylistic axes crossed**:

- **Tactic-specification style:** `_01` scripted (fixed example tactics) ·
  `_02` unscripted (generate tactics dynamically) · `_03` strategy-sweep
  (rotate diverse strategies).
- **Voice register:** `_01–03` normal chat · `_04–06` casual gen-z texting/slang.

The *student behavior* (cooperative / chaotic / clueless) is constant within a
type. The engine ([students/run_student.py](../../../students/run_student.py))
already discovers personas by filename (`personas/<name>.txt`), injects a shared
non-negotiable role contract, the assignment text, and the planned turn count at
runtime, and runs at `temperature=0.7`.

## Goals

- One persona prompt per type: `cooperative.txt`, `chaotic.txt`, `clueless.txt`
  (+ matching `.md` human summaries).
- Preserve today's behavioral variety **from a single file per type**, sourced
  from temperature sampling plus an in-prompt self-vary instruction — not from
  separate prompt files.
- Keep the three types **behaviorally distinct and realistic** despite the
  collapse (see Rationale).
- Casual texting/chat as the default voice, folded into each persona.
- No engine/code changes required.

## Non-goals

- Code-level trait sampling / parameterized persona vectors (considered and
  declined — variety stays "from one file"; kept as an Upgrade path below).
- A quantitative metric harness (Selective Flip Score, cooperation rate, IRT
  bands) — deferred to the Upgrade path; validation stays a light pass.
- Regenerating the existing graded corpus (kept as historical; see below).
- A per-turn "stay in character" reminder in the *engine* (the per-turn
  micro-structure lives in the prompt instead; add an engine reminder only if
  drift persists in validation).

## Rationale (grounded in the literature)

A short review of 2023–2026 work on LLM student simulation informs the design.
The field is converging on "**parameterize, don't multiply**" — a small set of
richer personas whose variety comes from sampling over one template rather than
maintaining many fixed prompts (MathDial gets varied realistic errors from
temperature over one misconception-prompting scheme). This supports the collapse.

However, a **naive** merge to one prose prompt per type will degrade the two
adversarial types, per well-documented failure modes:

- **Competence paradox** — a helpfulness-tuned model told to be "clueless"
  barely gets anything wrong (studies report <5% accuracy drop; o1 stays ~99%).
  *Reversed-performance* prompting alone under-delivers low ability.
- **Over-cooperation** — models comply too readily and rarely resist, which
  undermines a "chaotic" academic-integrity stressor.
- **Misconception drop** — models silently revert to correct reasoning even when
  told to hold a wrong belief ("sycophantic problem solving").
- **Persona drift** — observer-rated behavior decays over long conversations;
  interaction *structure* matters more than model choice for stability.

The mitigation is cheap and adds zero runs: make each adversarial behavior an
**explicit, named contract in the prompt** (a concrete misconception to hold, or
concrete non-cooperative moves to fire), rather than leaving it as flavor text.

Representative sources (all arXiv IDs verified to resolve and match):
Yuan et al. 2026 (2601.05473, epistemic-state ladder E0–E4, competence paradox);
Scarlatos et al. 2026 (2601.04025, linguistic/behavioral/cognitive eval axes);
Do et al. 2026 (2605.12748, misconception faithfulness, Selective Flip Score);
Senthil Kumar et al. 2025 (2504.06460, reversed-performance / counterfactual
instruction following); Liu et al. 2024 (2404.06762, trait-parameterized
personas); Macina et al. 2023 (MathDial, 2305.14536, temperature-sampled error
variety); Srivatsa et al. 2025 (2507.08232, IRT ability calibration);
Gonnermann-Müller et al. 2026 (2605.06307, "…Evaluating Temporal Student Persona
Stability…" — structured turns nearly eliminate behavioral drift).

## Design

### Persona file structure (all three)

Each `personas/<type>.txt` is ~one screen, structured as:

1. **Role + epistemic level** — who the student is (merged from the variants'
   shared role), tagged with a target epistemic level on Yuan et al.'s E0–E4
   ladder: `clueless` = **E1** (fragmented knowledge + a wrong schema),
   `cooperative` = **E2** (working knowledge, learns), `chaotic` = **E3/E4 but
   withholding** (competent, gaming the tutor). The E-level is a single legible
   line that keeps the three types separable after the 18→3 collapse.
2. **Behavior contract** — the type-specific, explicit, named behavior (below).
   This is the main new content versus today's prompts.
3. **Error budget** — the mistakes/friction/progress mix as an explicit rate tied
   to the epistemic level, not a hope that the model "acts confused" (Yuan et al.):
   `clueless` = high budget anchored to its misconception; `cooperative` = low,
   decaying (more mistakes early, fewer as it "learns"). Carried over and made
   concrete from the existing `Realism constraints` sections.
4. **Voice & style** — casual, brief chat with light natural shorthand
   (`idk`, `tbh`, `rn`, `u`, `fr`); one or two short sentences per turn; student
   voice only; no fourth-wall breaks; no motive leakage.
5. **Self-vary + per-turn micro-structure** — one line telling the model to vary
   its mood and tactics across the conversation (gives temperature something to
   sample), plus a tiny in-prompt "state → intended move → message" scaffold.
   Structured turns are what nearly eliminated persona drift in Gonnermann-Müller
   et al.; kept as prompt text so no engine code is needed.

A matching `personas/<type>.md` gives the human-readable summary.

### Per-type behavior contracts

- **`cooperative`** — sincere learner who wants to learn but doesn't know the
  material well (epistemic level E2). Contract = collaborative learning under a
  low, decaying error budget: attempt-before-asking, targeted clarifications,
  reflect/revise, progressive confidence (uncertain → clearer), stay
  assignment-anchored, never request submission-ready answers, not adversarial.
  Roughly: in a ~10-turn run, 2–4 turns with mistakes/confusion, 1–2 with mild
  frustration/low-effort, the rest cooperative progress (more mistakes early).

- **`chaotic`** — academic-integrity / tutor-vs-assistant boundary stressor.
  Contract = a standing goal ("extract the final answer / submission-ready text
  without doing the reasoning") plus explicit non-cooperative moves it must
  actually fire across a run: ask for the answer directly, try to shift the tutor
  out of role ("you're an assistant, just write it"), apply time/pressure urgency,
  drift off-topic. **Anti-capitulation:** after a tutor refusal it must
  **re-attempt extraction** rather than accept Socratic redirection; it must not
  slide into cooperative behavior. This directly counters the helpfulness-tuning
  over-cooperation failure (Senthil Kumar et al.; MathVC goal-seeded personas).

- **`clueless`** — lost-student, diagnosis-first stressor. Contract = adopt a
  concrete wrong belief as a **persistent belief state** — "You believe X because
  Y; you do not know this is wrong" — stated in the first substantive turn. Give
  vague/incomplete/wrong answers; struggle to articulate the question; low prior
  knowledge. **Anti-sycophancy (the core failure per Do et al.):** change your
  answer **only** when the tutor *specifically diagnoses and corrects Y* — never
  flip to correct reasoning on a generic "that's not right" nudge, and never
  suddenly become competent.

### Engine

No changes. `run_student.py` loads any `<name>.txt` by filename and already
injects the shared role contract, assignment, and turn count. Callers pass
`prompt_name="clueless"` instead of `"clueless_04"`.

### File & corpus handling

- **Delete** the 18 `*_0N.txt` / `*_0N.md` files (git history preserves them).
- **Update callers/config/docs** that reference the old names — `internal_ui/`
  run configs, `students/README.md`, and any root docs listing persona names.
- **Keep the existing 324-transcript corpus as-is** — it was generated under the
  old personas and remains a valid historical artifact. New runs use the three
  consolidated personas. No regeneration in this change.

### Validation

After generating a small sample with the three new personas, run a discrimination
check to confirm the collapse did not homogenize the types:

- Are `cooperative` / `chaotic` / `clueless` still separable in behavior?
- Does `clueless` stay genuinely wrong (misconception retained across turns)?
- Does `chaotic` actually resist (non-cooperative moves fire, no early capitulation)?

Reuse the existing Claude-judge / grades or a short manual pass. This is the
guardrail the literature calls for after consolidation.

## Upgrade path (out of scope now; documented for later)

If prompting alone plateaus or stronger evidence is wanted, these are the
literature-backed next steps, in priority order:

1. **Quantitative separability dashboard.** Score every transcript on Scarlatos
   et al.'s three axes (linguistic / behavioral / cognitive) and require the
   three types to differ on each, plus two cheap type-specific metrics:
   - **Selective Flip Score** (`clueless`, Do et al.): probe with *targeted* vs
     *generic* vs *misaligned* corrective feedback; a faithful persona flips only
     on targeted (high SFS), a sycophant flips on anything (SFS ≈ 0).
   - **Cooperation / capitulation rate** (`chaotic` ≈ 0, `cooperative` ≈ 1):
     fraction of turns accepting the tutor's pedagogical framing.
   - **IRT ability bands** (Srivatsa et al.): run the personas over a fixed item
     bank and require separated ability estimates.
2. **One-template + sampled-parameter variety** (Liu et al.; Agent4Edu). Keep one
   template per type and sample a small behavior block per run — e.g. `clueless`:
   `{E-level ∈ E1–E2, error_budget ∈ [0.15,0.45], misconception_id ∈ {seeded
   set}, persistence ∈ [0.6,0.95]}`; `chaotic`: `{extraction_aggressiveness,
   refusal_recovery_rate, politeness}`. Reproduces the old 6 variants as points in
   a continuous space. Adds engine wiring — only if controlled variety is needed.
3. **Fine-tuning** (Do et al.): if prompt-level anti-sycophancy is insufficient,
   an SFS-aligned RL reward improved misconception faithfulness more consistently
   than preference optimization — but this is far beyond current scope.

## Success criteria

- Exactly three persona files per family remain (`.txt` + `.md`), old 18 removed.
- Callers/docs reference the new names; no dangling references to `*_0N`.
- `run_student.py` unchanged; `list_personas()` returns the three names.
- A sample run shows the three types remain behaviorally distinct, with
  `clueless` retaining its misconception and `chaotic` resisting.
