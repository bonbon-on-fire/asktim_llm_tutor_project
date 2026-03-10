# Web UI

Browser-based interface for the Humanities LLM Tutor. Same pipeline as the
terminal UI but with a Flask web server and interactive chat page.

## Structure

```
web_ui/
  __init__.py
  __main__.py          # python -m web_ui
  run_app.py           # Flask app with API routes
  templates/
    index.html         # Single-page chat interface
```

## How to run

```bash
# Development
python -m web_ui

# Production (Heroku / gunicorn)
gunicorn web_ui.run_app:app --bind 0.0.0.0:$PORT
```

The app listens on port **5000** by default (override with the `PORT`
environment variable).

## Pipeline

The web UI mirrors the terminal UI pipeline:

1. **Configure** — the page presents dropdowns for tutor prompt, student
   persona type + version, course, and exercise. Options are discovered
   dynamically from the file system via `GET /api/config-options`.
2. **Start conversation** — `POST /api/start` builds the tutor graph with the
   combined assignment context (`course.txt` + chosen exercise) injected into
   the system prompt and returns the tutor's opening message. The payload may
   include optional `turn_size` (positive integer), which is included in both
   tutor/student context.
3. **Chat** — the user types messages (`POST /api/chat`) or clicks
   *Run student bot turn* (`POST /api/student-turn`) to let the selected
   student persona generate a message using that same combined assignment
   context, then get the tutor's reply.
4. **Debug mode** — a checkbox toggles display of the tutor's
   `pedagogical-reasoning` field alongside each reply.

## API routes

| Method | Path                  | Description                       |
| ------ | --------------------- | --------------------------------- |
| GET    | `/`                   | Serve the HTML page               |
| GET    | `/api/config-options` | Discover available config options |
| POST   | `/api/start`          | Start a new conversation          |
| POST   | `/api/chat`           | Send a user message               |
| POST   | `/api/student-turn`   | Generate student + tutor turn     |
| GET    | `/api/reasoning`      | Fetch reasoning for all turns     |

## Dependencies

- Flask (+ gunicorn for production)
- LangChain / LangGraph
- OpenAI API key (`OPENAI_API_KEY` env var required)
