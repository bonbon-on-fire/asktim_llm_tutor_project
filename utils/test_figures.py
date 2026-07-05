"""Standalone tests for utils.figures (no pytest dependency).

Run with:
    python -m utils.test_figures

Exercises discovery edge cases and the encoding round-trip against the real
checked-in curriculum figures plus a temporary fixture directory.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from utils.figures import (
    build_multimodal_content,
    discover_figures,
    figure_filenames,
    image_to_data_url,
    resolve_figure_filenames,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CURRICULUM = _REPO_ROOT / "curriculum"

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a pass/fail result for the named assertion."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# discover_figures
# ---------------------------------------------------------------------------

def test_discovers_real_curriculum_figure() -> None:
    """Assert discover_figures finds the checked-in exercise_8 and exercise_4 figures."""
    figs = discover_figures("cities_and_climate_change", "8")
    names = figure_filenames(figs)
    _check(
        "discovers exercise_8 spider diagram",
        names == ["exercise_8_spider_diagram.png"],
        f"got {names}",
    )

    figs04 = discover_figures("cities_and_climate_change", "4")
    _check(
        "discovers exercise_4 power/actors map",
        figure_filenames(figs04) == ["exercise_4_power_actors_map.png"],
        f"got {figure_filenames(figs04)}",
    )


def test_exercise_number_is_normalized() -> None:
    """Assert padded and unpadded exercise numbers both resolve to exercise_8."""
    # "8" (unpadded) and "08" (padded) should both resolve to exercise_8.
    by_unpadded = figure_filenames(discover_figures("cities_and_climate_change", "8"))
    _check("unpadded '8' resolves to exercise_8", by_unpadded == ["exercise_8_spider_diagram.png"], f"got {by_unpadded}")
    by_padded = figure_filenames(discover_figures("cities_and_climate_change", "08"))
    _check("padded '08' also resolves to exercise_8", by_padded == ["exercise_8_spider_diagram.png"], f"got {by_padded}")


def test_missing_exercise_and_course_return_empty() -> None:
    """Assert a missing exercise or course yields an empty figure list."""
    _check("missing exercise -> []", discover_figures("cities_and_climate_change", "99") == [])
    _check("missing course -> []", discover_figures("no_such_course", "01") == [])


def test_discovery_filters_and_isolates_by_exercise() -> None:
    """Assert discovery filters by extension/name, sorts, and isolates by exercise number."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        # Valid, two figures for exercise 1 (should sort alphabetically).
        (figdir / "exercise_1_b_second.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "exercise_1_a_first.jpg").write_bytes(b"\xff\xd8\xff")
        # Different exercise — must not bleed into 1.
        (figdir / "exercise_2_other.jpeg").write_bytes(b"\xff\xd8\xff")
        # Non-matching names — must be ignored.
        (figdir / "course_overview.png").write_bytes(b"x")   # no exercise_ prefix
        (figdir / "exercise_1_notes.pdf").write_bytes(b"x")  # unsupported extension

        names = figure_filenames(discover_figures("demo", "1", curriculum_root=root))
        _check(
            "filters extensions/names and sorts within exercise 1",
            names == ["exercise_1_a_first.jpg", "exercise_1_b_second.png"],
            f"got {names}",
        )
        names2 = figure_filenames(discover_figures("demo", "2", curriculum_root=root))
        _check("isolates exercise 2", names2 == ["exercise_2_other.jpeg"], f"got {names2}")


# ---------------------------------------------------------------------------
# image_to_data_url
# ---------------------------------------------------------------------------

def test_data_url_round_trip_from_path() -> None:
    """Assert a PNG path encodes to a data URL that decodes back to the file bytes."""
    fig = discover_figures("cities_and_climate_change", "08")[0]
    url = image_to_data_url(fig)
    _check("png path -> data url prefix", url.startswith("data:image/png;base64,"))
    payload = url.split(",", 1)[1]
    decoded = base64.b64decode(payload)
    _check("round-trip matches file bytes", decoded == fig.read_bytes())


def test_data_url_from_bytes_requires_mime() -> None:
    """Assert encoding raw bytes needs an explicit MIME and raises ValueError without one."""
    url = image_to_data_url(b"\xff\xd8\xff", mime_type="image/jpeg")
    _check("bytes + mime -> data url", url.startswith("data:image/jpeg;base64,"))
    raised = False
    try:
        image_to_data_url(b"\xff\xd8\xff")
    except ValueError:
        raised = True
    _check("bytes without mime raises", raised)


def test_unsupported_extension_raises() -> None:
    """Assert encoding a file with an unsupported extension raises ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "diagram.gif"
        bad.write_bytes(b"GIF89a")
        raised = False
        try:
            image_to_data_url(bad)
        except ValueError:
            raised = True
        _check("unsupported extension raises", raised)


# ---------------------------------------------------------------------------
# build_multimodal_content
# ---------------------------------------------------------------------------

def test_no_figures_returns_plain_string() -> None:
    """Assert building content with no figures returns the plain text string."""
    out = build_multimodal_content("hello", None)
    _check("no figures -> plain str", out == "hello", f"got {out!r}")
    out2 = build_multimodal_content("hello", [])
    _check("empty figures -> plain str", out2 == "hello", f"got {out2!r}")


def test_with_figures_returns_blocks() -> None:
    """Assert figures produce [text, image_url] content blocks with a data URL."""
    figs = discover_figures("cities_and_climate_change", "08")
    out = build_multimodal_content("describe this", figs)
    ok_shape = (
        isinstance(out, list)
        and out[0] == {"type": "text", "text": "describe this"}
        and out[1]["type"] == "image_url"
        and out[1]["image_url"]["url"].startswith("data:image/png;base64,")
    )
    _check("figures -> [text, image_url] blocks", ok_shape, f"got {out!r}")


def test_build_content_accepts_bytes_tuples_and_data_urls() -> None:
    """Assert build_multimodal_content accepts paths, (bytes, mime) tuples, and data URLs."""
    # (bytes, mime) tuple — in-memory upload path.
    out = build_multimodal_content("hi", [(b"\xff\xd8\xff", "image/jpeg")])
    ok_tuple = (
        isinstance(out, list)
        and out[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    )
    _check("(bytes, mime) tuple -> image_url block", ok_tuple, f"got {out!r}")

    # Pre-built data URL string — used verbatim.
    url = "data:image/png;base64,QUJD"
    out2 = build_multimodal_content("hi", [url])
    _check("data-url string passed through verbatim", out2[1]["image_url"]["url"] == url, f"got {out2!r}")

    # Mixed path + tuple + data-url in one call.
    fig = discover_figures("cities_and_climate_change", "08")[0]
    out3 = build_multimodal_content("hi", [fig, (b"\xff\xd8\xff", "image/jpeg"), url])
    ok_mixed = (
        len(out3) == 4
        and out3[1]["image_url"]["url"].startswith("data:image/png;base64,")
        and out3[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        and out3[3]["image_url"]["url"] == url
    )
    _check("mixed path/tuple/data-url blocks", ok_mixed, f"got {out3!r}")


# ---------------------------------------------------------------------------
# resolve_figure_filenames
# ---------------------------------------------------------------------------

def test_resolve_filenames_round_trips_discovery() -> None:
    """Assert resolve_figure_filenames round-trips discovery and skips missing files."""
    figs = discover_figures("cities_and_climate_change", "08")
    names = figure_filenames(figs)
    resolved = resolve_figure_filenames("cities_and_climate_change", names)
    _check("resolve filenames -> same paths", resolved == figs, f"got {resolved}")
    # Non-existent filenames are skipped silently.
    mixed = resolve_figure_filenames(
        "cities_and_climate_change", names + ["exercise_08_does_not_exist.png"]
    )
    _check("resolve skips missing files", mixed == figs, f"got {mixed}")


def main() -> int:
    """Run all tests and return 1 if any failed, else 0."""
    tests = [
        test_discovers_real_curriculum_figure,
        test_exercise_number_is_normalized,
        test_missing_exercise_and_course_return_empty,
        test_discovery_filters_and_isolates_by_exercise,
        test_data_url_round_trip_from_path,
        test_data_url_from_bytes_requires_mime,
        test_unsupported_extension_raises,
        test_no_figures_returns_plain_string,
        test_with_figures_returns_blocks,
        test_build_content_accepts_bytes_tuples_and_data_urls,
        test_resolve_filenames_round_trips_discovery,
    ]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
