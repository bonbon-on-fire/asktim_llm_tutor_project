"""Batch-mode bulk judging via the raw Anthropic / OpenAI Batch APIs (~50% cheaper).

Offline grading is latency-insensitive and every transcript is independent, so
the async Batch API is a natural fit. We build one request per transcript,
submit a single batch, poll to completion, then validate + write each grade.

Robustness: anything that can't go through the batch cleanly falls back to the
synchronous judge (`run_judge.judge_transcript`, which has the repair loop) —
that covers (a) transcripts carrying curriculum figures (kept text-only in
batch), (b) individual results that fail validation, and (c) a batch submission
or polling error, in which case the *whole* set degrades to sync. So a run never
breaks; worst case it loses the discount. `--live` on the runner forces sync.

Batches complete within 24h (usually minutes); this polls in the foreground, so
it is meant for offline runs, not an interactive path.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eval.tutor_judge.run_judge import (
    JudgeError,
    JudgeResult,
    TRANSCRIPTS_DIR,
    _env_truthy,
    _format_conversation_for_judge,
    _order_grade_payload,
    _parse_json_from_model_output,
    _sanitize_grade_payload,
    _sanitize_text,
    _validate_grade_payload,
    judge_transcript,
    load_judge_prompt,
)
from utils.pricing import priced

# Poll cadence for the foreground wait. Batches finish within 24h; most in minutes.
_POLL_INTERVAL_S = 20
_MAX_WAIT_S = 24 * 3600
_MAX_TOKENS = 4096  # judge grade JSON is small; matches the sync path's headroom

_ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0}


def _load_transcript(stem: str) -> tuple[dict[str, Any], Path]:
    path = TRANSCRIPTS_DIR / f"{stem}.json"
    if not path.exists():
        raise JudgeError(f"Transcript not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    exchanges = data.get("exchanges") if isinstance(data, dict) else None
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain non-empty 'exchanges' list.")
    return data, path


def _has_figures(transcript: dict[str, Any]) -> bool:
    figs = transcript.get("figures")
    return isinstance(figs, list) and bool(figs)


def _write_grade(
    grade_json: dict[str, Any],
    *,
    transcript: dict[str, Any],
    transcript_path: Path,
    provider: str,
    model_name: str,
    reasoning: str,
    output_name: str | None,
    usage: dict[str, int],
) -> JudgeResult:
    """Mirror of run_judge._judge_transcript's grade assembly + write, for batch results."""
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
    grade_payload["judge_llm_calls"] = 1  # batch is a single non-retrying pass
    grade_payload["token_usage"] = usage or dict(_ZERO_USAGE)
    grade_payload["cost_estimate"] = priced(model_name, grade_payload["token_usage"])
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_doc = dict(transcript)
    out_doc.pop("grade", None)
    out_doc["grade"] = grade_payload
    out_name = f"{output_name}.json" if output_name else transcript_path.name
    out_path = transcript_path.with_name(out_name)
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=out_path,
    )


def _validate_text(raw_text: str) -> dict[str, Any]:
    """Parse + sanitize + validate one raw judge response into an ordered grade payload."""
    parsed = _parse_json_from_model_output(_sanitize_text(raw_text))
    return _order_grade_payload(_validate_grade_payload(_sanitize_grade_payload(parsed)))


# --------------------------------------------------------------------------
# Provider batch calls — return {custom_id: (raw_text, usage_dict)}
# --------------------------------------------------------------------------


def _anthropic_batch(reqs: dict[str, tuple[str, str]], *, model: str, api_key: str, log: Callable[[str], None]) -> dict[str, tuple[str, dict]]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    requests = [
        {
            "custom_id": cid,
            "params": {
                "model": model,
                "max_tokens": _MAX_TOKENS,
                "temperature": 0,
                # Cache the rubric prefix across the batch (same as the sync path).
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user}],
            },
        }
        for cid, (system, user) in reqs.items()
    ]
    batch = client.messages.batches.create(requests=requests)
    log(f"submitted Anthropic batch {batch.id} ({len(requests)} requests)")
    waited = 0
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        if waited >= _MAX_WAIT_S:
            raise JudgeError(f"Anthropic batch {batch.id} unfinished after {_MAX_WAIT_S}s")
        time.sleep(_POLL_INTERVAL_S)
        waited += _POLL_INTERVAL_S

    out: dict[str, tuple[str, dict]] = {}
    for r in client.messages.batches.results(batch.id):
        if r.result.type != "succeeded":
            continue  # errored/expired/canceled → left out, routed to sync fallback
        msg = r.result.message
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        u = msg.usage
        usage = {
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0),
            "cache_write": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        }
        out[r.custom_id] = (text, usage)
    return out


