"""Unit tests for the alliterative student-pseudonym helper."""

from __future__ import annotations

from database_ui.anonymize import (
    _ADJECTIVES,
    _ANIMALS,
    _LETTERS,
    display_identity,
    pseudonym,
)


def test_pseudonym_is_deterministic():
    assert pseudonym("stu@mit.edu") == pseudonym("stu@mit.edu")


def test_pseudonym_is_two_titlecase_words():
    adj, animal = pseudonym("kwong_boey").split(" ")
    assert adj.istitle() and animal.istitle()


def test_pseudonym_is_alliterative():
    # The whole point: adjective and animal share a first letter.
    for name in ("stu@mit.edu", "kwong_boey", "SC2x_Laura", "caplice", "toym26"):
        adj, animal = pseudonym(name).split(" ")
        assert adj[0].lower() == animal[0].lower(), (name, adj, animal)


def test_pseudonym_varies_across_usernames():
    names = [f"student_{i}@mit.edu" for i in range(50)]
    pairs = {pseudonym(n) for n in names}
    # Not a perfect bijection (collisions are fine), but 50 users must not all
    # collapse to a handful of pairs — sanity-check reasonable spread.
    assert len(pairs) > 25


def test_every_usable_letter_has_both_adjectives_and_animals():
    for letter in _LETTERS:
        assert _ADJECTIVES.get(letter), letter
        assert _ANIMALS.get(letter), letter


def test_display_identity_all_access_returns_real_username():
    assert display_identity("stu@mit.edu", all_access=True) == "stu@mit.edu"


def test_display_identity_course_scope_returns_pseudonym():
    got = display_identity("stu@mit.edu", all_access=False)
    assert got != "stu@mit.edu"
    assert got == pseudonym("stu@mit.edu")


def test_display_identity_blank_is_none_regardless_of_scope():
    assert display_identity(None, all_access=False) is None
    assert display_identity("", all_access=False) is None
    assert display_identity(None, all_access=True) is None
