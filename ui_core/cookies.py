"""Shared cookie policy for the web chat apps.

Single source of truth for cookie names and the attribute policy applied to
Flask ``response.set_cookie(...)``. Each app passes its own ``secure`` and
``max_age`` (which come from that app's config) into ``default_cookie_kwargs``.
"""

from __future__ import annotations

import uuid

from flask import current_app, request as _flask_request
from itsdangerous import BadSignature, URLSafeSerializer

SESSION_COOKIE_NAME = "tutor_session_id"
USERNAME_COOKIE_NAME = "tutor_username"

# Namespaces the identity-cookie signature so it can't be swapped for some other
# value signed with the same app secret. Bump the suffix to force a re-sign.
_USERNAME_SALT = "tutor-username-v1"


def new_session_id() -> str:
    """Generate a fresh anonymous session id (UUIDv4)."""
    return str(uuid.uuid4())


def _username_serializer() -> URLSafeSerializer:
    """itsdangerous serializer keyed on the running app's secret key."""
    return URLSafeSerializer(current_app.secret_key, salt=_USERNAME_SALT)


def sign_username(username: str) -> str:
    """Sign *username* into a tamper-evident identity-cookie value.

    Uses an HMAC over the app secret so a hand-crafted ``tutor_username=<victim>``
    cookie no longer verifies. Store the returned string as the cookie value.
    """
    return _username_serializer().dumps(username)


def read_username_cookie(req=None) -> str | None:
    """Read and verify the identity cookie; return the username or ``None``.

    Returns ``None`` when the cookie is absent, forged/tampered, or a legacy
    *unsigned* value — so reads gated on username identity can't be spoofed by
    setting the cookie by hand. Pass a Flask ``request`` or rely on the proxy.
    """
    req = req if req is not None else _flask_request
    raw = req.cookies.get(USERNAME_COOKIE_NAME)
    if not raw:
        return None
    try:
        value = _username_serializer().loads(raw)
    except BadSignature:
        return None
    return value if isinstance(value, str) else None


def default_cookie_kwargs(*, secure: bool, max_age: int) -> dict:
    """Cookie attribute kwargs for Flask ``response.set_cookie(...)``.

    On HTTPS (``secure=True``): HttpOnly + SameSite=None + Secure + Partitioned
    (CHIPS) so the cookie survives an iframe / third-party (embed) context.

    On plain http (``secure=False``, e.g. ``*_COOKIE_SECURE=false`` for local
    dev): browsers **drop** ``SameSite=None`` and ``Partitioned`` cookies unless
    ``Secure`` is also set — which would make the identity cookie vanish in
    exactly the local-http case this flag exists for. Fall back to
    ``SameSite=Lax`` (works same-site over http); iframe-embed testing needs
    HTTPS regardless.
    """
    kwargs = {
        "httponly": True,
        "secure": secure,
        "max_age": max_age,
        "path": "/",
    }
    if secure:
        kwargs["samesite"] = "None"
        kwargs["partitioned"] = True
    else:
        kwargs["samesite"] = "Lax"
        kwargs["partitioned"] = False
    return kwargs
