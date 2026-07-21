"""Adapter presenting MIT's STEM AskTIM through our ``get_tutor_reply`` seam.

The vendored MIT tutor (``_stem_asktim/open_learning_ai_tutor``) has a very
different calling convention from ours: it threads three histories turn-to-turn,
runs *two* model calls per turn (a blocking assessment, then the reply), and
exposes only an async streaming generator. This module wraps all of that behind
the one signature our simulators already call::

    get_tutor_reply(messages, graph=..., retrieved_context="") -> (messages, text)

so ``internal_testing.run_transcript_rag`` can drive either tutor without caring
which one is on the other end, and the resulting transcripts stay judge- and
visualization-compatible.

Deliberate choices for the 07/21 comparison round (see meeting_notes/2026-07-21.md):

* **No retrieval.** ``retrieved_context`` is accepted and ignored — round one
  runs the STEM tutor without lecture context, which is how it ships. The
  same-RAG rerun is a follow-up.
* **Same underlying model.** We build the client with our own
  ``tutor.run_tutor.build_tutor_model``, so the only variable between the two
  arms is tutor *design*, not model choice.
* **No tools.** The upstream default is ``[execute_python, python_calculator]``,
  which runs unsandboxed ``PythonREPL`` from a module-level shared instance —
  state would leak across parallel conversations. We pass ``[]``.
* **LangSmith off.** With ``LANGSMITH_API_KEY`` set, upstream silently pulls
  prompts from LangSmith instead of its in-repo templates, which would make runs
  irreproducible. We unset it for the process and say so.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from tutor.run_tutor import build_tutor_model
from utils.curriculum import SOLUTION_CONTEXT_LABEL, read_solution

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STEM_PKG_ROOT = _REPO_ROOT / "_stem_asktim"

# The vendored package is not installed (no setup.py run, not on the path); it's
# a plain source drop, so make it importable by root rather than vendoring again.
if str(_STEM_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_STEM_PKG_ROOT))

from open_learning_ai_tutor.message_tutor import message_tutor  # noqa: E402


def _merge_system_messages(messages: list) -> list:
    """Hoist every SystemMessage into a single leading one, order preserved.

    Upstream builds its reply prompt as ``[System(problem), *chat, System(intent)]``,
    which is fine on OpenAI but which Anthropic rejects outright — it lifts system
    content into a top-level parameter and refuses "multiple non-consecutive system
    messages". Concatenating them into one leading SystemMessage is the native
    Anthropic translation of the same prompt.

    This does move the intent instruction from last position to first, which can
    weaken instruction salience. Run with ``--provider gpt`` to drive upstream
    completely unmodified if that difference is ever in question.
    """
    system_parts = [
        m.content if isinstance(m.content, str) else str(m.content)
        for m in messages
        if isinstance(m, SystemMessage)
    ]
    rest = [m for m in messages if not isinstance(m, SystemMessage)]
    if not system_parts:
        return rest
    return [SystemMessage(content="\n\n".join(system_parts)), *rest]


class _AnthropicCompatClient:
    """Thin proxy making upstream's OpenAI-shaped prompts valid for Anthropic.

    ``Tutor`` only ever calls ``bind_tools`` and ``invoke`` on its client, so those
    are the only two surfaces we need. Also skips ``bind_tools`` entirely when the
    tool list is empty — binding an empty array is a no-op that some providers
    reject.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def bind_tools(self, tools):
        inner = self._inner.bind_tools(tools) if tools else self._inner
        return _AnthropicCompatClient(inner)

    def invoke(self, messages, *args, **kwargs):
        return self._inner.invoke(_merge_system_messages(messages), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _disable_langsmith_prompt_pull() -> bool:
    """Drop ``LANGSMITH_API_KEY`` from the environment; return whether it was set.

    Upstream ``prompts.py`` treats the presence of this key as "fetch prompts from
    LangSmith", and pushes any missing prompt *into* the caller's LangSmith account.
    Either behaviour would make a comparison run unreproducible, so we force the
    local templates.
    """
    return os.environ.pop("LANGSMITH_API_KEY", None) is not None


class StemTutorAdapter:
    """One STEM AskTIM conversation, exposed through our tutor-reply signature.

    Holds the three histories upstream threads between turns (``chat_history``,
    ``assessment_history``, ``intent_history``) so the caller can stay stateless,
    and records per-turn assessment/intent so a silently-defaulting assessor is
    visible in the transcript rather than mistaken for real tutoring.
    """

    def __init__(
        self,
        *,
        course: str,
        kind: str,
        number: str,
        problem_text: str,
        turn_size: int,
        provider: str = "claude",
        tools: list | None = None,
        include_solution: bool = False,
    ) -> None:
        self.course = course
        self.kind = kind
        self.number = number
        self.provider = provider
        # Upstream's `tools` arg is positional with no default; [] disables the
        # PythonREPL tools without changing their code.
        self.tools = tools if tools is not None else []
        self.langsmith_was_set = _disable_langsmith_prompt_pull()

        # Same model as our own tutor, so the only variable between the two arms is
        # tutor design. Claude needs the message-shape proxy; GPT runs upstream's
        # prompt structure verbatim.
        model = build_tutor_model(provider=provider)
        self.client = _AnthropicCompatClient(model) if provider == "claude" else model
        self.problem_set = self._build_problem_set(problem_text, turn_size, include_solution)

        self.chat_history: list[BaseMessage] = []
        self.assessment_history: list[BaseMessage] = []
        self.intent_history: list[list] = []

        # Populated each turn — the caller reads these for the transcript.
        self.last_reasoning: str = ""
        self.last_assessment_raw: str = ""
        self.last_intents: list[str] = []
        self.last_assessment_message: AIMessage | None = None
        self.last_reply_message: AIMessage | None = None

    # ----------------------------------------------------------------- #
    # Problem framing
    # ----------------------------------------------------------------- #

    def _build_problem_set(self, problem_text: str, turn_size: int, include_solution: bool) -> str:
        """Assemble the ``problem_set`` blob upstream interpolates into its prompt.

        We use ``variant="canvas"``, whose template takes free-form text; the
        default ``"edx"`` variant asserts the payload is XML, which ours isn't.

        The solution key is withheld by default as of 2026-07-21, matching what our
        own tutor now gets (see ui_core.tutor_bridge.build_assignment_text) — the
        arms have to see the same material for the comparison to mean anything.
        Note the cost: upstream's assessment codes (WRONG, COMPLETE_SOLUTION, ...)
        are only confidently assignable with the answer in hand, and a
        solution-blind assessor degrades *silently*. Pass include_solution=True to
        measure that difference deliberately.
        """
        parts = [f"{'Practice problem' if self.kind == 'practice' else 'Exercise'}:\n{problem_text}"]
        if include_solution:
            solution = read_solution(self.course, self.number, kind=self.kind)
            if solution.strip():
                parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())
        parts.append(
            "Run configuration:\n- Planned conversation length: "
            f"{turn_size} student+tutor exchanges."
        )
        return "\n\n".join(parts)

    # ----------------------------------------------------------------- #
    # Streaming drain
    # ----------------------------------------------------------------- #

    @staticmethod
    async def _drain(stream) -> AIMessage | None:
        """Consume upstream's ``astream`` and return the final assistant message.

        ``get_streaming_response`` yields ``(mode, chunk)`` under
        ``stream_mode=["messages", "values"]``. The last ``values`` chunk carries
        the complete graph state, so we take its trailing AIMessage rather than
        reassembling token deltas — that also skips any tool-call round trips
        cleanly if tools are ever re-enabled.
        """
        final: AIMessage | None = None
        async for mode, chunk in stream:
            if mode != "values":
                continue
            messages = chunk.get("messages") if isinstance(chunk, dict) else None
            if not messages:
                continue
            last = messages[-1]
            if isinstance(last, AIMessage):
                final = last
        return final

    # ----------------------------------------------------------------- #
    # The seam
    # ----------------------------------------------------------------- #

    def reply(
        self,
        messages: list,
        *,
        graph=None,  # noqa: ARG002 - accepted for signature parity, unused
        retrieved_context: str = "",  # noqa: ARG002 - round one is deliberately no-context
    ) -> tuple[list, str]:
        """Answer the latest student turn, mirroring ``tutor.run_tutor.get_tutor_reply``.

        Only the trailing message of *messages* is read (the new student turn);
        conversational state lives in this adapter's own histories. Returns the
        caller's list with our reply appended, plus the reply text.
        """
        if not messages:
            raise ValueError("StemTutorAdapter.reply requires at least one message.")
        student_text = messages[-1].content
        if not isinstance(student_text, str):
            student_text = str(student_text)

        new_messages = [HumanMessage(content=student_text)]

        # `new_messages` feeds only the assessment call; the reply prompt is built
        # from `chat_history` alone, so the student's turn has to already be in it.
        # Without this the turn-1 prompt is two SystemMessages and nothing else,
        # which Anthropic rejects outright ("at least one message is required").
        self.chat_history.append(HumanMessage(content=student_text))

        # Upstream mutates the list it's handed (inserts/appends SystemMessages),
        # so pass a copy and keep our own history clean of prompt scaffolding.
        stream, new_intent_history, new_assessment_history = message_tutor(
            problem="",  # ignored by the canvas variant
            problem_set=self.problem_set,
            client=self.client,
            new_messages=new_messages,
            chat_history=list(self.chat_history),
            assessment_history=list(self.assessment_history),
            intent_history=list(self.intent_history),
            tools=self.tools,
            variant="canvas",
        )

        reply_message = asyncio.run(self._drain(stream))
        if reply_message is None:
            raise RuntimeError("STEM tutor returned no assistant message.")

        reply_text = reply_message.content
        if not isinstance(reply_text, str):
            reply_text = str(reply_text)

        # message_tutor returns updated intent/assessment histories but never an
        # updated chat_history — the student turn went in above, the reply here.
        self.chat_history.append(AIMessage(content=reply_text))
        self.assessment_history = [
            m for m in new_assessment_history if not isinstance(m, SystemMessage)
        ]
        self.intent_history = new_intent_history

        self._record_turn_metadata(new_assessment_history, new_intent_history, reply_message)

        return [*messages, reply_message], reply_text

    def _record_turn_metadata(
        self, assessment_history: list, intent_history: list, reply_message: AIMessage
    ) -> None:
        """Capture this turn's assessment JSON and intents for the transcript.

        The raw assessment is kept verbatim because upstream fails soft: bad JSON
        falls back to ASKING_FOR_CONCEPTS and an unmatched code falls through to
        S_STRATEGY, both of which read as plausible tutoring downstream. Logging
        it is what distinguishes "engaged and did poorly" from "never engaged".
        """
        self.last_reply_message = reply_message
        raw = ""
        if assessment_history:
            last = assessment_history[-1]
            self.last_assessment_message = last if isinstance(last, AIMessage) else None
            raw = last.content if isinstance(last.content, str) else str(last.content)
        self.last_assessment_raw = raw

        intents = intent_history[-1] if intent_history else []
        self.last_intents = [getattr(i, "name", str(i)) for i in intents]

        justification = ""
        selection = ""
        parse_error = ""
        try:
            parsed = json.loads(raw)
            justification = str(parsed.get("justification", ""))
            selection = str(parsed.get("selection", ""))
        except (json.JSONDecodeError, TypeError, AttributeError) as error:
            # Not fatal upstream — it silently defaults. Surface it here instead.
            parse_error = f"{type(error).__name__}: {error}"

        # Slots into the transcript's existing ``pedagogical_reasoning`` field: this
        # is the STEM tutor's analogue, and the judge strips that field before
        # grading, so it can't bias scores.
        self.last_reasoning = json.dumps(
            {
                "intents": self.last_intents,
                "assessment_selection": selection,
                "assessment_justification": justification,
                **({"assessment_parse_error": parse_error} if parse_error else {}),
                **({"assessment_raw": raw} if parse_error else {}),
            },
            ensure_ascii=False,
        )

    def get_tutor_reply(self, messages: list, **kwargs) -> tuple[list, str]:
        """Alias matching the upstream free-function name, for drop-in substitution."""
        return self.reply(messages, **kwargs)
