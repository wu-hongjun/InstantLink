"""Tests for the AUTO appearance schedule and the SYSTEM → AUTO migration."""

from __future__ import annotations

import datetime as _dt

from instantlink_bridge.config import UiAppearance, parse_ui_appearance
from instantlink_bridge.ui.theme import (
    AUTO_DARK_START_HOUR,
    AUTO_LIGHT_START_HOUR,
    DARK_THEME,
    LIGHT_THEME,
    Appearance,
    resolve_auto_appearance,
    theme_for,
)


def _at(hour: int) -> _dt.datetime:
    """A deterministic wall-clock instant at the given hour for resolver tests."""

    return _dt.datetime(2026, 5, 29, hour, 0, 0)


def test_auto_window_default_is_07_to_19() -> None:
    """Spec constants stay nailed to the documented 07-19 light window."""

    assert AUTO_LIGHT_START_HOUR == 7
    assert AUTO_DARK_START_HOUR == 19


def test_auto_resolves_to_light_inside_the_window() -> None:
    assert resolve_auto_appearance(_at(7)) is Appearance.LIGHT
    assert resolve_auto_appearance(_at(12)) is Appearance.LIGHT
    assert resolve_auto_appearance(_at(18)) is Appearance.LIGHT  # 18:00 still inside


def test_auto_resolves_to_dark_outside_the_window() -> None:
    assert resolve_auto_appearance(_at(19)) is Appearance.DARK  # 19:00 starts dark
    assert resolve_auto_appearance(_at(23)) is Appearance.DARK
    assert resolve_auto_appearance(_at(0)) is Appearance.DARK
    assert resolve_auto_appearance(_at(6)) is Appearance.DARK   # 06:00 still dark


def test_auto_window_is_inclusive_on_start_exclusive_on_end() -> None:
    """Boundary semantics are the same convention as `range()` / time-of-day APIs:
    the moment the light window starts you're in light, the moment the dark
    window starts you're in dark. Documented here so future tweaks don't drift."""

    # Use a custom window to make the boundary check independent of the defaults.
    light = resolve_auto_appearance(_at(9), light_start_hour=9, dark_start_hour=17)
    dark = resolve_auto_appearance(_at(17), light_start_hour=9, dark_start_hour=17)
    assert light is Appearance.LIGHT
    assert dark is Appearance.DARK


def test_theme_for_auto_picks_the_right_palette() -> None:
    """`theme_for("auto")` calls the resolver internally — at a daytime hour
    it must hand back LIGHT_THEME; at night, DARK_THEME. We can't fully pin
    the clock here without monkeypatching, but we *can* verify both palettes
    are still wired up correctly through the AUTO branch by exercising the
    enum + string forms directly."""

    # AUTO via enum routes through the resolver. Either palette is acceptable
    # depending on the moment the test runs — the contract is that AUTO is
    # never a third palette, only LIGHT or DARK.
    assert theme_for(Appearance.AUTO) in {LIGHT_THEME, DARK_THEME}
    assert theme_for("auto") in {LIGHT_THEME, DARK_THEME}


def test_theme_for_accepts_legacy_system_string_as_auto() -> None:
    """Bridges in the field have `appearance = "system"` written into
    /etc/InstantLinkBridge/config.toml. After this release the renderer
    receives the string straight from the snapshot, so it must still
    resolve to a valid theme rather than falling through to "unknown"."""

    assert theme_for("system") in {LIGHT_THEME, DARK_THEME}


def test_theme_for_light_and_dark_are_unchanged() -> None:
    """Regression check: the AUTO plumbing must not affect the LIGHT/DARK
    fast paths that every test snapshot today still uses."""

    assert theme_for("light") is LIGHT_THEME
    assert theme_for("dark") is DARK_THEME
    assert theme_for(Appearance.LIGHT) is LIGHT_THEME
    assert theme_for(Appearance.DARK) is DARK_THEME


def test_theme_for_unknown_string_falls_back_to_light() -> None:
    """Unknown / garbage values keep returning LIGHT — same as before AUTO."""

    assert theme_for("magenta") is LIGHT_THEME


def test_parse_ui_appearance_accepts_canonical_values() -> None:
    assert parse_ui_appearance("light") is UiAppearance.LIGHT
    assert parse_ui_appearance("dark") is UiAppearance.DARK
    assert parse_ui_appearance("auto") is UiAppearance.AUTO


def test_parse_ui_appearance_migrates_legacy_system_to_auto() -> None:
    """Existing deployments have `appearance = "system"` in their config; the
    parser must roll it forward instead of raising on next boot."""

    assert parse_ui_appearance("system") is UiAppearance.AUTO


def test_parse_ui_appearance_rejects_garbage() -> None:
    """Unknown values still error so a typo in config.toml is loud, not silent."""

    try:
        parse_ui_appearance("midnight")
    except ValueError as exc:
        assert "[ui].appearance" in str(exc)
    else:  # pragma: no cover - we want the ValueError to actually fire
        raise AssertionError("parse_ui_appearance should have raised on 'midnight'")
