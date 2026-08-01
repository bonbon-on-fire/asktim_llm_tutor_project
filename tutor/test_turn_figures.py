"""Standalone test for per-turn figure attachment in the tutor graph.

Run with:
    python -m tutor.test_turn_figures

Verifies that the last human message gets the UNION of static (exercise) and
per-turn (retrieved) figures, deduped, without invoking any model.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tutor.run_tutor import _attach_figures_to_last_human

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_union_of_static_and_turn_figures_deduped() -> None:
    """Assert static + per-turn figures attach to the last human message, deduped, ordered."""
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
        HumanMessage(content="explain figure"),
    ]
    static = ["data:image/png;base64,AAA"]
    turn = ["data:image/png;base64,BBB", "data:image/png;base64,AAA"]  # BBB new, AAA dup
    merged = list(dict.fromkeys([*static, *turn]))
    _attach_figures_to_last_human(messages, merged)

    last = messages[-1]
    urls = [b["image_url"]["url"] for b in last.content if b.get("type") == "image_url"]
    _check(
        "static+turn union attaches once each, static first",
        urls == ["data:image/png;base64,AAA", "data:image/png;base64,BBB"],
        f"got {urls}",
    )
    _check("text block preserved", last.content[0] == {"type": "text", "text": "explain figure"})


def main() -> int:
    tests = [test_union_of_static_and_turn_figures_deduped]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