def _openai_batch(reqs: dict[str, tuple[str, str]], *, model: str, reasoning: str, api_key: str, log: Callable[[str], None]) -> dict[str, tuple[str, dict]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    lines: list[str] = []
    for cid, (system, user) in reqs.items():
        body: dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if reasoning in {"low", "medium", "high"}:
            body["reasoning_effort"] = reasoning
        lines.append(json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/chat/completions", "body": body}))
    jsonl = ("\n".join(lines)).encode("utf-8")

    upload = client.files.create(file=("judge_batch.jsonl", jsonl), purpose="batch")
    batch = client.batches.create(
        input_file_id=upload.id, endpoint="/v1/chat/completions", completion_window="24h"
    )
    log(f"submitted OpenAI batch {batch.id} ({len(lines)} requests)")
    waited = 0
    while True:
        b = client.batches.retrieve(batch.id)
        if b.status == "completed":
            break
        if b.status in {"failed", "expired", "cancelled"}:
            raise JudgeError(f"OpenAI batch {batch.id} ended with status={b.status}")
        if waited >= _MAX_WAIT_S:
            raise JudgeError(f"OpenAI batch {batch.id} unfinished after {_MAX_WAIT_S}s")
        time.sleep(_POLL_INTERVAL_S)
        waited += _POLL_INTERVAL_S

    content = client.files.content(b.output_file_id).text
    out: dict[str, tuple[str, dict]] = {}
    for line in content.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid = rec.get("custom_id")
        resp = rec.get("response") or {}
        if resp.get("status_code") != 200:
            continue
        rbody = resp.get("body") or {}
        try:
            text = rbody["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            continue
        u = rbody.get("usage") or {}
        usage = {
            "input_tokens": int(u.get("prompt_tokens", 0) or 0),
            "output_tokens": int(u.get("completion_tokens", 0) or 0),
            "cache_read": int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0),
            "cache_write": 0,
        }
        out[cid] = (text, usage)
    return out


# --------------------------------------------------------------------------
# Public orchestrator
# --------------------------------------------------------------------------


def judge_transcripts_batch(
    items: list[tuple[str, str | None]],
    *,
    provider: str,
    prompt_name: str,
    rubric_name: str,
    model_name: str,
    api_key: str,
    reasoning: str,
    log: Callable[[str], None] = lambda _m: None,
) -> dict[str, JudgeResult]:
    """Grade `items` (list of (transcript_stem, output_name)) via the Batch API.

    Returns {stem: JudgeResult}. Transcripts with figures, results that fail
    validation, and (on a batch/submission error) the entire set fall back to the
    synchronous `judge_transcript`. Raises only if a transcript is unreadable.
    """
    reqs: dict[str, tuple[str, str]] = {}
    ctx: dict[str, dict[str, Any]] = {}
    fallback: list[tuple[str, str | None]] = []
    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)

    for stem, output_name in items:
        try:
            transcript, path = _load_transcript(stem)
        except JudgeError as exc:
            log(f"skip {stem}: {exc}")  # unreadable transcript — don't abort the batch
            continue
        if _has_figures(transcript):
            fallback.append((stem, output_name))  # keep multimodal grading on the sync path
            continue
        cid = stem.replace("/", "__")  # custom_id must be filesafe/opaque
        reqs[cid] = (system_prompt, _format_conversation_for_judge(transcript))
        ctx[cid] = {"stem": stem, "output_name": output_name, "transcript": transcript, "path": path}

    raw: dict[str, tuple[str, dict]] = {}
    if reqs:
        try:
            if provider == "claude":
                raw = _anthropic_batch(reqs, model=model_name, api_key=api_key, log=log)
            else:
                raw = _openai_batch(reqs, model=model_name, reasoning=reasoning, api_key=api_key, log=log)
        except Exception as exc:  # submission/poll failure → whole set to sync
            log(f"batch failed ({type(exc).__name__}: {exc}); falling back to sync for all")
            for cid, c in ctx.items():
                fallback.append((c["stem"], c["output_name"]))
            reqs = {}

    results: dict[str, JudgeResult] = {}
    for cid, c in ctx.items():
        got = raw.get(cid)
        if got is None:
            fallback.append((c["stem"], c["output_name"]))
            continue
        text, usage = got
        try:
            grade_json = _validate_text(text)
        except JudgeError:
            fallback.append((c["stem"], c["output_name"]))  # bad JSON → sync repair loop
            continue
        results[c["stem"]] = _write_grade(
            grade_json,
            transcript=c["transcript"],
            transcript_path=c["path"],
            provider=provider,
            model_name=model_name,
            reasoning=reasoning,
            output_name=c["output_name"],
            usage=usage,
        )

    if fallback:
        log(f"sync fallback for {len(fallback)} transcript(s)")
    for stem, output_name in fallback:
        results[stem] = judge_transcript(
            stem,
            provider=provider,
            prompt_name=prompt_name,
            rubric_name=rubric_name,
            output_name=output_name,
        )
    return results
