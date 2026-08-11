"""Live proof that cached-mode history caches. Run manually with real keys:
    TUTOR_CACHED_HISTORY=1 PYTHONPATH=. python -m internal_testing.smoke_cached_history
Sends a 2-turn Claude conversation via the raw request builder and prints usage;
turn 2 should show cache_read_input_tokens > 0."""
import anthropic
from tutor.run_tutor import _require_anthropic_api_key, load_system_prompt, build_anthropic_request
from tutor.cached_history import build_message_plan, tutor_output_json

client = anthropic.Anthropic(api_key=_require_anthropic_api_key())
sysprompt = load_system_prompt("tutor_07", assignment_override="Exercise: intro.")

def run(plan, label):
    """Send *plan* to Claude and print its cache-read, cache-write, and input token usage under *label*."""
    system_blocks, messages = build_anthropic_request(plan)
    r = client.messages.create(model="claude-sonnet-5", max_tokens=64, system=system_blocks, messages=messages)
    u = r.usage
    print(f"{label}: cache_read={getattr(u,'cache_read_input_tokens',0)} "
          f"cache_write={getattr(u,'cache_creation_input_tokens',0)} input={u.input_tokens}")

# Turn 1: writes the prefix to cache
plan1 = build_message_plan(static_system=sysprompt, prior_turns=[], current_student="what is a topic sentence?", current_rag="Retrieved: a topic sentence states the paragraph's main idea.")
run(plan1, "turn1")
# Turn 2: prior turn replayed verbatim -> should cache-READ the prefix
prior = [{"student_content": "what is a topic sentence?", "rag_text": "Retrieved: a topic sentence states the paragraph's main idea.", "tutor_json": tutor_output_json("think", "A topic sentence states the main idea.")}]
plan2 = build_message_plan(static_system=sysprompt, prior_turns=prior, current_student="give an example", current_rag="Retrieved: e.g. 'Dogs make great pets.'")
run(plan2, "turn2")
