"""Figure discovery and multimodal-content helpers shared across modules.

Curriculum exercises may ship visual context (maps, diagrams) under
``curriculum/<course>/figures/``. This module turns those files into the
normalized multimodal content blocks that LangChain forwards to both OpenAI
and Anthropic vision models, so the tutor / student / judge can reason over
the real figure instead of a secondhand prose description.

Mirrors the small, dependency-free style of :mod:`utils.parsing`.

Naming convention (strict): ``exercise_<NN>_<slug>.<ext>`` where ``<NN>`` is a
two-digit exercise number and ``<ext>`` is one of ``png``, ``jpg``, ``jpeg``
(case-insensitive). Multiple figures per exercise are allowed and returned
sorted by filename. A figure serves exactly one exercise.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

# Repo root is two levels up from this file (utils/ -> repo root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CURRICULUM_ROOT = _REPO_ROOT / "curriculum"

# exercise_<NN>_<slug>.<png|jpg|jpeg>, extension case-insensitive.
_FIGURE_NAME_RE = re.compile(r"^exercise_(\d{2})_.+\.(png|jpe?g)$", re.IGNORECASE)

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def discover_figures(
    course: str,
    exercise_number: str,
    curriculum_root: Path | str | None = None,
) -> list[Path]:
    """Return the figure files attached to a given course/exercise.

    Globs ``<curriculum_root>/<course>/figures/``, keeps only files matching
    the strict ``exercise_<NN>_*.{png,jpg,jpeg}`` convention whose ``<NN>``
    equals *exercise_number* (zero-padded to two digits), and returns them
    sorted by filename. Returns an empty list when the folder or matches are
    absent — figures are always optional and back-compatible.
    """
    root = Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT
    figures_dir = root / course / "figures"
    if not figures_dir.is_dir():
        return []

    try:
        target = f"{int(exercise_number):02d}"
    except (TypeError, ValueError):
        target = str(exercise_number).strip()

    matches: list[Path] = []
    for path in figures_dir.iterdir():
        if not path.is_file():
            continue
        m = _FIGURE_NAME_RE.match(path.name)
        if m and m.group(1) == target:
            matches.append(path)
    return sorted(matches, key=lambda p: p.name)


def image_to_data_url(source: Path | str | bytes, *, mime_type: str | None = None) -> str:
    """Base64-encode an image into a ``data:`` URL consumable by LangChain.

    *source* may be a filesystem path (``Path``/``str``) or raw ``bytes``.
    When bytes are passed, *mime_type* must be provided (there is no filename
    to infer it from). The result is the normalized ``image_url`` value shape
    that both OpenAI and Anthropic accept via LangChain.
    """
    if isinstance(source, bytes):
        if not mime_type:
            raise ValueError("mime_type is required when encoding raw image bytes.")
        raw = source
        mime = mime_type
    else:
        path = Path(source)
        raw = path.read_bytes()
        mime = mime_type or _MIME_BY_SUFFIX.get(path.suffix.lower())
        if not mime:
            raise ValueError(
                f"Unsupported image extension '{path.suffix}'. "
                f"Supported: {', '.join(sorted(_MIME_BY_SUFFIX))}"
            )
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _figure_to_data_url(fig) -> str:
    """Coerce one figure item into a ``data:`` URL.

    Accepts any of:
    - a filesystem path (``Path``/``str``) to a PNG/JPG file,
    - an already-built ``data:`` URL string (used verbatim),
    - a ``(bytes, mime_type)`` tuple (used for in-memory uploads).
    """
    if isinstance(fig, str) and fig.startswith("data:"):
        return fig
    if isinstance(fig, tuple):
        raw, mime = fig
        return image_to_data_url(raw, mime_type=mime)
    return image_to_data_url(fig)


def build_multimodal_content(
    text: str,
    figures: list | None = None,
):
    """Build LangChain message content for *text* plus optional *figures*.

    Returns the plain ``text`` string when there are no figures (so callers
    that never deal with images are unaffected and message shapes stay
    identical to today). When figures are present, returns a list of content
    blocks::

        [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ...
        ]

    Each figure item may be a filesystem path (curriculum figures), an
    already-built ``data:`` URL string, or a ``(bytes, mime_type)`` tuple
    (in-memory student uploads). This list-of-blocks shape is the format
    LangChain normalizes for both the OpenAI and Anthropic providers, so the
    same content works regardless of which model the tutor / student / judge
    is using.
    """
    if not figures:
        return text

    blocks: list[dict] = [{"type": "text", "text": text}]
    for fig in figures:
        url = _figure_to_data_url(fig)
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def figure_filenames(figures: list[Path]) -> list[str]:
    """Return just the filenames for a list of figure paths (for transcript records)."""
    return [p.name for p in figures]


def resolve_figure_filenames(
    course: str,
    filenames: list[str],
    curriculum_root: Path | str | None = None,
) -> list[Path]:
    """Resolve recorded figure *filenames* back to paths under the course's figures dir.

    Used by the judge, which reads the ``figures`` field (filenames only) from
    a transcript and needs the on-disk paths to re-attach the images. Silently
    skips names that no longer exist on disk.
    """
    root = Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT
    figures_dir = root / course / "figures"
    resolved: list[Path] = []
    for name in filenames:
        candidate = figures_dir / name
        if candidate.is_file():
            resolved.append(candidate)
    return resolved
