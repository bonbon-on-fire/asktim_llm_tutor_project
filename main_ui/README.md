# main_ui

Production-shape embeddable tutor app for real OCW students. Designed to be loaded inside an iframe on course pages, with each iframe URL hardcoding its own course + exercise context.

For the overall design — problem framing, schema, identity flow, non-goals — see **Phase 8** of the root [PLANNING.md](../PLANNING.md). For the step-by-step build log, see [main_ui/PLANNING.md](PLANNING.md).

## Status

Step 1 of 11 — folder skeleton + Flask boot. No database, no chat, no templates yet. The app boots and responds to a health check; that's it for now.

## Quick start

```powershell
python -m main_ui
```

The app binds to `127.0.0.1:5001` (avoids clashing with `web_ui/` on `5000`).

Verify it's up:

```powershell
curl http://127.0.0.1:5001/health
# {"service":"main_ui","status":"ok"}
```

## Environment variables

All are optional in dev (sensible defaults provided). Production hosting (future phase) will require real values.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAIN_UI_SECRET_KEY` | `dev-insecure-key` | Flask session signing key. Replace in production. |
| `DATABASE_URL` | `sqlite:///./main_ui.db` | DB connection string. Used starting Step 2. |
| `PORT` | `5001` | TCP port the Flask dev server binds to. |

## How `main_ui/` differs from `web_ui/`

| | `web_ui/` | `main_ui/` |
| --- | --- | --- |
| Audience | Developers / TAs testing tutor configs | Real students embedded in OCW course pages |
| UI | 3-step wizard (tutor, course, exercise) | No wizard — course/exercise come from URL params |
| Persistence | In-memory only | Postgres-backed (added Step 2) |
| Identity | None | Email-after-3-messages (added Step 7) |
| Port | `5000` | `5001` |
| Status | Stable — testing harness | New work in progress |

Both apps will coexist and can run side by side.

## Layout

```text
main_ui/
  __init__.py     # package marker
  __main__.py     # python -m main_ui entry point
  config.py       # env-driven Config dataclass
  run_app.py      # Flask app factory + /health route
  README.md       # this file
  PLANNING.md     # step-by-step build log
```

Subfolders (`db/`, `routes/`, `services/`, `templates/`, `static/`, `uploads/`, `tests/`) are added in later steps as described in [PLANNING.md](PLANNING.md).

## What's NOT in main_ui yet

- Database (Step 2)
- `/embed` route + chat UI (Steps 3, 6)
- Tutor integration (Step 4)
- `/api/chat` (Step 5)
- Email modal + identity (Step 7)
- Conversation history (Step 8)
- Image uploads (Step 9)
- Iframe test page (Step 10)
- Tests (Step 11)
