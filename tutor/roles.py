"""Role registry: the single source of truth mapping an assistant *role* to its
prompt folder and default prompt.

A role decides which prompt family the web apps use. ``tutor`` reads
``tutor/prompts/`` with default ``tutor_07`` (today's behavior). Additional
roles (e.g. a teaching assistant ``ta`` reading ``ta/prompts/``) are added by
creating the folder and registering an entry below — until then the role is
unknown and the web layer 404s on it.

Both ``main_ui`` and ``sandbox_ui`` import from here so they stay in lockstep.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Role:
    """A named assistant role: which prompt folder and default prompt to use."""

    name: str
    prompts_dir: Path
    default_prompt: str


DEFAULT_ROLE = "tutor"

# Only roles that are ready to serve appear here. To add the TA role later:
# create ``ta/prompts/ta_01.txt`` (+ variants) and uncomment the entry below.
ROLES: dict[str, Role] = {
    "tutor": Role("tutor", _REPO_ROOT / "tutor" / "prompts", "tutor_07"),
    # "ta": Role("ta", _REPO_ROOT / "ta" / "prompts", "ta_01"),
}


def get_role(name: str | None) -> Role | None:
    """Return the :class:`Role` for *name*, or ``None`` if unknown/unregistered."""
    return ROLES.get(name) if name else None


def prompts_dir_for_prompt(prompt_name: str) -> Path | None:
    """Return the registered ``prompts_dir`` whose folder owns ``<prompt_name>.txt``.

    Prompt names are unique per role (``tutor_*`` vs ``ta_*``), so at most one
    registered role matches. Returns ``None`` when no registered role owns the
    prompt — callers then fall back to the default tutor folder.
    """
    for role in ROLES.values():
        if (role.prompts_dir / f"{prompt_name}.txt").is_file():
            return role.prompts_dir
    return None
