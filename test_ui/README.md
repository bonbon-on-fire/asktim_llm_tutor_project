# Test UI

Browser-based chat interface for the Humanities LLM Tutor. A 3-step wizard selects tutor prompt, course, and exercise, then opens a human-student chat session.

> This is the **TA / developer testing harness**. The student-facing iframe-embeddable app lives in [`main_ui/`](../main_ui/README.md). Both can run side-by-side — `test_ui/` on port `5000`, `main_ui/` on `5001`.

## Structure

```
test_ui/
  __init__.py
  __main__.py          # python -m test_ui
  run_app.py           # Flask app with API routes
  templates/
    index.html         # Single-page wizard + chat interface
```

## How to run

```bash
# Development
python -m test_ui

# Production (Heroku / gunicorn)
gunicorn test_ui.run_app:app --bind 0.0.0.0:$PORT
```

The app listens on port **5000** by default (override with the `PORT` environment variable).

## Usage

1. **Choose a tutor** — click a tutor version button (`tutor_01`, `tutor_02`, …)
2. **Choose a course** — click a course button; options come from `curriculum/` subfolders
3. **Choose an exercise** — click an exercise button; conversation starts automatically
4. **Chat** — type messages and press Enter (or Send); the tutor responds each turn
5. **New conversation** — click the header button to return to step 1

A **breadcrumb** at the top of the wizard tracks completed selections. Each step has a **Back** button to revise a prior choice. **Debug mode** (header checkbox) shows the tutor's `pedagogical-reasoning` field alongside each reply.

## API routes

| Method | Path                  | Description                            |
| ------ | --------------------- | -------------------------------------- |
| GET    | `/`                   | Serve the HTML page                    |
| GET    | `/api/config-options` | Tutor versions, courses, and exercises |
| POST   | `/api/start`          | Start a new conversation               |
| POST   | `/api/chat`           | Send a user message                    |
| GET    | `/api/reasoning`      | Fetch reasoning for all tutor turns    |

## Dependencies

- Flask (+ gunicorn for production)
- LangChain / LangGraph
- OpenAI API key (`OPENAI_API_KEY` env var required) or Anthropic key for Claude tutors
