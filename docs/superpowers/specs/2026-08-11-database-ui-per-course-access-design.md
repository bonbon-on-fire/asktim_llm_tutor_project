# database_ui per-course access scoping — design

**Date:** 2026-08-11
**App:** `database_ui` (read-only review dashboard)

## Goal

Give different course staff their own passwords, each scoped so a password can
only see its own course(s)' data in the review tool. This addresses the privacy
concern raised in the 2026-08-11 meeting: today a single shared password unlocks
**everyone's** conversations across **all** courses.

The AskTIM team keeps one all-access "master" password that still sees every
course.

## Current state

`database_ui/auth.py` is a single shared-password gate: one env var
`DATABASE_UI_PASSWORD` unlocks the whole tool for the browser session via a
signed Flask cookie (`session["database_authed"] = True`). If the env var is
unset (local dev), the gate is open.

Every data path is deliberately **unscoped** — `list_all_conversations`,
`get_conversation`, the CSV export (`list_export_filters` / `iter_export_rows`),
and the image/file byte endpoints all return data for **every** course. The
`course` key (a curriculum folder key, e.g. `supply_chain_design`) already lives
on each `Conversation` row and is the scoping dimension.

The app is **read-only by construction**: it never writes the DB and never
migrates (`main_ui` owns migrations). This design preserves that — all changes
are auth checks and `SELECT` filters, no schema changes.

## Decisions (locked)

- **Config storage:** env vars. Chosen because the app is strictly read-only
  (a DB credentials table would break that and require password-management UI
  that doesn't exist), it matches the existing `DATABASE_UI_PASSWORD` pattern,
  and Railway config is env-first. Tradeoff accepted: changing access requires a
  redeploy/restart — negligible at this scale (a handful of courses/staff).
- **Mapping model:** one password → one *or more* courses, plus a master
  all-access password.
- **Login UX:** unchanged single password box. The matched password determines
  the scope; the course list is never leaked on the login page.
- **Scope coverage:** *everything*. List, single-conversation view, CSV export
  (picker + rows), and image/file byte endpoints all enforce the session's
  scope. A scoped user reaching another course's conversation/image/file by
  guessing an ID gets a plain **404**.
- **Fail-safe:** a malformed/empty `DATABASE_UI_COURSE_PASSWORDS`, or a password
  that matches nothing, grants **no** access — never all-access.

## Configuration

Master (all-access) stays as today:

```bash
DATABASE_UI_PASSWORD='<master password>'
```

New: `DATABASE_UI_COURSE_PASSWORDS`, a JSON list of `{password, courses}`
entries. `courses` holds curriculum keys (the same keys on `Conversation.course`):

```bash
DATABASE_UI_COURSE_PASSWORDS='[
  {"password": "<supply-chain password>", "courses": ["supply_chain_design"]},
  {"password": "<multi-course password>", "courses": ["economic_development_planning", "urban_transportation"]}
]'
```

- Both unset → open local-dev mode (all-access), exactly as today.
- Only `DATABASE_UI_PASSWORD` set → single all-access password, exactly as today
  (backward compatible).
- Passwords are secrets: set them in Railway env, never commit real values. The
  example values in this doc are placeholders.

Parsed once at startup into config. Parse failure logs an error and yields an
**empty** course-password map (master still works; no course access granted).

## Auth / session (`auth.py`)

A **Scope** captures what a session may see: either all-access, or a fixed list
of allowed course keys.

- `resolve_scope(candidate) -> Scope | None`: check the master password first
  (→ all-access), then each course-password entry. Returns the matched scope, or
  `None` if nothing matches.
- On successful login, store the scope in the session:
  `session["all_access"] = bool` and `session["allowed_courses"] = [...]`
  (alongside the existing authed flag). `mark_authed(scope)` gains the scope.
- `allowed_courses() -> list[str] | None`: read the scope back from the session.
  `None` means "no filter" (master / local-dev); a list means "restrict to
  these". Exposed to routes (e.g. on `g`) so each handler can filter.
- `is_authed()`, the before-request guard, and public endpoints are unchanged.

Comparisons use a constant-time check (`hmac.compare_digest`) for each candidate,
matching the sensitivity of the existing gate.

## Scope enforcement — every data path

Routes read `allowed_courses()` and pass it into the service layer; service
functions gain an optional `courses: list[str] | None` filter (`None` = no
filter, preserving current behavior for master/dev and keeping existing callers/
tests valid).

- **`list_all_conversations(..., courses=None)`** — add `WHERE course IN (...)`
  when `courses` is not `None`.
- **`list_export_filters(db, courses=None)`** — same filter, so the export picker
  only lists the staff member's course(s).
- **`iter_export_rows(db, pairs, courses=None)`** — intersect the requested
  `(course, exercise)` pairs with the allowed courses; drop out-of-scope pairs so
  a crafted `assignment=` query can't pull another course.
- **`get_conversation` (by UUID)** — route returns **404** if the fetched
  conversation's `course` is not in `allowed_courses()`.
- **`api_image` / `api_file` (by int ID)** — the byte endpoints must verify the
  owning conversation's course. Add a scoped lookup that joins
  `UploadedImage`/`UploadedFile → Message → Conversation` and returns the row
  only if its course is allowed; otherwise **404**. **This is the key security
  detail** — without it, a scoped user could reach another course's attachments
  by guessing sequential integer IDs.

## Login / UI

- Login form and POST handler unchanged except that a successful
  `check_password` becomes `resolve_scope(...)`; on match, `mark_authed(scope)`.
- **Minor UI polish:** the header shows the active scope — "Viewing:
  \<course name\>" (or a combined label for multiple courses / "All courses" for
  master). Server-side scoping is authoritative; this is only a signpost so staff
  know what they're looking at. Passed to the template from the session scope via
  `course_display_name`.

## Testing

Extend `database_ui/tests`:

- **Master password** → sees all courses in list, view, export filters, export
  rows, images, files.
- **Scoped password** → list/view/export show only its course(s); a
  conversation, image, or file belonging to another course returns **404**.
- **Export pair filtering** → an `assignment=` for an out-of-scope course yields
  no rows (not another course's data).
- **Fail-safe config** → malformed/empty `DATABASE_UI_COURSE_PASSWORDS` grants
  no course access; a non-matching password is rejected.
- **Backward compatibility** → only `DATABASE_UI_PASSWORD` set behaves exactly as
  today (all-access); neither set = open local dev.

## Out of scope

- Per-user accounts / usernames, password rotation UI, audit logging.
- Any schema change or migration (the app stays read-only).
- Runtime editing of credentials (requires a redeploy — accepted).
