"""python -m main_ui entry point — boots the Flask development server."""

from __future__ import annotations

from main_ui.config import load_config
from main_ui.run_app import app


if __name__ == "__main__":
    config = load_config()
    app.run(host="127.0.0.1", port=config.port, debug=True)
