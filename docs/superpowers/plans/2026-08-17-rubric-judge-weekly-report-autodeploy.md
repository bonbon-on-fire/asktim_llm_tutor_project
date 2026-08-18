# Rubric-Judge Weekly Report + Auto-Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the weekly report's lightweight judge for the mature rubric_08 judge (full 40-point grading stored, highlights-only shown), and make the weekly job run and deploy automatically to `prod-beta-plus` through an auto-merged PR while enforcing PR-only pushes for collaborators.

**Architecture:** Two independent workstreams. **A (deploy):** a GitHub branch ruleset requires a PR to land on `prod-beta`/`prod-beta-plus` (owner bypasses; collaborators cannot); the weekly GitHub Actions job pushes its cache to a throwaway branch, opens a PR, and merges it with the built-in `GITHUB_TOKEN`. **B (judge):** the existing eval rubric judge (`eval/tutor_judge/run_judge.py`) gains an in-memory entrypoint; a new adapter (`database_ui/analytics/rubric_judge.py`) converts the weekly job's `(role, content)` transcripts into the eval transcript shape, runs the rubric judge, keeps the full grade in the committed cache, and derives report/dashboard highlights (pass/fail at 32/40, top deductions, overview) plus a separate cheap topics call.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, pytest; `langgraph` + `langchain-anthropic` (already in `requirements.txt`); GitHub Actions; GitHub repository rulesets via `gh api`.

**Spec:** Inline brainstorm captured in this conversation. Background/prior spec: `docs/superpowers/plans/2026-08-12-weekly-report.md`.

## Global Constraints

