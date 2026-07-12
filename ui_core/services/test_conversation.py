"""Standalone tests for ui_core.services.conversation (no pytest).

Run with:
    python -m ui_core.services.test_conversation

The helpers are model-agnostic — they take the ORM classes (bundled in a
``Models``) as arguments — so they're tested in ISOLATION on a local Base
(ui_core must not depend on the app packages). A minimal local ``Conversation``
supplies the columns these functions touch, plus an extra ``notes`` column to
exercise ``extra_fields`` (mirroring how sandbox_ui's real Conversation adds
columns main_ui's doesn't have).
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Text, Uuid
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from ui_core.db.models_common import (
    MessageMixin,
    StudentMixin,
    UploadedFileMixin,
    UploadedImageMixin,
)
from ui_core.db.session import build_engine
from ui_core.services import conversation as svc
from ui_core.services.conversation import Models

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a PASS/FAIL for *name* based on *condition*."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _utcnow() -> datetime:
    """Return the current tz-aware UTC datetime (column default for the test model)."""
    return datetime.now(timezone.utc)


class _Base(DeclarativeBase):
    pass


class Conversation(_Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    course: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_number: Mapped[str] = mapped_column(Text, nullable=False)
    tutor_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # extra, sandbox-style column exercised via `extra_fields`
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(MessageMixin, _Base):
    pass


class Student(StudentMixin, _Base):
    pass


class UploadedImage(UploadedImageMixin, _Base):
    pass


class UploadedFile(UploadedFileMixin, _Base):
    """Not exercised by these tests; declared so MessageMixin.uploaded_files resolves."""


_MODELS = Models(Conversation=Conversation, Message=Message, UploadedImage=UploadedImage)


def _new_session():
    """Create a fresh SQLite-backed schema; return ``(tempdir, engine)`` for the caller to clean up."""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    eng = build_engine(f"sqlite:///{Path(tmp.name) / 'c.db'}", sqlite_fk=True)
    _Base.metadata.create_all(eng)
    return tmp, eng


def test_find_or_create_conversation() -> None:
    """Cover create, resolve-by-session, resolve-by-username, and the WrongSessionError paths."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessA",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
                username="alice",
            )
            s.commit()
            _check("created with no extra_fields", convo.notes is None)
            _check("course set", convo.course == "cs101")
            _check("username set", convo.username == "alice")

            # resolve existing by same session_id
            again = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessA",
                conversation_id=convo.id,
                course="ignored",
                exercise_number="ignored",
                tutor_prompt="ignored",
            )
            _check("resolves existing by session", again.id == convo.id)

            # resolve existing by matching username, different session
            again2 = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="other-session",
                conversation_id=convo.id,
                course="ignored",
                exercise_number="ignored",
                tutor_prompt="ignored",
                username="alice",
            )
            _check("resolves existing by username", again2.id == convo.id)

            # wrong session + wrong/no username -> WrongSessionError
            try:
                svc.find_or_create_conversation(
                    s,
                    models=_MODELS,
                    session_id="stranger",
                    conversation_id=convo.id,
                    course="ignored",
                    exercise_number="ignored",
                    tutor_prompt="ignored",
                    username="bob",
                )
                _check("wrong session+username raises", False, "did not raise")
            except svc.WrongSessionError:
                _check("wrong session+username raises", True)

            # missing conversation_id -> WrongSessionError
            try:
                svc.find_or_create_conversation(
                    s,
                    models=_MODELS,
                    session_id="sessA",
                    conversation_id=uuid.uuid4(),
                    course="ignored",
                    exercise_number="ignored",
                    tutor_prompt="ignored",
                )
                _check("missing id raises", False, "did not raise")
            except svc.WrongSessionError:
                _check("missing id raises", True)
        eng.dispose()
    finally:
        tmp.cleanup()


