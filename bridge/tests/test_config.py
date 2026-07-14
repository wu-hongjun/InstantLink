from __future__ import annotations

from pathlib import Path

from instantlink_bridge.ble.models import PrinterModel
from instantlink_bridge.config import (
    AdjustmentsConfig,
    BridgeConfig,
    DatestampFormat,
    FtpConfig,
    FtpReceiveMode,
    PowerBackend,
    PowerConfig,
    PrinterConfig,
    SyncConfig,
    SyncDestination,
    WorkflowConfig,
    ipv4_24_network,
    ipv4_in_24_subnet,
    is_link_local_ipv4,
    load_config,
    write_config,
)
from instantlink_bridge.imaging.pipeline import FitMode


def test_ftp_bind_host_defaults_to_all_interfaces(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'host = "192.168.7.1"',
                "port = 21",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ftp.bind_host == "0.0.0.0"
    assert config.ftp.host == "192.168.7.1"
    assert config.ftp.hotspot_host == "192.168.8.1"
    assert config.ftp.username == "ib"
    assert config.ftp.mode is FtpReceiveMode.HOTSPOT
    assert config.printer.quality == 100
    assert config.power.backend is PowerBackend.X306
    assert not config.power.idle_poweroff_enabled


def test_ipv4_24_subnet_helpers_detect_transport_membership() -> None:
    assert str(ipv4_24_network("192.168.7.1")) == "192.168.7.0/24"
    assert ipv4_in_24_subnet("192.168.7.42", "192.168.7.1")
    assert not ipv4_in_24_subnet("192.168.8.42", "192.168.7.1")
    assert is_link_local_ipv4("169.254.44.2")
    assert not is_link_local_ipv4("192.168.5.20")
    assert not is_link_local_ipv4("not-an-ip")


def test_ftp_receive_mode_can_be_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[ftp]\nmode = "hotspot"\n', encoding="utf-8")

    config = load_config(config_path)

    assert config.ftp.mode is FtpReceiveMode.HOTSPOT


def test_ftp_receive_mode_must_be_known(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[ftp]\nmode = "bluetooth"\n', encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[ftp].mode" in str(exc)
    else:
        raise AssertionError("expected invalid FTP receive mode to fail")


def test_ftp_bind_host_can_be_overridden(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'bind_host = "127.0.0.1"',
                'host = "192.168.7.1"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ftp.bind_host == "127.0.0.1"


def test_ftp_preferred_wifi_host_can_be_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'preferred_wifi_host = "192.168.5.7"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ftp.preferred_wifi_host == "192.168.5.7"


def test_ftp_preferred_wifi_host_must_be_ipv4(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[ftp]\npreferred_wifi_host = "not-an-ip"\n', encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[ftp].preferred_wifi_host" in str(exc)
    else:
        raise AssertionError("expected invalid preferred Wi-Fi host to fail")


def test_ftp_hotspot_host_can_be_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[ftp]\nhotspot_host = "192.168.8.1"\n', encoding="utf-8")

    config = load_config(config_path)

    assert config.ftp.hotspot_host == "192.168.8.1"


def test_ftp_hotspot_host_must_not_overlap_usb_subnet(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'host = "192.168.7.1"',
                'hotspot_host = "192.168.7.2"',
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[ftp].hotspot_host" in str(exc)
        assert "192.168.7.0/24" in str(exc)
    else:
        raise AssertionError("expected overlapping hotspot subnet to fail")


def test_ftp_preferred_wifi_host_must_not_overlap_usb_subnet(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'host = "192.168.7.1"',
                'preferred_wifi_host = "192.168.7.2"',
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[ftp].preferred_wifi_host" in str(exc)
    else:
        raise AssertionError("expected overlapping preferred Wi-Fi subnet to fail")


def test_ftp_preferred_wifi_host_must_not_overlap_hotspot_subnet(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[ftp]",
                'hotspot_host = "192.168.8.1"',
                'preferred_wifi_host = "192.168.8.42"',
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[ftp].preferred_wifi_host" in str(exc)
        assert "192.168.8.0/24" in str(exc)
    else:
        raise AssertionError("expected overlapping preferred Wi-Fi subnet to fail")


def test_printer_keepalive_defaults_to_ten_seconds(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[printer]\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.printer.keepalive_interval_s == 10.0


def test_power_backend_and_idle_policy_can_be_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[power]",
                'backend = "pisugar"',
                "battery_poll_interval_s = 15",
                "idle_dim_after_s = 10",
                "idle_screen_off_after_s = 20",
                "idle_deep_after_s = 30",
                "idle_poweroff_after_s = 40",
                "idle_poweroff_enabled = false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.power.backend is PowerBackend.PISUGAR
    assert config.power.battery_poll_interval_s == 15.0
    assert not config.power.idle_poweroff_enabled


def test_power_backend_must_be_known(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[power]\nbackend = "battery-mystery"\n', encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[power].backend" in str(exc)
    else:
        raise AssertionError("expected invalid power backend to fail")


def test_printer_fit_defaults_to_auto(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[printer]\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.printer.fit is FitMode.AUTO


def test_printer_keepalive_can_be_overridden(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[printer]\nkeepalive_interval_s = 15\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.printer.keepalive_interval_s == 15.0


def test_printer_keepalive_must_be_positive(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[printer]\nkeepalive_interval_s = 0\n", encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[printer].keepalive_interval_s" in str(exc)
    else:
        raise AssertionError("expected invalid keepalive interval to fail")


def test_printer_keepalive_must_be_finite(tmp_path: Path) -> None:
    for invalid in ("nan", "inf"):
        config_path = tmp_path / f"{invalid}.toml"
        config_path.write_text(
            f"[printer]\nkeepalive_interval_s = {invalid}\n",
            encoding="utf-8",
        )

        try:
            load_config(config_path)
        except ValueError as exc:
            assert "[printer].keepalive_interval_s" in str(exc)
        else:
            raise AssertionError(f"expected {invalid} keepalive interval to fail")


def test_printer_search_interval_defaults_and_override(tmp_path: Path) -> None:
    default_path = tmp_path / "default.toml"
    default_path.write_text('[printer]\nmodel = "square"\n', encoding="utf-8")
    assert load_config(default_path).printer.search_interval_s == 5.0

    override_path = tmp_path / "override.toml"
    override_path.write_text("[printer]\nsearch_interval_s = 30\n", encoding="utf-8")
    assert load_config(override_path).printer.search_interval_s == 30.0


def test_printer_search_interval_must_be_positive_and_finite(tmp_path: Path) -> None:
    for invalid in ("0", "-1", "nan", "inf"):
        config_path = tmp_path / f"search-{invalid}.toml"
        config_path.write_text(
            f"[printer]\nsearch_interval_s = {invalid}\n",
            encoding="utf-8",
        )
        try:
            load_config(config_path)
        except ValueError as exc:
            assert "[printer].search_interval_s" in str(exc)
        else:
            raise AssertionError(f"expected {invalid} search interval to fail")


def test_workflow_auto_print_delay_can_be_configured(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workflow]\nauto_print_delay_s = 5\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.workflow.auto_print_delay_s == 5.0


def test_workflow_can_allow_print_without_film(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workflow]\nallow_print_without_film = true\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.workflow.allow_print_without_film


def test_workflow_auto_print_delay_can_be_off_or_zero(tmp_path: Path) -> None:
    off_path = tmp_path / "off.toml"
    off_path.write_text('[workflow]\nauto_print_delay_s = "off"\n', encoding="utf-8")
    zero_path = tmp_path / "zero.toml"
    zero_path.write_text("[workflow]\nauto_print_delay_s = 0\n", encoding="utf-8")

    assert load_config(off_path).workflow.auto_print_delay_s is None
    assert load_config(zero_path).workflow.auto_print_delay_s == 0.0


def test_workflow_legacy_auto_print_delay_maps_to_preview_delay(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workflow]\nauto_print_delay_s = 1.5\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.workflow.auto_print_delay_s == 5.0


def test_workflow_auto_print_delay_must_not_be_negative(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workflow]\nauto_print_delay_s = -1\n", encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[workflow].auto_print_delay_s" in str(exc)
    else:
        raise AssertionError("expected invalid auto-print delay to fail")


def test_write_config_round_trips_runtime_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = BridgeConfig(
        ftp=FtpConfig(mode=FtpReceiveMode.PEER),
        printer=PrinterConfig(
            model=PrinterModel.WIDE,
            fit=FitMode.CONTAIN,
            quality=95,
            print_option=2,
            keepalive_interval_s=15,
            search_interval_s=5,
        ),
        workflow=WorkflowConfig(auto_print_delay_s=5, allow_print_without_film=True),
        power=PowerConfig(backend=PowerBackend.X306, idle_poweroff_after_s=9000),
    )

    write_config(config, config_path)
    round_tripped = load_config(config_path)

    assert round_tripped.ftp.mode is FtpReceiveMode.PEER
    assert round_tripped.printer.model == PrinterModel.WIDE
    assert round_tripped.printer.fit == FitMode.CONTAIN
    assert round_tripped.printer.quality == 95
    assert round_tripped.printer.print_option == 2
    assert round_tripped.printer.keepalive_interval_s == 15
    assert round_tripped.printer.search_interval_s == 5
    assert round_tripped.workflow.auto_print_delay_s == 5
    assert round_tripped.workflow.allow_print_without_film
    assert round_tripped.power.backend is PowerBackend.X306
    assert round_tripped.power.idle_poweroff_after_s == 9000


# ---------------------------------------------------------------------------
# Plan 037 phase 4: customizable watermark + datestamp format presets
# ---------------------------------------------------------------------------


def test_watermark_text_default_is_empty() -> None:
    """Plan 037 phase 4: dropped the hardcoded "InstantLink" default."""
    assert AdjustmentsConfig().watermark_text == ""


def test_datestamp_format_default_is_quartz_date() -> None:
    """Default datestamp preset mirrors the macOS app's Quartz Date."""
    assert AdjustmentsConfig().datestamp_format is DatestampFormat.QUARTZ_DATE


def test_datestamp_format_round_trip_toml(tmp_path: Path) -> None:
    """Each datestamp preset survives a write/load cycle as the same enum value."""

    for fmt in DatestampFormat:
        config_path = tmp_path / f"{fmt.value}.toml"
        config = BridgeConfig(adjustments=AdjustmentsConfig(datestamp_format=fmt))
        write_config(config, config_path)
        round_tripped = load_config(config_path)
        assert round_tripped.adjustments.datestamp_format is fmt, f"{fmt.value} did not round-trip"


def test_datestamp_format_parse_unknown_raises(tmp_path: Path) -> None:
    """An unrecognised datestamp_format string fails fast with a useful message."""

    config_path = tmp_path / "bad.toml"
    config_path.write_text(
        '[adjustments]\ndatestamp_format = "polaroid"\n',
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[adjustments].datestamp_format" in str(exc)
    else:
        raise AssertionError("expected unknown datestamp_format to fail")


def test_watermark_text_round_trips_custom_value(tmp_path: Path) -> None:
    """Custom watermark text survives the TOML round-trip (no default override)."""

    config_path = tmp_path / "config.toml"
    config = BridgeConfig(adjustments=AdjustmentsConfig(watermark_text="Hello"))
    write_config(config, config_path)
    round_tripped = load_config(config_path)
    assert round_tripped.adjustments.watermark_text == "Hello"
    assert round_tripped.adjustments.datestamp_format is DatestampFormat.QUARTZ_DATE


# ---------------------------------------------------------------------------
# Plan 050: [sync] section for iPhone auto-sync
# ---------------------------------------------------------------------------


def test_sync_defaults_when_section_missing(tmp_path: Path) -> None:
    """A config file without a [sync] table yields the print-only defaults."""

    config_path = tmp_path / "config.toml"
    config_path.write_text("[printer]\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.sync.destination is SyncDestination.PRINT
    assert config.sync.port == 8721
    assert config.sync.outbox_dir == Path("/var/lib/InstantLinkBridge/sync-outbox")
    assert config.sync.outbox_budget_mb == 2048
    assert config.sync.token_path == Path("/etc/InstantLinkBridge/sync.token")
    assert not config.sync.sync_enabled
    assert config.sync.print_enabled


def test_sync_destination_enables_expected_pipelines() -> None:
    """sync_enabled / print_enabled derive from the destination value."""

    print_only = SyncConfig(destination=SyncDestination.PRINT)
    assert not print_only.sync_enabled
    assert print_only.print_enabled

    iphone_only = SyncConfig(destination=SyncDestination.IPHONE)
    assert iphone_only.sync_enabled
    assert not iphone_only.print_enabled

    both = SyncConfig(destination=SyncDestination.BOTH)
    assert both.sync_enabled
    assert both.print_enabled


def test_sync_destination_round_trip_toml(tmp_path: Path) -> None:
    """Each sync destination survives a write/load cycle as the same enum value."""

    for destination in SyncDestination:
        config_path = tmp_path / f"{destination.value}.toml"
        config = BridgeConfig(sync=SyncConfig(destination=destination))
        write_config(config, config_path)
        round_tripped = load_config(config_path)
        assert round_tripped.sync.destination is destination, (
            f"{destination.value} did not round-trip"
        )


def test_write_config_round_trips_sync_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = BridgeConfig(
        sync=SyncConfig(
            destination=SyncDestination.BOTH,
            port=9000,
            outbox_dir=Path("/var/lib/InstantLinkBridge/outbox-alt"),
            outbox_budget_mb=512,
            token_path=Path("/etc/InstantLinkBridge/alt.token"),
        )
    )

    write_config(config, config_path)
    round_tripped = load_config(config_path)

    assert round_tripped.sync.destination is SyncDestination.BOTH
    assert round_tripped.sync.port == 9000
    assert round_tripped.sync.outbox_dir == Path("/var/lib/InstantLinkBridge/outbox-alt")
    assert round_tripped.sync.outbox_budget_mb == 512
    assert round_tripped.sync.token_path == Path("/etc/InstantLinkBridge/alt.token")


def test_sync_destination_must_be_known(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[sync]\ndestination = "android"\n', encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "[sync].destination" in str(exc)
    else:
        raise AssertionError("expected unknown sync destination to fail")


def test_sync_port_must_be_in_range(tmp_path: Path) -> None:
    for invalid in ("0", "65536", "-1"):
        config_path = tmp_path / f"port-{invalid}.toml"
        config_path.write_text(f"[sync]\nport = {invalid}\n", encoding="utf-8")

        try:
            load_config(config_path)
        except ValueError as exc:
            assert "[sync].port" in str(exc)
        else:
            raise AssertionError(f"expected port {invalid} to fail")


def test_sync_outbox_budget_must_be_positive(tmp_path: Path) -> None:
    for invalid in ("0", "-1"):
        config_path = tmp_path / f"budget-{invalid}.toml"
        config_path.write_text(f"[sync]\noutbox_budget_mb = {invalid}\n", encoding="utf-8")

        try:
            load_config(config_path)
        except ValueError as exc:
            assert "[sync].outbox_budget_mb" in str(exc)
        else:
            raise AssertionError(f"expected outbox budget {invalid} to fail")
