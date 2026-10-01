from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from instantlink_bridge.config import BridgeConfig, UiConfig, load_config, write_config
from instantlink_bridge.manager.config_payload import (
    ConfigValidationError,
    apply_config_diff,
    serialize_config,
)


def test_unlock_guard_defaults_true_and_round_trips_false(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[ui]\nlanguage = "en"\n')
    original = load_config(path)
    assert original.ui.unlock_requires_three_presses is True
    changed = replace(original, ui=replace(original.ui, unlock_requires_three_presses=False))
    write_config(changed, path)
    assert load_config(path) == changed
    assert serialize_config(changed)["ui"]["unlock_requires_three_presses"] is False


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_unlock_guard_config_and_api_reject_non_booleans(value: object) -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        UiConfig(unlock_requires_three_presses=value)  # type: ignore[arg-type]
    with pytest.raises(ConfigValidationError) as error:
        apply_config_diff(BridgeConfig(), {"ui": {"unlock_requires_three_presses": value}})
    assert error.value.field_errors == {"ui.unlock_requires_three_presses": "Must be a boolean."}


def test_unlock_guard_api_changes_only_selected_field() -> None:
    original = BridgeConfig()
    changed = apply_config_diff(original, {"ui": {"unlock_requires_three_presses": False}})
    assert changed.ui == replace(original.ui, unlock_requires_three_presses=False)
    assert changed.power == original.power
    assert changed.correction == original.correction
    assert changed.adjustments == original.adjustments
    assert (
        apply_config_diff(changed, {"ui": {"language": "zh-Hans"}}).ui.unlock_requires_three_presses
        is False
    )