def test_find_or_create_with_extra_fields() -> None:
    """Check ``extra_fields`` is written to the sandbox-style extra column on create."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessB",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
                extra_fields={"notes": "custom note"},
            )
            s.commit()
            _check("extra_fields persisted", convo.notes == "custom note")
        eng.dispose()
    finally:
        tmp.cleanup()


def test_turn_numbering_and_history() -> None:
    """Check turn numbers increment across exchanges and history/count reflect them."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessC",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
            )
            s.flush()

            student1, tutor1 = svc.append_exchange(
                s,
                models=_MODELS,
                conversation=convo,
                student_text="hi",
                tutor_text="hello",
                pedagogical_reasoning="reasoning-1",
            )
            _check("first turn is 1", student1.turn == 1 and tutor1.turn == 1)

            student2 = svc.start_exchange_student_only(
                s, models=_MODELS, conversation=convo, student_text="q2"
            )
            _check("second student turn is 2", student2.turn == 2)

            tutor2 = svc.complete_exchange_tutor(
                s,
                models=_MODELS,
                conversation=convo,
                turn=student2.turn,
                tutor_text="a2",
                pedagogical_reasoning="reasoning-2",
            )
            _check("second tutor turn matches", tutor2.turn == 2)
            s.commit()

            history = svc.get_history_for_tutor(s, convo, models=_MODELS)
            _check(
                "history shape",
                history
                == [
                    {"role": "student", "content": "hi"},
                    {"role": "tutor", "content": "hello"},
                    {"role": "student", "content": "q2"},
                    {"role": "tutor", "content": "a2"},
                ],
                str(history),
            )

            count = svc.count_student_messages(s, convo, models=_MODELS)
            _check("count_student_messages", count == 2, str(count))
        eng.dispose()
    finally:
        tmp.cleanup()


def test_get_history_for_tutor_with_attachments() -> None:
    """Check `get_history_for_tutor` re-injects uploaded_files text into student
    turns only (via the batched `_files_by_message` helper, not a lazy per-message
    load), leaves the stored row untouched, and leaves file-less turns unaffected.
    """
    models_with_files = Models(
        Conversation=Conversation,
        Message=Message,
        UploadedImage=UploadedImage,
        UploadedFile=UploadedFile,
    )
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=models_with_files,
                session_id="sessH",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
            )
            s.flush()

            student1, tutor1 = svc.append_exchange(
                s,
                models=models_with_files,
                conversation=convo,
                student_text="What does this show?",
                tutor_text="Looks like sales data.",
                pedagogical_reasoning=None,
            )
            s.add(
                UploadedFile(
                    message_id=student1.id,
                    filename="budget.csv",
                    kind="text/csv",
                    extracted_text="a, b\n1, 2",
                    size_bytes=9,
                    data=b"a, b\n1, 2",
                )
            )
            s.commit()

            history = svc.get_history_for_tutor(s, convo, models=models_with_files)
            student_entry = next(h for h in history if h["role"] == "student")
            _check(
                "attachment text injected into student content",
                "[Attachment: budget.csv]" in student_entry["content"]
                and "1, 2" in student_entry["content"],
                student_entry["content"],
            )
            _check(
                "tutor content unaffected by attachments",
                history[1] == {"role": "tutor", "content": "Looks like sales data."},
                str(history[1]),
            )
            _check(
                "stored row content not mutated",
                student1.content == "What does this show?",
                student1.content,
            )

            # A second, file-less turn in the same conversation stays unaffected.
            student2 = svc.start_exchange_student_only(
                s, models=models_with_files, conversation=convo, student_text="q2"
            )
            svc.complete_exchange_tutor(
                s,
                models=models_with_files,
                conversation=convo,
                turn=student2.turn,
                tutor_text="a2",
                pedagogical_reasoning=None,
            )
            s.commit()

            history2 = svc.get_history_for_tutor(s, convo, models=models_with_files)
            _check(
                "text-only turn unaffected",
                history2[2] == {"role": "student", "content": "q2"},
                str(history2[2]),
            )
        eng.dispose()
    finally:
        tmp.cleanup()


