"""Run the dashboard Flask app via ``python -m dashboard_ui``."""

import os

from .run_dashboard_ui import app


if __name__ == "__main__":
    # Ports: main_ui=5000, sandbox_ui=5001, database_ui=5002; dashboard defaults to 5003 (PORT overrides).
    app.run(debug=True, port=int(os.environ.get("PORT", "5003")))

