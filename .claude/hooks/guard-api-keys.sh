#!/usr/bin/env bash
# PreToolUse guard: force a permission prompt (ask) before any command that
# could spend a PROJECT API key (OpenAI / Anthropic / embeddings). Reads the
# hook payload on stdin and greps it for key-using patterns. On a match it
# emits permissionDecision "ask" so the user approves or denies per run; on no
# match it stays silent so normal permission flow proceeds. No jq dependency.
payload="$(cat)"

if printf '%s' "$payload" | grep -Eqi \
  'run_ui_raw|run_ui_judge|run_judge|rag[._ ]ingest|rag\.embeddings|OpenAIEmbeddings|text-embedding|OPENAI_API_KEY|ANTHROPIC_API_KEY|EMBEDDING_MODEL|\.invoke\(|\.stream\(|get_next_student_message|get_tutor_reply|stream_tutor_reply|build_tutor_model|build_graph\('; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"This command may use a PROJECT API key (OpenAI / Anthropic / embeddings) and cost money. Approve ONLY if you intend to run it; otherwise Deny."}}'
fi

exit 0
