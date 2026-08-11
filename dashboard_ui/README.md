# Transcripts Dashboard

Flask dashboard to browse the raw tutor/student transcripts in `transcripts/`. Lists every
transcript across persona groups and opens each one to read the full turn-by-turn conversation.

## Structure

```text
dashboard_ui/
  __init__.py              — package marker
  __main__.py              — entrypoint for python -m dashboard_ui
  run_dashboard_ui.py      — Flask app: routes, data loading, grade summaries
  static/
    app.js                 — frontend: routing, table rendering, chart drawing
    style.css              — dashboard styling
  templates/
    index.html             — single-page app shell
```

## Run

From repo root in PowerShell:

```powershell
python -m flask --app dashboard_ui.run_dashboard_ui run -p 5003
```

Or:

```powershell
python -m dashboard_ui.run_dashboard_ui
```

Then open [http://127.0.0.1:5003](http://127.0.0.1:5003).

> Ports `5000`–`5002` are taken by [`main_ui/`](../main_ui/README.md), `sandbox_ui/`, and `database_ui/`. The dashboard defaults to `5003` (override with the `PORT` env var); the snippets above use `5003`.

## Data source

- By default, the app reads from `transcripts/` in repo root.
- Override with env var `TRANSCRIPTS_DIR` if needed.
- Rows: one per raw transcript in `transcripts/<group>/<group>_raw/*.json`. A "group" is any
  folder under `transcripts/` that contains a `<group>_raw/` subfolder (e.g. `chaotic`,
  `clueless`, `cooperative`).

## Features

- Sortable table columns: `Group` (student persona), `Version` (transcript number), `Course`,
  `Exercise`, `Turns`, `Score` (Claude judge total/max), plus a `Read` link.
- The detail page shows run metadata (tutor prompt, persona, course, exercise, turns), collapsible
  `Context`/`Exercise` blocks, and every turn rendered as Student / Tutor (with the tutor's
  pedagogical reasoning when present).

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `TRANSCRIPTS_DIR` | No | Override path to transcripts root folder. Default: `transcripts/` in repo root. |
