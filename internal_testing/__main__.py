"""Run the terminal UI entrypoint via ``python -m internal_ui``."""

from __future__ import annotations

from .run_ui import main


if __name__ == "__main__":
    raise SystemExit(main())

