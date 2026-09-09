# docs/ — project documents & design history

Human-facing documents about AskTIM: the public-facing legal text, stakeholder
decks, the research write-up, product screenshots, and the full design-history
archive of every feature that shipped. Nothing here is imported by the running
apps — it's the paper trail, not code.

## Top-level files

| File | What it is |
|------|-----------|
| `asktim_terms_of_service.txt` | The Terms of Service shown/linked to students using the tutor. |
| `meeting_deck_2026_june.md` | Stakeholder meeting deck (MIT CTL / OCW), June 2026. |
| `meeting_deck_2026_july.md` | Stakeholder meeting deck, July 2026. |
| `research_proposal_2026_summer.pdf` | Summer 2026 research proposal for the tutor study. |

> Note: `meeting_notes/` (dated running notes) lives at the repo root, separate
> from these polished decks.

## screenshots/

Product screenshots used in decks and READMEs — one per surface:

- `asktim-student-chat.png` — the student chat (`main_ui`).
- `sandbox-create-context.png` — the Create-context wizard (`sandbox_ui`).
- `database-review.png` — the read-only conversation review tool (`database_ui`).
- `weekly-report.png` — the weekly analytics report.

**Never commit a screenshot that shows a password or secret** (the `database_ui`
master password, per-course passwords, Railway env values). Crop or blur before
adding one here.

## superpowers/ — design history

The design record for the project, one pair of documents per feature, named
`YYYY-MM-DD-<feature>`:

- **`superpowers/specs/…-design.md`** — the *design doc* for a feature: the
  problem, the approach chosen, alternatives weighed, and the shape of the
  change. Written before/while building.
- **`superpowers/plans/…-<feature>.md`** — the *execution plan*: the concrete,
  ordered implementation steps for that feature.

Together they read as a chronological history of how AskTIM was built — from the
early `ui_core` consolidation and student-persona work (July 2026) through
per-course tutor rules, the weekly report and RubricJudge, to the most recent
provider-outage markers and per-course exam/anonymization work (Sept 2026). A
newcomer wanting the "why" behind a feature should read its spec first, then the
plan.

These are historical snapshots — they describe intent at the time of writing and
are **not** kept in sync with later code changes. For current behavior, trust the
code and the component READMEs; use these for rationale and context.