- **Commits:** Conventional Commits always — `type(scope): subject` — including any merge commits. **Never** append a `Co-Authored-By: Claude` trailer.
- **Secrets:** Never commit real passwords/API keys and never print secret values into logs or the report. Secrets live only in GitHub Actions secrets (`ANTHROPIC_API_KEY`, `ANALYTICS_DATABASE_URL`) and Railway env.
- **Privacy:** The analytics cache contains real student usernames/emails — the repo must stay **private**. Do not add cache contents to any public artifact.
- **Deploy branch:** `prod-beta-plus`. Keep `tutor_09` as the app default; this plan does not change the tutor.
- **Do not touch:** `meeting_notes/2026-08-11.md` (user's own uncommitted edit) and `.claude/settings.local.json` (local settings) — never stage or commit them.
- **Static assets:** When editing a static asset, bump its `?v=` query string at every include site.
- **Judge model:** The weekly rubric judge uses **`claude-sonnet-4-6`** (the model `rubric_08` was calibrated on, and the one the judge's hardcoded `temperature=0` is compatible with). Do **not** point it at a Claude-5 model without first stripping `temperature` and re-checking calibration.
- **Rubric:** `rubric_08` (40-point base: Pedagogy 20 / Dialogue 12 / Communication 8), judge prompt `judge_08`. Do not author a new rubric.
- **Pass threshold:** a conversation "worked well" iff `total_score >= 32` (80% of 40).

---

## Workstream A — Auto-Deploy (Option B: auto-merged PR)

### Task A1: Branch-protection ruleset on `prod-beta` + `prod-beta-plus`

**Files:**
- Create: `docs/ops/branch-protection.md` (records the ruleset JSON + how to re-apply/verify — the ruleset itself lives on GitHub, not in the repo).

**Interfaces:**
- Produces: an **active** repository ruleset named `protect-prod-beta-branches` targeting `refs/heads/prod-beta` and `refs/heads/prod-beta-plus`, requiring a PR (0 approvals), blocking `deletion` and `non_fast_forward`, with the **Repository admin** role as a bypass actor. `github-actions[bot]` is deliberately **not** a bypass actor — its PRs merge because 0 approvals are required.

This task configures GitHub, so its "test" is reading the ruleset back with `gh api`, not pytest.

- [ ] **Step 1: Confirm the current owner/admin and repo slug**

Run:
```bash
gh repo view --json nameWithOwner -q .nameWithOwner
gh api repos/{owner}/{repo}/rulesets -q '.[].name'   # expect: no protect-prod-beta-branches yet
```
Expected: prints the `owner/repo` slug; the ruleset list does not already contain `protect-prod-beta-branches`.

- [ ] **Step 2: Write the ruleset payload to a scratch file**

Write this JSON to `"$TMPDIR/ruleset.json"` (or the session scratchpad). `actor_id: 5` + `actor_type: RepositoryRole` is GitHub's built-in **Repository admin** role, which the repo owner holds — that is what lets the owner push directly:
```json
{
  "name": "protect-prod-beta-branches",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/prod-beta", "refs/heads/prod-beta-plus"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ]
}
```

- [ ] **Step 3: Create the ruleset**

Run:
```bash
gh api --method POST repos/{owner}/{repo}/rulesets \
  --input "$TMPDIR/ruleset.json" -q '.id,.name,.enforcement'
```
Expected: prints a numeric id, `protect-prod-beta-branches`, `active`.

- [ ] **Step 4: Verify enforcement by reading it back**

Run:
```bash
gh api repos/{owner}/{repo}/rulesets \
  -q '.[] | select(.name=="protect-prod-beta-branches") | {id,enforcement}'
gh api repos/{owner}/{repo}/rulesets/{id} \
  -q '{target, conditions:.conditions.ref_name.include, rules:[.rules[].type], bypass:[.bypass_actors[].actor_type]}'
```
Expected: `enforcement: active`; includes both `refs/heads/prod-beta` and `refs/heads/prod-beta-plus`; rules contain `deletion`, `non_fast_forward`, `pull_request`; bypass contains `RepositoryRole`.

- [ ] **Step 5: Document and commit**

Write `docs/ops/branch-protection.md` containing: the exact ruleset JSON from Step 2, the create command (Step 3), the verify command (Step 4), and one paragraph explaining the model — *collaborators must open a PR; the repo owner (Repository admin) bypasses and can push directly; the weekly Actions job is not a bypass actor and lands its cache through an auto-merged PR (0 approvals required)*.
```bash
git add docs/ops/branch-protection.md
git commit -m "docs(ops): record prod-beta branch-protection ruleset"
```

---

### Task A2: Weekly workflow opens + merges a PR to `prod-beta-plus`

**Files:**
- Modify: `.github/workflows/weekly-analytics.yml` (currently ends with a direct `git push origin HEAD:${TARGET_BRANCH}` step at lines 60-71; the `permissions:` block at lines 20-21 is `contents: write` only; the judge-model default at line 51 is `claude-sonnet-5`).

**Interfaces:**
- Consumes: repo secrets `ANALYTICS_DATABASE_URL`, `ANTHROPIC_API_KEY`; optional repo var `ANALYTICS_JUDGE_MODEL`; the ruleset from Task A1.
- Produces: on each run, a branch `analytics/weekly-<week_key>` pushed from the runner, a PR into `prod-beta-plus`, and an immediate squash-merge of that PR via the built-in `GITHUB_TOKEN` (deleting the branch). Keeps the Sunday `0 8 * * 0` cron. The rubric judge's model default becomes `claude-sonnet-4-6`.

This is a workflow-config change; its "test" is YAML validity + a manual `workflow_dispatch`, not pytest.

- [ ] **Step 1: Restore `pull-requests: write` permission**

In `.github/workflows/weekly-analytics.yml`, change the `permissions:` block (lines 20-21) from:
```yaml
permissions:
  contents: write
```
to:
```yaml
permissions:
  contents: write
  pull-requests: write
```

- [ ] **Step 2: Switch the judge-model default to the calibrated model**

Change line 51 from:
```yaml
          ANALYTICS_JUDGE_MODEL: ${{ vars.ANALYTICS_JUDGE_MODEL || 'claude-sonnet-5' }}
```
to:
```yaml
          ANALYTICS_JUDGE_MODEL: ${{ vars.ANALYTICS_JUDGE_MODEL || 'claude-sonnet-4-6' }}
```

- [ ] **Step 3: Replace the direct-push step with open-PR-and-merge**

Replace the entire final step (lines 60-71, `- name: Commit report cache to prod-beta-plus`) with:
```yaml
      - name: Open and merge report-cache PR to prod-beta-plus
        env:
          GH_TOKEN: ${{ github.token }}
          WEEK: ${{ steps.gen.outputs.week_key }}
        run: |
          git config user.name "asktim-bot"
          git config user.email "asktim-bot@users.noreply.github.com"
          git add database_ui/analytics/cache/
          if git diff --cached --quiet; then
            echo "No cache changes; nothing to deploy."
            exit 0
          fi
          BRANCH="analytics/weekly-${WEEK}"
          git checkout -b "$BRANCH"
          git commit -m "chore(analytics): weekly report cache for ${WEEK}"
          git push --force-with-lease origin "$BRANCH"
          # 0 required approvals on the ruleset => the bot can merge its own PR.
          gh pr create --base "$TARGET_BRANCH" --head "$BRANCH" \
            --title "chore(analytics): weekly report cache for ${WEEK}" \
            --body "Automated weekly analytics cache for week ${WEEK}. Merges on creation."
          gh pr merge "$BRANCH" --squash --delete-branch
```

- [ ] **Step 4: Validate the workflow YAML**

Run (any one available):
```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/weekly-analytics.yml')); print('yaml ok')"
```
Expected: prints `yaml ok` with no exception. If `actionlint` is installed, also run `actionlint .github/workflows/weekly-analytics.yml` and expect no errors.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/weekly-analytics.yml
git commit -m "ci(analytics): deploy weekly cache via auto-merged PR to prod-beta-plus"
```

- [ ] **Step 6: Manual smoke test (record, do not block the plan)**

After Workstream B is merged to `prod-beta-plus`, note in the PR description that the owner should run the workflow once via **Actions → Weekly analytics report → Run workflow** with `max_convos: 2` and confirm: a `analytics/weekly-*` PR appears and auto-merges, and Railway redeploys. This is an operator action, not an automated test.

---

## Workstream B — Rubric-Judge Swap

### Task B1: In-memory `grade_transcript_payload` entrypoint

**Files:**
- Modify: `eval/tutor_judge/run_judge.py` — extract the grading body of `_judge_transcript` (lines 709-788) into a new public function; keep `_judge_transcript` (lines 686-803) as a thin file-in/file-out wrapper around it.
- Test: `eval/tutor_judge/test_run_judge_payload.py` (new pytest file).

**Interfaces:**
- Produces: `grade_transcript_payload(transcript: dict, *, provider: Provider = "claude", prompt_name: str = DEFAULT_JUDGE_PROMPT, rubric_name: str = DEFAULT_RUBRIC, model_name: str | None = None, api_key: str | None = None) -> dict`. The returned dict is the ordered grade payload: `sections`, `total_base_score`, `max_base_score`, `overview`, `judge_reasoning`, `total_score`, `max_score`, `model`, `judge_llm_calls`, `token_usage`, `cost_estimate`. Raises `JudgeError` if `exchanges` is missing/empty or the judge fails to produce valid JSON. When `transcript["course"]` is empty, figure discovery is skipped (text-only).
- Consumes: existing module helpers `load_judge_prompt`, `_format_conversation_for_judge`, `_create_model_invoke`, `_create_judge_graph`, `_order_grade_payload`, `priced`, and the figure helpers.

- [ ] **Step 1: Write the failing test**

Create `eval/tutor_judge/test_run_judge_payload.py`:
```python
"""grade_transcript_payload: in-memory grading without file or network I/O."""
from eval.tutor_judge import run_judge


class _FakeGraph:
    def invoke(self, state):
        assert state["num_turns"] == 1          # exchanges were formatted
        assert "Physics" in state["conversation_text"]  # context flowed through
        return {
            "grade_json": {
                "sections": {}, "overview": "Solid Socratic guidance.",
                "total_base_score": 33, "max_base_score": 40,
                "total_score": 33, "max_score": 40,
            },
            "attempts": 1,
            "token_usage": {"input_tokens": 10, "output_tokens": 5, "cache_read": 0, "cache_write": 0},
            "judge_model": "claude-sonnet-4-6",
        }


def test_grade_transcript_payload_returns_ordered_grade(monkeypatch):
    monkeypatch.setattr(run_judge, "_create_model_invoke", lambda *a, **k: None)
    monkeypatch.setattr(run_judge, "_create_judge_graph", lambda **k: _FakeGraph())

    transcript = {
        "course": "",                       # disables figure discovery
        "context": "Physics III",
        "exercise": "Damped oscillator",
        "exchanges": [{"student": "where do I start?", "tutor": "what forces act on the mass?"}],
    }
    grade = run_judge.grade_transcript_payload(transcript, api_key="test-key")

    assert grade["total_score"] == 33
    assert grade["max_score"] == 40
    assert grade["overview"] == "Solid Socratic guidance."
    assert grade["model"] == {"provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0}
    assert "cost_estimate" in grade and "token_usage" in grade


def test_grade_transcript_payload_rejects_empty_exchanges(monkeypatch):
    monkeypatch.setattr(run_judge, "_create_model_invoke", lambda *a, **k: None)
    monkeypatch.setattr(run_judge, "_create_judge_graph", lambda **k: _FakeGraph())
    import pytest
    with pytest.raises(run_judge.JudgeError):
        run_judge.grade_transcript_payload({"course": "", "exchanges": []}, api_key="test-key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest eval/tutor_judge/test_run_judge_payload.py -v`
Expected: FAIL — `AttributeError: module 'eval.tutor_judge.run_judge' has no attribute 'grade_transcript_payload'`.

- [ ] **Step 3: Add `grade_transcript_payload` and refactor `_judge_transcript`**

In `eval/tutor_judge/run_judge.py`, add this function immediately **above** `_judge_transcript` (before line 686):
```python
def grade_transcript_payload(
    transcript: dict[str, Any],
    *,
    provider: Provider = "claude",
    prompt_name: str = DEFAULT_JUDGE_PROMPT,
    rubric_name: str = DEFAULT_RUBRIC,
    model_name: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Grade an in-memory transcript dict and return the ordered grade payload.

    Same grading path as ``_judge_transcript`` but with no file I/O: callers
    (the eval CLI and the weekly report adapter) pass a transcript dict shaped
    ``{course, context, exercise, exchanges:[{student, tutor, retrieved?}], figures?}``
    and receive the grade payload. An empty ``course`` skips figure discovery.
    """
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript must be an object.")
    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain non-empty 'exchanges' list.")

    if provider == "gpt":
        model_name = model_name or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        api_key = api_key or _require_openai_api_key()
        reasoning = os.environ.get("JUDGE_OPENAI_REASONING_EFFORT", DEFAULT_REASONING).strip().lower() or DEFAULT_REASONING
    else:
        model_name = model_name or os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL)
        api_key = api_key or _require_anthropic_api_key()
        reasoning = "off"

    invoke_model = _create_model_invoke(provider, model_name, api_key, reasoning)
    graph = _create_judge_graph(invoke_model=invoke_model, model_name=model_name, provider=provider)

    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text = _format_conversation_for_judge(transcript)

    course = _sanitize_text(transcript.get("course")).strip()
    figure_names: list[str] = []
    recorded = transcript.get("figures")
    if isinstance(recorded, list):
        figure_names.extend(str(n) for n in recorded)
    if course:
        retrieved_sources = []
        for ex in exchanges:
            if not isinstance(ex, dict):
                continue
            recs = ex.get("retrieved")
            if not isinstance(recs, list):
                continue
            for rec in recs:
                if isinstance(rec, dict):
                    retrieved_sources.append(str(rec.get("source", "")))
        figure_names.extend(figure_filenames(discover_figures_for_sources(course, retrieved_sources)))
    figure_names = list(dict.fromkeys(figure_names))
    figures: list = resolve_figure_filenames(course, figure_names) if (course and figure_names) else []

    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": system_prompt,
            "conversation_text": conversation_text,
            "num_turns": len(exchanges),
            "figures": figures,
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    if provider == "gpt":
        grade_payload["model"] = {
            "provider": "openai",
            "model": model_name,
            "temperature": 0,
            "reasoning_effort": reasoning,
        }
    else:
        grade_payload["model"] = {"provider": "anthropic", "model": model_name, "temperature": 0}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    judge_usage = result.get("token_usage") or {
        "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
    }
    judge_model = result.get("judge_model") or model_name
    grade_payload["token_usage"] = judge_usage
    grade_payload["cost_estimate"] = priced(judge_model, judge_usage)
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    return _order_grade_payload(grade_payload)
```
Then replace the body of `_judge_transcript` **from line 705 (`exchanges = transcript.get("exchanges")`) through line 788 (`grade_payload = _order_grade_payload(grade_payload)`)** with a single call, so lines 686-704 (docstring + file load + dict check) are kept and the tail (lines 790-803, `out_doc = dict(transcript) …`) is unchanged:
```python
    grade_payload = grade_transcript_payload(
        transcript,
        provider=provider,
        prompt_name=prompt_name,
        rubric_name=rubric_name,
    )
```

- [ ] **Step 4: Run the new test + the existing figures test**

Run:
```bash
python -m pytest eval/tutor_judge/test_run_judge_payload.py -v
python -m eval.tutor_judge.test_judge_figures
```
Expected: the pytest file PASSES; the figures script still prints all PASS (the figure logic moved but is byte-for-byte identical).

- [ ] **Step 5: Commit**

```bash
git add eval/tutor_judge/run_judge.py eval/tutor_judge/test_run_judge_payload.py
git commit -m "feat(tutor_judge): add in-memory grade_transcript_payload entrypoint"
```

---

### Task B2: Carry the full grade on `Verdict`; add `exercise` to the judge interface

**Files:**
- Modify: `database_ui/analytics/judge.py` (`Verdict` dataclass lines 18-32; `Judge` Protocol line 45-46; `FakeJudge.judge` line 57; `AnthropicJudge.judge` line 110).
- Test: `database_ui/analytics/tests/test_judge.py` (add cases).

**Interfaces:**
- Produces: `Verdict(worked_well: bool, issues: list[dict] = [], topics: list[str] = [], one_line: str = "", grade: dict | None = None)`. `Verdict.as_dict(course)` includes `"grade": self.grade` **only when** `grade is not None`. `Judge` protocol method becomes `judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict`. `FakeJudge.judge` and `AnthropicJudge.judge` accept and ignore `*, exercise: str = ""`.

- [ ] **Step 1: Write the failing test**

Add to `database_ui/analytics/tests/test_judge.py`:
```python
from database_ui.analytics.judge import Verdict


def test_verdict_as_dict_includes_grade_only_when_present():
    plain = Verdict(worked_well=True, one_line="ok")
    assert "grade" not in plain.as_dict("physics")

    graded = Verdict(worked_well=True, one_line="ok",
                     grade={"total_score": 35, "max_score": 40})
    d = graded.as_dict("physics")
    assert d["grade"] == {"total_score": 35, "max_score": 40}
    assert d["course"] == "physics"


def test_fake_judge_accepts_exercise_kwarg():
    j = FakeJudge(default=Verdict(worked_well=True, one_line="ok"))
    # Passing exercise must not raise and must not change the canned/default logic.
    assert j.judge("c1", [("student", "hi")], exercise="Damped oscillator").one_line == "ok"
```
(Keep the existing `from database_ui.analytics.judge import FakeJudge, Verdict, transcript_hash, ISSUE_TYPES` import at the top; add `Verdict` is already imported.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest database_ui/analytics/tests/test_judge.py -v`
Expected: FAIL — `test_verdict_as_dict_includes_grade_only_when_present` fails (`grade` always/never present or `TypeError` on unknown field), and `test_fake_judge_accepts_exercise_kwarg` fails with `TypeError: judge() got an unexpected keyword argument 'exercise'`.

- [ ] **Step 3: Implement the changes**

In `database_ui/analytics/judge.py`:

Change the `Verdict` dataclass (lines 18-32) to:
```python
@dataclass(frozen=True)
class Verdict:
    worked_well: bool
    issues: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    one_line: str = ""
    grade: dict | None = None

    def as_dict(self, course: str) -> dict:
        out = {
            "course": course,
            "worked_well": self.worked_well,
            "issues": self.issues,
            "topics": self.topics,
            "one_line": self.one_line,
        }
        if self.grade is not None:
            out["grade"] = self.grade
        return out
```

Change the `Judge` protocol (line 45-46) to:
```python
class Judge(Protocol):
    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict: ...
```

Change `FakeJudge.judge` (line 57) signature to:
```python
    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict:
```
(body unchanged).

Change `AnthropicJudge.judge` (line 110) signature to:
```python
    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict:
```
(body unchanged — `AnthropicJudge` stays until Task B4 removes it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest database_ui/analytics/tests/test_judge.py -v`
Expected: PASS (all existing cases plus the two new ones).

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/judge.py database_ui/analytics/tests/test_judge.py
git commit -m "feat(analytics): Verdict carries full grade; judge interface takes exercise"
```

---

### Task B3: `RubricJudge` adapter + grade→highlights mapping + cheap topics call

**Files:**
- Create: `database_ui/analytics/rubric_judge.py`.
- Test: `database_ui/analytics/tests/test_rubric_judge.py` (new).

**Interfaces:**
- Consumes: `grade_transcript_payload` (Task B1), `Verdict` (Task B2), `database_ui.analytics.stats.is_tutor`.
- Produces:
  - `SCORE_THRESHOLD = 32`, `DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"`, `DEFAULT_TOPICS_MODEL = "claude-haiku-4-5-20251001"`.
  - `pairs_to_exchanges(pairs: list[tuple[str, str]]) -> list[dict]` — folds `(role, content)` turns into `[{student, tutor}, ...]`.
  - `grade_to_verdict(grade: dict, topics: list[str], *, threshold: int = SCORE_THRESHOLD) -> Verdict` — `worked_well = total_score >= threshold`; `issues` = top 3 deductions (`type` = `sub_criterion_id`, `quote` = `reason`, `severity` from `points`); `one_line` = `overview`; `grade` attached.
  - `RubricJudge(model=DEFAULT_JUDGE_MODEL, *, topics_model=DEFAULT_TOPICS_MODEL, threshold=SCORE_THRESHOLD, api_key=None)` with `judge(self, course, transcript, *, exercise="") -> Verdict`.

- [ ] **Step 1: Write the failing test**

Create `database_ui/analytics/tests/test_rubric_judge.py`:
```python
from database_ui.analytics import rubric_judge as rj
from database_ui.analytics.judge import Verdict


def test_pairs_to_exchanges_pairs_student_then_tutor():
    pairs = [("student", "hi"), ("tutor", "what do you think?"),
             ("student", "maybe force?"), ("tutor", "why?")]
    assert rj.pairs_to_exchanges(pairs) == [
        {"student": "hi", "tutor": "what do you think?"},
        {"student": "maybe force?", "tutor": "why?"},
    ]


def test_pairs_to_exchanges_leading_tutor_and_trailing_student():
    pairs = [("tutor", "welcome!"), ("student", "start?"), ("tutor", "recall Newton"),
             ("student", "ok thanks")]
    assert rj.pairs_to_exchanges(pairs) == [
        {"student": "", "tutor": "welcome!"},
        {"student": "start?", "tutor": "recall Newton"},
        {"student": "ok thanks", "tutor": ""},
    ]


def _grade(total, deductions):
    return {
        "total_score": total, "max_score": 40, "overview": "summary here",
        "sections": {"1_pedagogy": {"criteria": {"1.1": {"deductions": deductions,
                                                          "score": 0, "max": 12}}}},
    }


def test_grade_to_verdict_pass_threshold():
    v = rj.grade_to_verdict(_grade(35, []), ["waves"])
    assert v.worked_well is True
    assert v.topics == ["waves"]
    assert v.one_line == "summary here"
    assert v.grade["total_score"] == 35


def test_grade_to_verdict_fail_and_ranks_deductions_by_points():
    deductions = [
        {"sub_criterion_id": "1.1.A.a", "reason": "small ding", "points": 1},
        {"sub_criterion_id": "1.1.B.b", "reason": "gave the answer", "points": 8},
        {"sub_criterion_id": "1.1.C.c", "reason": "mid issue", "points": 3},
    ]
    v = rj.grade_to_verdict(_grade(28, deductions), [])
    assert v.worked_well is False                      # 28 < 32
    assert [i["type"] for i in v.issues] == ["1.1.B.b", "1.1.C.c", "1.1.A.a"]  # by points desc
    assert v.issues[0]["severity"] == "high"           # 8 >= 5
    assert v.issues[1]["severity"] == "medium"         # 3 >= 2
    assert v.issues[2]["severity"] == "low"            # 1 < 2
    assert v.issues[0]["quote"] == "gave the answer"


def test_rubric_judge_orchestrates_grade_and_topics(monkeypatch):
    captured = {}

    def fake_grade(transcript, **kwargs):
        captured["transcript"] = transcript
        captured["model"] = kwargs.get("model_name")
        return _grade(30, [{"sub_criterion_id": "2.2.A.a", "reason": "rushed", "points": 4}])

    import eval.tutor_judge.run_judge as run_judge
    monkeypatch.setattr(run_judge, "grade_transcript_payload", fake_grade)

    j = rj.RubricJudge(model="claude-sonnet-4-6", api_key="k")
    monkeypatch.setattr(j, "_extract_topics", lambda course, transcript: ["momentum"])

    v = j.judge("Physics III", [("student", "hi"), ("tutor", "why?")], exercise="Collisions")

    assert isinstance(v, Verdict)
    assert v.worked_well is False
    assert v.topics == ["momentum"]
    assert v.grade["total_score"] == 30
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["transcript"]["context"] == "Physics III"
    assert captured["transcript"]["exercise"] == "Collisions"
    assert captured["transcript"]["course"] == ""     # figure discovery disabled
    assert captured["transcript"]["exchanges"] == [{"student": "hi", "tutor": "why?"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest database_ui/analytics/tests/test_rubric_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'database_ui.analytics.rubric_judge'`.

- [ ] **Step 3: Implement `rubric_judge.py`**

Create `database_ui/analytics/rubric_judge.py`:
```python
# database_ui/analytics/rubric_judge.py
"""Production judge for the weekly report.

Wraps the mature ``rubric_08`` judge from ``eval/tutor_judge`` so the weekly
job's ``(role, content)`` transcripts can be graded on the full 40-point
rubric. The complete grade is stored in the cache; the report/dashboard show
only highlights (pass/fail at the 32/40 threshold, top deductions, overview).
The rubric judge does not emit topics, so those come from a separate cheap
call.
"""
from __future__ import annotations

import os

from database_ui.analytics.judge import Verdict
from database_ui.analytics.stats import is_tutor

SCORE_THRESHOLD = 32                              # >= 32/40 (80%) == "worked well"
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"         # rubric_08 is calibrated on this
DEFAULT_TOPICS_MODEL = "claude-haiku-4-5-20251001"
_MAX_ISSUES = 3


def pairs_to_exchanges(pairs: list[tuple[str, str]]) -> list[dict]:
    """Fold alternating (role, content) turns into eval-shaped exchanges.

    Each exchange pairs a student utterance with the tutor reply that follows.
    A leading tutor turn becomes an exchange with an empty student; a trailing
    student turn, an exchange with an empty tutor; two students in a row flush
    the first with an empty tutor.
    """
    exchanges: list[dict] = []
    pending_student: str | None = None
    for role, content in pairs:
        if is_tutor(role):
            exchanges.append({"student": pending_student or "", "tutor": content})
            pending_student = None
        else:
            if pending_student is not None:
                exchanges.append({"student": pending_student, "tutor": ""})
            pending_student = content
    if pending_student is not None:
        exchanges.append({"student": pending_student, "tutor": ""})
    return exchanges


def _points(d: dict) -> int:
    try:
        return int(d.get("points", 0))
    except (TypeError, ValueError):
        return 0


def _grade_to_issues(grade: dict, *, limit: int = _MAX_ISSUES) -> list[dict]:
    deductions: list[dict] = []
    for section in (grade.get("sections") or {}).values():
        if not isinstance(section, dict):
            continue
        for crit in (section.get("criteria") or {}).values():
            if not isinstance(crit, dict):
                continue
            for d in crit.get("deductions") or []:
                if isinstance(d, dict):
                    deductions.append(d)
    deductions.sort(key=_points, reverse=True)
    issues: list[dict] = []
    for d in deductions[:limit]:
        pts = _points(d)
        severity = "high" if pts >= 5 else "medium" if pts >= 2 else "low"
        issues.append({
            "type": str(d.get("sub_criterion_id", "")),
            "severity": severity,
            "quote": str(d.get("reason", ""))[:200],
            "points": pts,
        })
    return issues


def grade_to_verdict(grade: dict, topics: list[str], *, threshold: int = SCORE_THRESHOLD) -> Verdict:
    try:
        total = int(grade.get("total_score", 0))
    except (TypeError, ValueError):
        total = 0
    return Verdict(
        worked_well=total >= threshold,
        issues=_grade_to_issues(grade),
        topics=list(topics),
        one_line=str(grade.get("overview", "")),
        grade=grade,
    )


_TOPICS_SYSTEM = (
    "Name the 1-3 specific concepts the student worked on in this tutoring "
    "conversation, as short noun phrases. Interpret them in the context of the "
    "named course, whatever its discipline."
)
_TOPICS_SCHEMA = {
    "name": "topics",
    "description": "Concepts the student worked on.",
    "parameters": {
        "type": "object",
        "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
        "required": ["topics"],
    },
}


class RubricJudge:
    """Rubric_08 judge adapted to the weekly report. Not used in tests."""

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, *,
                 topics_model: str = DEFAULT_TOPICS_MODEL,
                 threshold: int = SCORE_THRESHOLD,
                 api_key: str | None = None):
        self._model = model
        self._topics_model = topics_model
        self._threshold = threshold
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._topics_llm = None  # lazy: keep import + client construction off the test path

    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict:
        from eval.tutor_judge.run_judge import grade_transcript_payload

        payload = {
            "course": "",            # empty => figure discovery skipped (text-only v1)
            "context": course,       # human-readable subject context for the judge
            "exercise": exercise,
            "exchanges": pairs_to_exchanges(transcript),
        }
        grade = grade_transcript_payload(
            payload, provider="claude", model_name=self._model, api_key=self._api_key,
        )
        topics = self._extract_topics(course, transcript)
        return grade_to_verdict(grade, topics, threshold=self._threshold)

    def _extract_topics(self, course: str, transcript: list[tuple[str, str]]) -> list[str]:
        llm = self._topics_client()
        body = "\n\n".join(f"{role.upper()}: {content}" for role, content in transcript)
        try:
            result = llm.invoke([
                ("system", _TOPICS_SYSTEM),
                ("human", f"Course: {course}\n\nTranscript:\n{body}"),
            ])
            return [str(t) for t in (result.get("topics") or [])][:3]
        except Exception:
            return []  # topics are a nice-to-have; never fail a grade over them

    def _topics_client(self):
        if self._topics_llm is None:
            from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean
            # No temperature: Claude-5 + Haiku accept the default; passing temperature=0
            # 400-errors on Claude-5 models.
            self._topics_llm = ChatAnthropic(
                model=self._topics_model, api_key=self._api_key,
            ).with_structured_output(_TOPICS_SCHEMA)
        return self._topics_llm
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest database_ui/analytics/tests/test_rubric_judge.py -v`
Expected: PASS (all five cases).

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/rubric_judge.py database_ui/analytics/tests/test_rubric_judge.py
git commit -m "feat(analytics): RubricJudge adapter with highlights mapping and topics call"
```

---

### Task B4: Wire the weekly job to `RubricJudge`; restore grade on reuse; remove `AnthropicJudge`

**Files:**
- Modify: `database_ui/analytics/weekly.py` — import (line 20), reuse-Verdict reconstruction (lines 66-71), judge call (line 75), `main()` model default + judge construction (lines 124, 130).
- Modify: `database_ui/analytics/judge.py` — remove `AnthropicJudge` (lines 77-120) and its module-level `_SYSTEM` (lines 63-74). Keep `ISSUE_TYPES`/`SEVERITIES`.
- Test: `database_ui/analytics/tests/test_weekly.py` (add a grade-reuse case; existing `FakeJudge` cases still pass since `run_week` now passes `exercise=`).

**Interfaces:**
- Consumes: `RubricJudge` (Task B3); `Verdict(..., grade=...)` (Task B2).
- Produces: `run_week` reconstructs reused verdicts **with** their stored `grade` (so a cache hit re-serializes the full grade), and calls `judge.judge(course_display_name(conv.course), transcript, exercise=conv.tutor_prompt or conv.focus_problem or "")`. `main()` uses `judge_model` default `claude-sonnet-4-6` and `judge = RubricJudge(judge_model)`.

- [ ] **Step 1: Write the failing test**

Add to `database_ui/analytics/tests/test_weekly.py`:
```python
def test_run_week_persists_and_reuses_grade(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 1))
    graded = Verdict(worked_well=True, one_line="great",
                     grade={"total_score": 36, "max_score": 40, "overview": "great"})
    judge = FakeJudge(default=graded)
    weekly.run_week(session, wk, judge, judge_model="fake",
                    generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc))
    blob = cache_mod.read_cache(wk.key)
    any_conv = next(iter(blob["conversations"].values()))
    assert any_conv["grade"]["total_score"] == 36   # full grade stored

    # Second run with a distinguishable judge: unchanged transcripts reuse the
    # stored verdict, grade included.
    judge2 = FakeJudge(default=Verdict(worked_well=False, one_line="different",
                                       grade={"total_score": 10, "max_score": 40}))
    weekly.run_week(session, wk, judge2, judge_model="fake2",
                    generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc), prior_cache=blob)
    blob2 = cache_mod.read_cache(wk.key)
    reused = next(iter(blob2["conversations"].values()))
    assert reused["grade"]["total_score"] == 36     # reused, not re-judged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest database_ui/analytics/tests/test_weekly.py::test_run_week_persists_and_reuses_grade -v`
Expected: FAIL — on reuse the reconstructed `Verdict` drops `grade` (built without it), so `reused["grade"]` is missing → `KeyError`.

- [ ] **Step 3: Update `weekly.py` reuse + judge call**

In `database_ui/analytics/weekly.py`, change the import on line 20 from:
```python
from database_ui.analytics.judge import AnthropicJudge, Judge, Verdict, transcript_hash
```
to:
```python
from database_ui.analytics.judge import Judge, Verdict, transcript_hash
from database_ui.analytics.rubric_judge import RubricJudge
```

Change the reuse reconstruction (lines 66-71) to restore the grade and the judge call (line 75) to pass the exercise:
```python
        if prior_hashes.get(conv.id) == h and conv.id in prior_verdicts:
            entry = prior_verdicts[conv.id]
            verdict = Verdict(
                worked_well=entry["worked_well"], issues=entry["issues"],
                topics=entry["topics"], one_line=entry["one_line"],
                grade=entry.get("grade"),
            )
        else:
            # Judge sees the human-readable course name (any discipline) for
            # domain context; grouping/storage still keys off conv.course.
            verdict = judge.judge(
                course_display_name(conv.course), transcript,
                exercise=conv.tutor_prompt or conv.focus_problem or "",
            )
```

In `main()`, change line 124 and line 130:
```python
    judge_model = os.environ.get("ANALYTICS_JUDGE_MODEL", "claude-sonnet-4-6")
```
```python
        judge = RubricJudge(judge_model)
```

- [ ] **Step 4: Remove `AnthropicJudge` and `_SYSTEM` from `judge.py`**

In `database_ui/analytics/judge.py`, delete the `_SYSTEM` string constant (lines 63-74) and the entire `AnthropicJudge` class (lines 77-120). Leave `ISSUE_TYPES`, `SEVERITIES`, `Verdict`, `transcript_hash`, `Judge`, and `FakeJudge` in place.

- [ ] **Step 5: Run the analytics suite**

Run: `python -m pytest database_ui/analytics/tests/ -v`
Expected: PASS — the new reuse-grade test, both existing `test_weekly` cases (now exercising the `exercise=` kwarg through `FakeJudge`), and `test_judge` all green. Confirm no import of `AnthropicJudge` remains: `python -c "import database_ui.analytics.weekly"` imports cleanly.

- [ ] **Step 6: Commit**

```bash
git add database_ui/analytics/weekly.py database_ui/analytics/judge.py database_ui/analytics/tests/test_weekly.py
git commit -m "feat(analytics): weekly job uses RubricJudge and reuses stored grades"
```

---

### Task B5: Report highlights — score column + average rubric score

**Files:**
- Modify: `database_ui/analytics/flags.py` (`build_flags`, lines 14-53) — add per-item `score` and a dict-level `avg_score`.
- Modify: `database_ui/analytics/report.py` (`render_report`, lines 35-48 table; lines 57-62 Meta) — add a Score column and an average-score Meta line.
- Test: `database_ui/analytics/tests/test_flags.py`, `database_ui/analytics/tests/test_report.py`.

**Interfaces:**
- Consumes: `Verdict.grade` (Task B2).
- Produces: `build_flags(...)` result gains `"avg_score": float | None` (mean `total_score` across verdicts that have a grade; `None` if none do) and each `items[i]` gains `"score": int | None` (that conversation's `grade.total_score`, or `None`). `render_report` renders a `Score` column (`N/40` or blank) in the "Didn't work well" table and a Meta line `- Average rubric score: X.X/40 (n graded).` when `avg_score is not None`.

- [ ] **Step 1: Write the failing tests**

Add to `database_ui/analytics/tests/test_flags.py` (import `Verdict` if not already imported):
```python
def test_build_flags_adds_score_and_avg_score():
    from database_ui.analytics.data import ConvRow, MsgRow
    from database_ui.analytics.flags import build_flags
    from database_ui.analytics.judge import Verdict

    conv = ConvRow(id="c1", course="physics", username="u1", exercise_number="1",
                   exercise_kind="lecture", focus_problem="", tutor_prompt="",
                   started_at=None, last_active_at=None)
    verdicts = {
        "c1": Verdict(worked_well=False, one_line="bad",
                      grade={"total_score": 20, "max_score": 40}),
        "c2": Verdict(worked_well=True, one_line="ok",
                      grade={"total_score": 40, "max_score": 40}),
    }
    flags = build_flags([conv], [], verdicts)
    assert flags["avg_score"] == 30.0                 # mean(20, 40)
    item = next(i for i in flags["items"] if i["id"] == "c1")
    assert item["score"] == 20
```
(If `test_flags.py` already builds `ConvRow`s with a helper, reuse that helper instead of constructing inline — match the file's existing style. Include every `ConvRow` field: `id, course, username, exercise_number, exercise_kind, focus_problem, tutor_prompt, started_at, last_active_at`.)

Add to `database_ui/analytics/tests/test_report.py`:
```python
def test_report_shows_score_column_and_average(sample_report_args):
    # sample_report_args: reuse whatever fixture/factory this file already uses to
    # call render_report. Ensure flags carries avg_score and an item with score.
    ...
```
If `test_report.py` has no such fixture, write a direct call instead:
```python
def test_report_shows_score_column_and_average():
    from datetime import date
    from database_ui.analytics.report import render_report
    from database_ui.analytics.weeks import week_containing

    wk = week_containing(date(2026, 5, 1))
    stats = {
        "usage": {"conversations": 1, "unique_students": 1, "new_students": 1, "returning_students": 0},
        "ratings": {"positive_rate": 1.0, "up": 1, "down": 0, "pct_turns_rated": 1.0},
        "cost": {"total_usd": 0.0, "per_conversation_usd": 0.0, "model_mix": {}},
        "content": {"rag_rate": 0.0},
    }
    flags = {
        "items": [{"id": "c1", "course": "physics", "exercise": "lecture:1", "student": "u1",
                   "source": "judge", "issue_type": "1.1.A.a", "severity": "high",
                   "quote": "gave answer", "one_line": "bad", "score": 20}],
        "counts_by_issue": {}, "thumbs_down": 0, "judge_flagged": 1, "overlap": 0,
        "avg_score": 30.0,
    }
    md = render_report(wk, stats, {}, flags, {}, judged_count=2, judge_model="claude-sonnet-4-6", skipped=0)
    assert "| Score |" in md                     # new column header
    assert "20/40" in md                          # per-row score
    assert "Average rubric score: 30.0/40" in md  # Meta line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest database_ui/analytics/tests/test_flags.py database_ui/analytics/tests/test_report.py -v`
Expected: FAIL — `flags["avg_score"]`/`item["score"]` missing (`KeyError`), and the report lacks the `Score` column / average line.

- [ ] **Step 3: Update `flags.py`**

In `database_ui/analytics/flags.py`, inside `build_flags`, compute the per-item score and the average. Add `score` to each appended item:
```python
        verdict = verdicts.get(cid)
        grade = getattr(verdict, "grade", None) if verdict else None
        score = None
        if isinstance(grade, dict) and isinstance(grade.get("total_score"), int):
            score = grade["total_score"]
```
then include `"score": score,` in the `items.append({...})` dict (add the key alongside `one_line`). After the loop, before the `return`, compute the average across all graded verdicts:
```python
    graded_scores = [
        v.grade["total_score"] for v in verdicts.values()
        if isinstance(getattr(v, "grade", None), dict)
        and isinstance(v.grade.get("total_score"), int)
    ]
    avg_score = round(sum(graded_scores) / len(graded_scores), 1) if graded_scores else None
```
and add `"avg_score": avg_score,` to the returned dict.

- [ ] **Step 4: Update `report.py`**

In `database_ui/analytics/report.py`, change the table header/separator (lines 41-42) to add a Score column, and render the score per row (lines 43-47):
```python
        lines.append("| Course | Exercise | Student | Issue | Severity | Score | Note |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i in flags["items"][:25]:
            note = (i["one_line"] or i["quote"]).replace("\n", " ").replace("\r", " ")
            note = note.replace("|", "\\|")[:80]
            score = f"{i['score']}/40" if i.get("score") is not None else ""
            lines.append(f"| {course_display_name(i['course'])} | {i['exercise']} | "
                         f"{i['student']} | {i['issue_type']} | {i['severity']} | {score} | {note} |")
```
In the Meta block (after line 60), add the average line when present:
```python
    if flags.get("avg_score") is not None:
        graded = flags.get("judge_flagged", 0)  # informational count; see note below
        lines.append(f"- Average rubric score: {flags['avg_score']}/40 ({judged_count} graded).")
```
(Use `judged_count` as the graded denominator — every judged conversation gets a grade. Drop the unused `graded` local if the reviewer flags it; keep the line exactly as: `f"- Average rubric score: {flags['avg_score']}/40 ({judged_count} graded)."`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest database_ui/analytics/tests/test_flags.py database_ui/analytics/tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add database_ui/analytics/flags.py database_ui/analytics/report.py database_ui/analytics/tests/test_flags.py database_ui/analytics/tests/test_report.py
git commit -m "feat(analytics): report shows rubric score column and weekly average"
```

---

### Task B6: Dashboard flagged-list highlights (score + overview) + grade passthrough test

**Files:**
- Modify: `database_ui/static/js/analytics.js` (the "Didn't work well" render block at lines 130-133, which currently shows only a count).
- Modify: `database_ui/templates/analytics.html` (bump `analytics.js` `?v=` at line 30).
- Modify: `database_ui/templates/index.html` (bump `analytics.js` `?v=` at line 114 — must match analytics.html).
- Test: `database_ui/tests/test_analytics_routes.py` (add a grade-passthrough assertion).

**Interfaces:**
- Consumes: the cache's per-conversation dict, now `{course, worked_well, issues, topics, one_line, grade?}`; `grade.total_score`/`grade.max_score` when present.
- Produces: the flagged panel lists each `!worked_well` conversation as a compact row — course, `score/40` (blank when no grade), and the `one_line` overview — with a leading count. Old caches without `grade` render the row with no score (no crash). The `/api/analytics` response continues to include `grade` on conversations that have it.

- [ ] **Step 1: Write the failing passthrough test**

Add to `database_ui/tests/test_analytics_routes.py` (follow the file's existing app/client fixture + cache-seeding pattern — the assertion is what matters):
```python
def test_api_analytics_passes_through_conversation_grade(client, monkeypatch, tmp_path):
    # Seed one week's cache with a graded, flagged conversation, then hit the API.
    # (Reuse this file's existing cache-writing/seeding helper; the key assertion:)
    payload = client.get("/api/analytics?week=<seeded_week_key>").get_json()
    conv = next(iter(payload["cached"]["conversations"].values()))
    assert "grade" in conv
    assert conv["grade"]["total_score"] == <seeded_score>
```
If the file already has a helper that writes a cache blob and a known week key, use it and assert `grade` survives `filter_cache` (it does — `filter_cache` copies each conversation dict unchanged). If no helper exists, write the cache blob with `cache_mod.write_cache` into a `monkeypatch`-ed `cache_mod.CACHE_DIR = tmp_path`, using a `conversations` dict whose one entry includes `"grade": {"total_score": 22, "max_score": 40}` and `"course"` in the client's allowed scope.

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest database_ui/tests/test_analytics_routes.py -k grade -v`
Expected: This asserts existing passthrough behavior. If it PASSES immediately, that confirms `filter_cache` preserves `grade` — keep the test as a regression guard and proceed to the JS change (note in the commit that no route code changed). If it FAILS, `filter_cache` is dropping fields — fix `filter_cache` to preserve the full conversation dict before continuing.

- [ ] **Step 3: Update the flagged-list rendering in `analytics.js`**

Replace the count-only flagged block (lines 130-133) so it lists highlights. Current code resembles:
```javascript
const flags = Object.values(cached.conversations).filter(c => !c.worked_well);
// ... renders: flags.length + " conversations flagged."
```
Change it to render a compact list (match the file's existing DOM-building idiom — `document.createElement` vs template strings — do not introduce a new style):
```javascript
const flags = Object.values(cached.conversations).filter(c => !c.worked_well);
let html = `<p>${flags.length} conversation${flags.length === 1 ? "" : "s"} flagged.</p>`;
if (flags.length) {
  html += "<ul class='flagged-list'>";
  for (const c of flags) {
    const g = c.grade;
    const score = g && typeof g.total_score === "number"
      ? `${g.total_score}/${g.max_score || 40}` : "";
    const note = (c.one_line || "").replace(/</g, "&lt;");
    html += `<li><span class="flag-course">${c.course}</span>`
          + (score ? ` <span class="flag-score">${score}</span>` : "")
          + (note ? ` — ${note}` : "") + "</li>";
  }
  html += "</ul>";
}
// assign html into the same container element the old count used
```
Preserve whatever container element and assignment target the current code uses; only the produced markup changes.

- [ ] **Step 4: Bump the `analytics.js` cache-buster at both include sites**

In `database_ui/templates/analytics.html` line 30 and `database_ui/templates/index.html` line 114, bump the `analytics.js` version from `v='12'` to `v='13'` (they must stay identical).

- [ ] **Step 5: Run the route test + full analytics suites**

Run:
```bash
python -m pytest database_ui/tests/test_analytics_routes.py -v
python -m pytest database_ui/analytics/tests/ -v
```
Expected: PASS (grade passthrough guarded; nothing else regressed).

- [ ] **Step 6: Manual visual check (operator step, record in PR)**

Load `/analytics` (and the dashboard `#analytics-panel`) against a week whose cache has grades; confirm the flagged list shows `course · score/40 · overview` and that an older week (no grades) still renders without error. This is a manual check — note it in the PR body.

- [ ] **Step 7: Commit**

```bash
git add database_ui/static/js/analytics.js database_ui/templates/analytics.html database_ui/templates/index.html database_ui/tests/test_analytics_routes.py
git commit -m "feat(database_ui): flagged-list shows rubric score and overview highlights"
```

---

## Self-Review

**Spec coverage**

- "Use our rubric judge (rubric_08/judge_08), not the lightweight one" → Tasks B1, B3, B4.
- "Full grading stored, highlights only shown" → grade stored (B4 cache, via B2 `Verdict.grade`), highlights in report (B5) and dashboard (B6).
- "Keep a cheap topics call" → B3 `RubricJudge._extract_topics` on a cheap model, no temperature.
- "Flag at < 32/40 (80%)" → B3 `SCORE_THRESHOLD = 32`, `grade_to_verdict`.
- "Replace the old judge" → B4 removes `AnthropicJudge`.
- "Cost breakdown / model" → Global Constraints locks `claude-sonnet-4-6` (calibrated + temperature-compatible); prompt caching already built in (system prompt `cache_control: ephemeral`).
- "Run at end of week, deploy automatically" → A2 keeps Sunday `0 8 * * 0` cron and auto-merges.
- "Remove branch logic / deploy automatically" → A2 open-PR-and-merge with `GITHUB_TOKEN`.
- "Collaborators must PR; owner and code can push/merge without review" → A1 ruleset (PR required, 0 approvals, admin bypass), A2 bot self-merges.

**Placeholder scan** — B5 Step 1 and B6 Step 1 intentionally defer to each test file's existing fixtures because those fixtures' exact names can't be known without the files open; both provide a complete fallback (direct `render_report` call / direct cache write) that is fully specified. The implementer uses the fallback if no fixture exists. No other placeholders.

**Type consistency** — `grade_transcript_payload` signature is identical in B1 (produced) and B3 (consumed). `Verdict(..., grade=None)` and `as_dict` gating on `grade is not None` are consistent across B2, B4, B5. `judge(self, course, transcript, *, exercise="")` is identical in B2 (protocol/Fake), B3 (RubricJudge), and B4 (call site). `flags["avg_score"]` / `items[i]["score"]` names match between B5 producer (`flags.py`) and consumers (`report.py`, tests). `SCORE_THRESHOLD = 32` single source in B3.

---

## Notes for the executor

- **Order matters:** B1 → B2 → B3 → B4 → B5 → B6. B4 both swaps `weekly.py` to `RubricJudge` and removes `AnthropicJudge` in the same task so no intermediate state has a dangling import. Workstream A (A1, A2) is independent of B and can run before, after, or in parallel — but do **not** create the ruleset (A1) until you intend the workflow change (A2) to follow, so the deploy path is never half-configured.
- **Cost (verified estimate, `claude-sonnet-4-6`, prompt caching on):** rubric judge ≈ \$2/week for a typical week; the cheap topics call adds roughly \$0.10/week; a full-history backfill ≈ \$5. Pricing assumes sonnet-tier \$3/\$15 per Mtok — confirm against `utils/pricing.py` before quoting externally.
- **Do not** run the weekly job against production during implementation; use `--max-convos 2` for any live smoke test, and only after the owner approves.
