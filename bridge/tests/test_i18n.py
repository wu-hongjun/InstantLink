"""Tests for the bridge UI i18n translation table."""

from __future__ import annotations

from instantlink_bridge.ui.i18n import Language, t, translatable_strings


def test_english_passthrough_returns_source_unchanged() -> None:
    """English is the source language — no translation lookup."""

    assert t("Ready", Language.EN) == "Ready"
    assert t("Anything goes here", Language.EN) == "Anything goes here"


def test_chinese_translates_registered_strings() -> None:
    assert t("Ready", Language.ZH_HANS) == "就绪"
    assert t("Connected", Language.ZH_HANS) == "已连接"
    assert t("Searching", Language.ZH_HANS) == "搜索中"


def test_missing_translation_falls_back_to_english_source() -> None:
    """A key not present in the target language returns the source string
    so missing translations degrade gracefully (text stays readable)."""

    assert t("not-yet-translated", Language.ZH_HANS) == "not-yet-translated"


def test_string_language_tag_is_parsed() -> None:
    """The runtime carries language as a snapshot str (BCP 47); t() accepts
    both the enum and the bare tag so callers don't have to convert."""

    assert t("Ready", "zh-Hans") == "就绪"
    assert t("Ready", "en") == "Ready"
    # Unknown tag → fall back to source.
    assert t("Ready", "xx-YY") == "Ready"


def test_translatable_strings_exposes_full_target_map() -> None:
    table = translatable_strings(Language.ZH_HANS)

    # Spot-check a representative slice — the full table is owned by the
    # i18n module and shouldn't be coupled to a hard count here.
    assert table["Ready"] == "就绪"
    assert table["Settings"] == "设置"
    assert "Connected" in table
    assert "KEY1 Setting" in table
