"""Tests for the bridge UI i18n translation table."""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------------
# Plan 040: iOS-style confirmation dialog strings translate to zh-Hans
# ---------------------------------------------------------------------------


# zh-Hans intentionally uses the full-width question mark — that is the
# Apple iOS convention this i18n module mirrors. Each parametrised entry
# carries an RUF001 inline suppression so ruff's ambiguous-glyph check
# doesn't trip on the deliberate localisation choice.
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Forget printer?", "忘记打印机？"),  # noqa: RUF001
        ("Reset credentials?", "还原凭据？"),  # noqa: RUF001
        ("Reset connection?", "还原连接？"),  # noqa: RUF001
        ("Re-pair printer?", "重新配对打印机？"),  # noqa: RUF001
        ("Save preset?", "存储预设？"),  # noqa: RUF001
        ("Cancel", "取消"),
        ("Reset", "还原"),
        ("Save", "存储"),
        ("Delete", "删除"),
        ("Overwrite", "覆盖"),
    ],
)
def test_zh_hans_confirmation_dialog_strings(source: str, expected: str) -> None:
    """The 7 dialog flows (plan 040) need both title + verb labels translated."""

    assert t(source, Language.ZH_HANS) == expected


# ---------------------------------------------------------------------------
# Plan 037 polish #15: datestamp format preset names — translate vs keep
# ---------------------------------------------------------------------------


def test_zh_hans_datestamp_format_modern_quartz_labprint_translated() -> None:
    """Plan 037 polish #15: descriptive English datestamp names get
    translated to zh-Hans; brand names (Olympus, Contax) stay Latin."""

    assert t("Modern", Language.ZH_HANS) == "现代"
    assert t("Quartz Date", Language.ZH_HANS) == "石英日期"
    assert t("Lab Print", Language.ZH_HANS) == "冲印店"


def test_zh_hans_olympus_contax_stay_latin() -> None:
    """Plan 037 polish #15 (regression guard): Olympus and Contax are
    real product brands and intentionally fall through untranslated, in
    line with the i18n doctrine of leaving brand identifiers in Latin.
    """

    assert t("Olympus", Language.ZH_HANS) == "Olympus"
    assert t("Contax", Language.ZH_HANS) == "Contax"


# ---------------------------------------------------------------------------
# Plan 037 polish #6: preset "edited" badge translation
# ---------------------------------------------------------------------------


def test_zh_hans_preset_edited_marker_translates() -> None:
    """Plan 037 polish #6: the "edited" badge that replaces the cryptic
    "*" marker on the Preset row translates to zh-Hans."""

    assert t("edited", Language.ZH_HANS) == "已编辑"


# ---------------------------------------------------------------------------
# Plan 037 polish #8: "Camera link" row label translation
# ---------------------------------------------------------------------------


def test_zh_hans_camera_link_label_translates() -> None:
    """Plan 037 polish #8: the renamed FTP_RECEIVE_MODE row label
    ("Camera link", was "Wi-Fi Mode") has a zh-Hans translation so the
    label reads naturally in the localised settings list."""

    assert t("Camera link", Language.ZH_HANS) == "相机链路"


# ---------------------------------------------------------------------------
# Plan 037 polish #14: Hue help string trailing-period cleanup
# ---------------------------------------------------------------------------


def test_hue_help_zh_hans_has_no_trailing_full_stop() -> None:
    """Plan 037 polish #14: the source Hue help text dropped its trailing
    period to match sibling help strings; the zh-Hans translation drops
    its corresponding full-width period."""

    translated = t("Tint. Left toward orange, right toward blue", Language.ZH_HANS)
    assert translated == "色调。左偏橙色，右偏蓝色"  # noqa: RUF001
    assert not translated.endswith("。")