def test_get_messages_for_conversation_reasoning_toggle() -> None:
    """Check ``include_reasoning`` gates the pedagogical-reasoning field and images key is always present."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessD",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
            )
            s.flush()
            svc.append_exchange(
                s,
                models=_MODELS,
                conversation=convo,
                student_text="hi",
                tutor_text="hello",
                pedagogical_reasoning="secret-reasoning",
            )
            s.commit()

            without = svc.get_messages_for_conversation(
                s, convo, models=_MODELS, include_reasoning=False
            )
            with_reasoning = svc.get_messages_for_conversation(
                s, convo, models=_MODELS, include_reasoning=True
            )
            _check(
                "reasoning excluded by default",
                all("pedagogical_reasoning" not in m for m in without),
            )
            tutor_entry = next(m for m in with_reasoning if m["role"] == "tutor")
            _check(
                "reasoning included when requested",
                tutor_entry.get("pedagogical_reasoning") == "secret-reasoning",
            )
            _check(
                "images key always present",
                all("images" in m for m in without + with_reasoning),
            )
        eng.dispose()
    finally:
        tmp.cleanup()


def test_summarize_and_list_conversations() -> None:
    """Check conversation summaries (snippet truncation, ``summarize_extra``) and username listing."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessE",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
                username="carol",
                extra_fields={"notes": "flagged"},
            )
            s.flush()
            svc.append_exchange(
                s,
                models=_MODELS,
                conversation=convo,
                student_text="hi",
                tutor_text="a somewhat long tutor reply that goes past eighty characters "
                "so the snippet gets truncated with an ellipsis at the end",
                pedagogical_reasoning=None,
            )
            s.commit()

            plain = svc._summarize_conversation(s, convo, models=_MODELS)
            _check("plain summary has no extra keys", "notes" not in plain)
            _check("message_count correct", plain["message_count"] == 2)
            _check(
                "snippet truncated",
                plain["last_message_snippet"] is not None
                and plain["last_message_snippet"].endswith("…"),
            )

            extra = svc._summarize_conversation(
                s, convo, models=_MODELS, summarize_extra=lambda c: {"notes": c.notes}
            )
            _check("summarize_extra merged", extra.get("notes") == "flagged")

            listed_plain = svc.list_conversations_for_username(
                s, "carol", models=_MODELS
            )
            _check("list has 1 conversation", len(listed_plain) == 1)
            _check("list without extra has no notes", "notes" not in listed_plain[0])

            listed_extra = svc.list_conversations_for_username(
                s,
                "carol",
                models=_MODELS,
                summarize_extra=lambda c: {"notes": c.notes},
            )
            _check(
                "list with extra has notes",
                listed_extra[0].get("notes") == "flagged",
            )

            _check(
                "empty username returns empty list",
                svc.list_conversations_for_username(s, "", models=_MODELS) == [],
            )
        eng.dispose()
    finally:
        tmp.cleanup()


