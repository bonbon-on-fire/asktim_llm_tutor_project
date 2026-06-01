# Transcripts Dashboard

Flask dashboard to browse transcript results and compare Claude Mini (tutor_05) and Claude grades.

## Structure

```text
dashboard_ui/
  __init__.py              — package marker
  __main__.py              — entrypoint for python -m dashboard_ui
  run_dashboard_ui.py      — Flask app: routes, data loading, grade summaries
  static/
    app.js                 — frontend: routing, table rendering, chart drawing
  templates/
    index.html             — single-page app shell
```

## Run

From repo root in PowerShell:

```powershell
python -m flask --app dashboard_ui.run_dashboard_ui run -p 5002
```

Or:

```powershell
python -m dashboard_ui.run_dashboard_ui
```

Then open [http://127.0.0.1:5002](http://127.0.0.1:5002).

> Port `5001` is now reserved for [`main_ui/`](../main_ui/README.md). Pick anything else for the dashboard; the snippets above use `5002`.

## Data source

- By default, the app reads from `transcripts/` in repo root.
- Override with env var `TRANSCRIPTS_DIR` if needed.
- Included row sources:
  - Persona raw transcripts in `transcripts/<group>/<group>_raw/*.json`
- Graded counterparts shown per row:
  - **Mini column**: `.../<group>_claude_mini/<stem>.json` — shown when a graded mini file exists for the same stem; otherwise "—"
  - **Claude column**: `.../<group>_claude/*.json`

## Features

- Headers use `Group` and `Version`.
- Score panels show explicit errors when Mini or Claude counterparts are missing, unreadable, ambiguous, or mismatched.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `TRANSCRIPTS_DIR` | No | Override path to transcripts root folder. Default: `transcripts/` in repo root. |
