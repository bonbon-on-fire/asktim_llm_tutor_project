"""Standalone tests for ui_core.web.static_blueprint (no pytest).

Run with:
    python -m ui_core.web.test_static_blueprint
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from ui_core.web.static_blueprint import static_bp

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


def test_serves_chat_css() -> None:
    app = Flask(__name__)
    app.register_blueprint(static_bp)
    client = app.test_client()

    resp = client.get("/ui-core/css/chat.css")
    _check("status 200", resp.status_code == 200, f"got {resp.status_code}")

    on_disk = (
        Path(__file__).resolve().parent.parent / "static" / "css" / "chat.css"
    ).read_bytes()
    _check("body matches on-disk chat.css bytes", resp.data == on_disk)


def test_endpoint_name() -> None:
    _check(
        "blueprint endpoint is ui_core.static",
        static_bp.name == "ui_core",
    )
    app = Flask(__name__)
    app.register_blueprint(static_bp)
    _check(
        "url_map has ui_core.static endpoint",
        "ui_core.static" in {rule.endpoint for rule in app.url_map.iter_rules()},
    )


def main() -> int:
    for t in (test_serves_chat_css, test_endpoint_name):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
