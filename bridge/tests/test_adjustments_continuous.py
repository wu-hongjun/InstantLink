"""Tests for plan 036 phase 1: continuous integer adjustment axes.

Validates that:
- Off-grid values (e.g. saturation=7) load successfully via load_config.
- Out-of-range values (e.g. saturation=101) raise with a clear error.
- The picker UI still works with the legacy 5-position discrete options.
- selected_option_index falls back to the nearest discrete option for off-grid values.

Rounding rule for off-grid picker fallback: nearest discrete option by
absolute distance; ties broken towards the lower index (lower-valued option).
Example: saturation=7 → nearest of {-100,-50,0,+50,+100} is 0 (index 2).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from instantlink_bridge.config import (
    AdjustmentsConfig,
    BridgeConfig,
    load_config,
    render_config,
    write_config,
)
from instantlink_bridge.ui.settings import (
    ADJUSTMENT_OPTIONS,
    VIGNETTE_OPTIONS,
    SettingKey,
    selected_option_index,
)

# ---------------------------------------------------------------------------
# Off-grid continuous values load successfully
# ---------------------------------------------------------------------------


def test_adjustments_config_accepts_off_grid_continuous_values(tmp_path: Path) -> None:
    """load_config accepts off-grid values like saturation=7, exposure=-33, etc."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[adjustments]",
                "saturation = 7",
                "exposure = -33",
                "sharpness = 88",
                "hue = -45",
                "vignette = 17",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.adjustments.saturation == 7
    assert config.adjustments.exposure == -33
    assert config.adjustments.sharpness == 88
    assert config.adjustments.hue == -45
    assert config.adjustments.vignette == 17


def test_adjustments_config_off_grid_round_trips_via_write_config(tmp_path: Path) -> None:
    """Off-grid values survive a write_config / load_config round-trip."""
    config_path = tmp_path / "config.toml"
    original = replace(
        BridgeConfig(),
        adjustments=AdjustmentsConfig(
            preset="Custom",
            saturation=7,
            exposure=-33,
            sharpness=88,
            hue=-45,
            vignette=17,
        ),
    )
    write_config(original, config_path)
    loaded = load_config(config_path)

    assert loaded.adjustments.saturation == 7
    assert loaded.adjustments.exposure == -33
    assert loaded.adjustments.sharpness == 88
    assert loaded.adjustments.hue == -45
    assert loaded.adjustments.vignette == 17


def test_adjustments_config_off_grid_round_trips_via_render_config() -> None:
    """render_config encodes off-grid values as plain integers that re-parse cleanly."""
    cfg = AdjustmentsConfig(preset="Custom", saturation=7, exposure=-33, sharpness=88, hue=-45)
    text = render_config(BridgeConfig(adjustments=cfg))
    assert "saturation = 7" in text
    assert "exposure = -33" in text
    assert "sharpness = 88" in text
    assert "hue = -45" in text


# ---------------------------------------------------------------------------
# Out-of-range values are rejected with a clear error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("saturation", 101),
        ("saturation", -150),
        ("vignette", -5),
        ("vignette", 101),
    ],
)
def test_adjustments_config_rejects_out_of_range(
    tmp_path: Path, field: str, bad_value: int
) -> None:
    """Out-of-range values raise ValueError with the field name in the message."""
    config_path = tmp_path / f"{field}_{bad_value}.toml"
    config_path.write_text(
        f"[adjustments]\n{field} = {bad_value}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=field):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("saturation", 101),
        ("saturation", -150),
        ("exposure", 101),
        ("exposure", -101),
        ("sharpness", 200),
        ("hue", -101),
        ("vignette", -5),
        ("vignette", 101),
    ],
)
def test_adjustments_config_direct_construction_rejects_out_of_range(
    field: str, bad_value: int
) -> None:
    """Constructing AdjustmentsConfig directly with an out-of-range value raises ValueError."""
    with pytest.raises(ValueError, match=field):
        AdjustmentsConfig(**{field: bad_value})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Picker UI still works with legacy 5-position discrete options
