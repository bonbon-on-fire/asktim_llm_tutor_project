"""``python -m internal_testing`` package entrypoint."""

from __future__ import annotations

from .run_ui import main


if __name__ == "__main__":
    raise SystemExit(main())

