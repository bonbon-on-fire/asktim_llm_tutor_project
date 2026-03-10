"""Allow ``python -m web_ui`` to launch the Flask dev server."""

from .run_app import app

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