# ---------------------------------------------------------------------------


def test_adjustment_options_constants_unchanged() -> None:
    """ADJUSTMENT_OPTIONS still exposes the 5 legacy discrete options."""
    values = [opt.value for opt in ADJUSTMENT_OPTIONS]
    assert values == [-100, -50, 0, 50, 100]


def test_vignette_options_constants_unchanged() -> None:
    """VIGNETTE_OPTIONS still exposes the 5 legacy discrete options."""
    values = [opt.value for opt in VIGNETTE_OPTIONS]
    assert values == [0, 25, 50, 75, 100]


@pytest.mark.parametrize(
    ("saturation", "expected_index"),
    [
        (-100, 0),
        (-50, 1),
        (0, 2),
        (50, 3),
        (100, 4),
    ],
)
def test_selected_option_index_on_grid_values(saturation: int, expected_index: int) -> None:
    """On-grid values resolve to their exact picker index without the nearest fallback."""
    config = replace(BridgeConfig(), adjustments=AdjustmentsConfig(saturation=saturation))
    assert selected_option_index(config, SettingKey.ADJUST_SATURATION) == expected_index


# ---------------------------------------------------------------------------
# Nearest-option fallback for off-grid values
# ---------------------------------------------------------------------------


def test_selected_option_index_falls_back_to_nearest_for_off_grid() -> None:
    """saturation=7 is closest to 0 (index 2); picker renders with that selection.

    Rounding rule: nearest discrete option by absolute distance.
    7 is 7 away from 0 and 43 away from 50, so 0 (index 2) wins.
    """
    config = replace(BridgeConfig(), adjustments=AdjustmentsConfig(saturation=7))
    index = selected_option_index(config, SettingKey.ADJUST_SATURATION)
    assert index == 2, (
        f"saturation=7 should map to index 2 (value 0), got index {index} "
        f"(value {ADJUSTMENT_OPTIONS[index].value})"
    )


@pytest.mark.parametrize(
    ("saturation", "expected_index", "note"),
    [
        (-75, 0, "tie between -100 and -50 → lower index wins"),  # dist to -100=25, dist to -50=25
        (-74, 1, "nearer to -50"),    # dist to -100=26, dist to -50=24
        (-76, 0, "nearer to -100"),   # dist to -100=24, dist to -50=26
        (1, 2, "nearest to 0"),
        (24, 2, "still nearest to 0"),
        (25, 2, "tie between 0 and 50 → lower index (0) wins"),
        (26, 3, "nearer to 50"),
        (99, 4, "nearest to 100"),
    ],
)
def test_selected_option_index_nearest_rounding(
    saturation: int, expected_index: int, note: str
) -> None:
    """Nearest-option rounding for a range of off-grid saturation values."""
    config = replace(BridgeConfig(), adjustments=AdjustmentsConfig(saturation=saturation))
    index = selected_option_index(config, SettingKey.ADJUST_SATURATION)
    assert index == expected_index, (
        f"saturation={saturation} ({note}): expected index {expected_index} "
        f"(value {ADJUSTMENT_OPTIONS[expected_index].value}), "
        f"got index {index} (value {ADJUSTMENT_OPTIONS[index].value})"
    )


def test_selected_option_index_vignette_off_grid_nearest() -> None:
    """vignette=17 is nearest to 25 (index 1) in {0,25,50,75,100}.

    dist to 0=17, dist to 25=8 → 25 wins (index 1).
    """
    config = replace(BridgeConfig(), adjustments=AdjustmentsConfig(vignette=17))
    index = selected_option_index(config, SettingKey.ADJUST_VIGNETTE)
    assert index == 1, (
        f"vignette=17 should map to index 1 (value 25), got index {index} "
        f"(value {VIGNETTE_OPTIONS[index].value})"
    )