# ---------------------------------------------------------------------------
# Plan 050: iPhone sync strings — Send to picker, pairing QR, readiness copy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Send to", "发送到"),
        ("Where received photos go", "接收照片的去向"),
        ("Both", "两者"),
        ("iPhone pairing", "iPhone 配对"),
        ("Show a QR code to pair your iPhone", "显示二维码以配对 iPhone"),
        ("Scan with InstantLink app", "请用 InstantLink App 扫码"),
        ("Pairing unavailable", "配对不可用"),
        ("Sync to iPhone", "同步到 iPhone"),
        ("Printer off · photos sync only", "打印机已关闭 · 仅同步照片"),
        ("No film · photos sync only", "无相纸 · 仅同步照片"),
        # The lowercase "connected" key stays for the Bluetooth diagnostics
        # row value; the READY-card sync chip now uses "active" (plan 051
        # P3.9) and the templated "{n} pending" (P3.10) below.
        ("connected", "已连接"),
    ],
)
def test_zh_hans_iphone_sync_strings(source: str, expected: str) -> None:
    """Plan 050: every new sync-surface string carries a zh-Hans entry."""

    assert t(source, Language.ZH_HANS) == expected


def test_zh_hans_iphone_brand_stays_latin() -> None:
    """The "iPhone" brand identifier intentionally falls through
    untranslated, matching the i18n doctrine for Wi-Fi / FTP / INSTAX."""

    assert t("iPhone", Language.ZH_HANS) == "iPhone"


# ---------------------------------------------------------------------------
# Plan 051 pass 2: sync-service honesty, footer, and discoverability strings
# translate to zh-Hans (EN + _ZH_HANS required for every new user-visible
# string).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Sync starting", "同步启动中"),
        ("Sync failed · restart bridge", "同步失败 · 请重启桥接"),
        ("Sync starting · try again", "同步启动中 · 请稍后再试"),
        ("Enable in Print > Send to", "请在 打印 > 发送到 中启用"),
        ("Pair iPhone: press KEY3", "配对 iPhone：按 KEY3"),  # noqa: RUF001
        ("Pair iPhone: Settings > Network", "配对 iPhone：设置 > 网络"),  # noqa: RUF001
        ("KEY3 Pair", "KEY3 配对"),
        (
            "Where received photos go · Pair iPhone: Network page",
            "接收照片的去向 · 配对 iPhone：网络页",  # noqa: RUF001
        ),
        (
            "Show a QR code to pair your iPhone · Send to: Print page",
            "显示二维码以配对 iPhone · 发送到：打印页",  # noqa: RUF001
        ),
    ],
)
def test_zh_hans_sync_pass2_strings(source: str, expected: str) -> None:
    assert t(source, Language.ZH_HANS) == expected


# ---------------------------------------------------------------------------
# Plan 051 pass 3: sync-chip copy (P3.9 / P3.10) and the token-rotation
# flow (P3.11). Every new user-visible string carries a zh-Hans entry; the
# pending count is a full template so each language owns its own spacing
# (zh-Hans drops the space before the measure word).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("{n} pending", "{n}张待传"),
        ("active", "活跃"),
        ("Reset sync token", "还原同步令牌"),
        ("Reset sync token?", "还原同步令牌？"),  # noqa: RUF001
        (
            "A new pairing token will be generated. All paired iPhones must scan the new QR.",
            "将生成新的配对令牌，所有已配对的 iPhone 需重新扫码。",  # noqa: RUF001
        ),
        ("Sync token reset", "同步令牌已还原"),
        ("Token reset failed", "令牌还原失败"),
        (
            "New pairing token; unpairs all iPhones",
            "生成新的配对令牌；所有 iPhone 需重新配对",  # noqa: RUF001
        ),
    ],
)
def test_zh_hans_sync_pass3_strings(source: str, expected: str) -> None:
    assert t(source, Language.ZH_HANS) == expected


def test_pending_measure_word_template_renders_without_space() -> None:
    """P3.10: the zh-Hans pending template must yield "3张待传" (count flush
    against the measure word) while EN keeps the space."""

    assert t("{n} pending", Language.ZH_HANS).format(n=3) == "3张待传"
    assert t("{n} pending", Language.EN).format(n=3) == "3 pending"


def test_lowercase_pending_key_removed_from_table() -> None:
    """The old concatenation key ("pending" → "张待传") is retired; only the
    templated form remains so no caller can rebuild the mis-spaced chip."""

    assert "pending" not in translatable_strings(Language.ZH_HANS)