def test_get_conversation_for_viewer_ownership() -> None:
    """Check viewer access is granted by session_id or username and denied to strangers / unknown ids."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessF",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
                username="dave",
            )
            s.commit()

            _check(
                "owner by session_id",
                svc.get_conversation_for_viewer(
                    s, convo.id, "sessF", None, models=_MODELS
                )
                is not None,
            )
            _check(
                "owner by username",
                svc.get_conversation_for_viewer(
                    s, convo.id, "other", "dave", models=_MODELS
                )
                is not None,
            )
            _check(
                "stranger denied",
                svc.get_conversation_for_viewer(
                    s, convo.id, "other", "eve", models=_MODELS
                )
                is None,
            )
            _check(
                "missing id -> None",
                svc.get_conversation_for_viewer(
                    s, uuid.uuid4(), "sessF", "dave", models=_MODELS
                )
                is None,
            )
        eng.dispose()
    finally:
        tmp.cleanup()


def test_backfill_username_for_session() -> None:
    """Check backfilling a username only touches rows with no username already set."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessG",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
            )
            svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessG",
                conversation_id=None,
                course="cs102",
                exercise_number="ex2",
                tutor_prompt="be nice",
                username="already-set",
            )
            s.commit()

            touched = svc.backfill_username_for_session(
                s, "sessG", "frank", models=_MODELS
            )
            s.commit()
            _check("only the unset row is touched", touched == 1, str(touched))

            rows = (
                s.query(Conversation)
                .filter(Conversation.session_id == "sessG")
                .order_by(Conversation.course)
                .all()
            )
            usernames = {c.course: c.username for c in rows}
            _check(
                "backfilled row now has username",
                usernames["cs101"] == "frank",
                str(usernames),
            )
            _check(
                "already-set row untouched",
                usernames["cs102"] == "already-set",
                str(usernames),
            )
        eng.dispose()
    finally:
        tmp.cleanup()


def test_message_rating_and_message_payload_ids() -> None:
    """Check per-message rating: default 0, set_message_rating, ownership, and
    that get_messages_for_conversation exposes each message's id + rating."""
    tmp, eng = _new_session()
    try:
        with Session(eng) as s:
            convo = svc.find_or_create_conversation(
                s,
                models=_MODELS,
                session_id="sessR",
                conversation_id=None,
                course="cs101",
                exercise_number="ex1",
                tutor_prompt="be nice",
                username="rita",
            )
            s.flush()
            _student, tutor = svc.append_exchange(
                s,
                models=_MODELS,
                conversation=convo,
                student_text="hi",
                tutor_text="hello",
                pedagogical_reasoning=None,
            )
            s.commit()

            _check("tutor rating defaults to 0", tutor.rating == 0, str(tutor.rating))

            # payload exposes id + rating for every message
            msgs = svc.get_messages_for_conversation(s, convo, models=_MODELS)
            _check(
                "payload has id + rating on every message",
                all("id" in m and "rating" in m for m in msgs),
                str(msgs),
            )

            # ownership: owner (by session or username) can fetch; stranger cannot
            got = svc.get_message_for_viewer(s, tutor.id, "sessR", None, models=_MODELS)
            _check("owner-by-session gets the message", got is not None and got.id == tutor.id)
            _check(
                "owner-by-username gets the message",
                svc.get_message_for_viewer(s, tutor.id, "other", "rita", models=_MODELS)
                is not None,
            )
            _check(
                "stranger denied the message",
                svc.get_message_for_viewer(s, tutor.id, "other", "eve", models=_MODELS)
                is None,
            )
            _check(
                "missing message id -> None",
                svc.get_message_for_viewer(s, 999999, "sessR", "rita", models=_MODELS)
                is None,
            )

            # set the rating and confirm it round-trips through the payload
            svc.set_message_rating(s, tutor, 1)
            s.commit()
            reloaded = svc.get_messages_for_conversation(s, convo, models=_MODELS)
            tutor_entry = next(m for m in reloaded if m["role"] == "tutor")
            _check("rating persisted to 1", tutor_entry["rating"] == 1, str(tutor_entry))

            svc.set_message_rating(s, tutor, -1)
            s.commit()
            _check("rating updates to -1", tutor.rating == -1, str(tutor.rating))
        eng.dispose()
    finally:
        tmp.cleanup()


def main() -> int:
    """Run all tests in this module and return an exit code (1 if any failed)."""
    tests = (
        test_find_or_create_conversation,
        test_find_or_create_with_extra_fields,
        test_turn_numbering_and_history,
        test_get_history_for_tutor_with_attachments,
        test_get_messages_for_conversation_reasoning_toggle,
        test_summarize_and_list_conversations,
        test_get_conversation_for_viewer_ownership,
        test_backfill_username_for_session,
        test_message_rating_and_message_payload_ids,
    )
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
