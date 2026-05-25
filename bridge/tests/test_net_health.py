from __future__ import annotations

from ipaddress import IPv4Interface
from pathlib import Path

from instantlink_bridge.config import FtpReceiveMode, FtpSourceKind
from instantlink_bridge.net.health import (
    DnsmasqLease,
    FtpActivity,
    FtpActivityTracker,
    WifiSubnetConflict,
    build_connection_health,
    parse_dnsmasq_leases,
    read_dnsmasq_leases,
    select_camera_lease,
)


def test_parse_dnsmasq_leases_parses_valid_rows_and_skips_invalid_rows() -> None:
    leases = parse_dnsmasq_leases(
        "\n".join(
            [
                "# comment",
                "1710000600 AA:BB:CC:DD:EE:01 192.168.7.21 camera-1 01:aabb",
                "not-a-time AA:BB:CC:DD:EE:02 192.168.7.22 camera-2 01:aacc",
                "1710000700 AA:BB:CC:DD:EE:03 not-an-ip camera-3 01:aadd",
                "0 AA:BB:CC:DD:EE:04 192.168.7.24 * *",
            ]
        )
    )

    assert leases == [
        DnsmasqLease(
            expires_at=1710000600,
            mac_address="aa:bb:cc:dd:ee:01",
            ipv4="192.168.7.21",
            hostname="camera-1",
            client_id="01:aabb",
        ),
        DnsmasqLease(
            expires_at=0,
            mac_address="aa:bb:cc:dd:ee:04",
            ipv4="192.168.7.24",
            hostname=None,
            client_id=None,
        ),
    ]


def test_select_camera_lease_returns_active_same_subnet_non_host_lease() -> None:
    lease = select_camera_lease(
        [
            DnsmasqLease(999, "aa:bb:cc:dd:ee:01", "192.168.7.20", "old", None),
            DnsmasqLease(2000, "aa:bb:cc:dd:ee:02", "192.168.7.1", "host", None),
            DnsmasqLease(2000, "aa:bb:cc:dd:ee:03", "192.168.8.20", "other", None),
            DnsmasqLease(1500, "aa:bb:cc:dd:ee:04", "192.168.7.30", "camera", None),
        ],
        "192.168.7.1",
        now=1000,
    )

    assert lease == DnsmasqLease(1500, "aa:bb:cc:dd:ee:04", "192.168.7.30", "camera", None)


def test_build_connection_health_prefers_expected_usb_address_and_tracks_readiness() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        usb_carrier=True,
        usb_ipv4_addresses=["169.254.10.20", "192.168.7.1"],
        wifi_ipv4_addresses=["192.168.5.149"],
        leases=[DnsmasqLease(1200, "aa:bb:cc:dd:ee:01", "192.168.7.20", "camera", None)],
        ftp_activity=FtpActivity(
            last_connected_at=100,
            last_upload_at=1080,
            last_remote_ip="192.168.7.20",
        ),
    )

    assert health.usb_ipv4 == "192.168.7.1"
    assert health.usb_configured
    assert health.wired_carrier
    assert not health.wired_configured_no_carrier
    assert health.wired_ftp_ready
    assert health.wireless_ftp_ready
    assert health.home_wifi_ftp_ready
    assert health.peer_same_wifi_ready
    assert not health.hotspot_ftp_ready
    assert not health.hotspot_active
    assert health.home_wifi_ipv4 == "192.168.5.149"
    assert health.can_accept_ftp
    assert not health.no_receive_path
    assert health.camera_lease_active
    assert health.camera_lease is not None
    assert health.camera_lease.ipv4 == "192.168.7.20"
    assert health.ftp_recently_active


def test_build_connection_health_reports_usb_not_ready_without_expected_address() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        usb_carrier=True,
        usb_ipv4_addresses=["169.254.10.20"],
        wifi_ipv4_addresses=[],
    )

    assert health.usb_ipv4 == "169.254.10.20"
    assert not health.usb_configured
    assert not health.wired_ftp_ready
    assert not health.can_accept_ftp


def test_stale_camera_lease_is_not_active_without_wired_link() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=[],
        leases=[DnsmasqLease(1200, "aa:bb:cc:dd:ee:01", "192.168.7.20", "camera", None)],
    )

    assert health.camera_lease is not None
    assert not health.wired_ftp_ready
    assert not health.camera_lease_active


def test_camera_lease_is_not_active_without_expected_usb_address() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        usb_carrier=True,
        usb_ipv4_addresses=["169.254.10.20"],
        wifi_ipv4_addresses=[],
        leases=[DnsmasqLease(1200, "aa:bb:cc:dd:ee:01", "192.168.7.20", "camera", None)],
    )

    assert health.camera_lease is not None
    assert not health.wired_ftp_ready
    assert not health.camera_lease_active


def test_build_connection_health_separates_hotspot_and_home_wifi_addresses() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["192.168.5.149", "192.168.8.1"],
    )

    assert health.wifi_ipv4 == "192.168.8.1"
    assert health.hotspot_ipv4 == "192.168.8.1"
    assert health.home_wifi_ipv4 == "192.168.5.149"
    assert health.hotspot_ftp_ready
    assert health.hotspot_active
    assert health.home_wifi_ftp_ready
    assert health.peer_same_wifi_ready
    assert health.wireless_ftp_ready
    assert health.can_accept_ftp
    assert health.can_accept_ftp_for_mode(FtpReceiveMode.HOTSPOT)
    assert health.can_accept_ftp_for_mode(FtpReceiveMode.PEER)
    assert not health.can_accept_ftp_for_mode(FtpReceiveMode.WIRED)


def test_build_connection_health_ignores_link_local_peer_wifi() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["169.254.44.2"],
    )

    assert health.wifi_ipv4 is None
    assert health.home_wifi_ipv4 is None
    assert not health.home_wifi_ftp_ready
    assert not health.wireless_ftp_ready
    assert not health.can_accept_ftp
    assert health.no_receive_path


def test_home_wifi_ipv4_excludes_reserved_subnet_conflicts() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["192.168.7.42", "192.168.8.42", "192.168.5.149"],
    )

    assert health.home_wifi_ipv4 == "192.168.5.149"
    assert health.home_wifi_ipv4_addresses == ("192.168.5.149",)
    assert health.wifi_subnet_conflict
    assert health.wifi_subnet_conflicts == (
        WifiSubnetConflict("192.168.7.42", FtpSourceKind.USB, "192.168.7.0/24", "192.168.7.0/24"),
        WifiSubnetConflict(
            "192.168.8.42",
            FtpSourceKind.HOTSPOT,
            "192.168.8.0/24",
            "192.168.8.0/24",
        ),
    )


def test_wide_peer_wifi_network_conflicts_with_reserved_wired_subnet() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=["192.168.5.149"],
        wifi_ipv4_interfaces=[IPv4Interface("192.168.5.149/22")],
    )

    assert health.usb_configured
    assert health.wired_configured_no_carrier
    assert not health.wired_ftp_ready
    assert health.wifi_subnet_conflict
    assert health.wifi_subnet_conflicts == (
        WifiSubnetConflict("192.168.5.149", FtpSourceKind.USB, "192.168.7.0/24", "192.168.4.0/22"),
    )
    assert health.home_wifi_ipv4 is None
    assert not health.peer_same_wifi_ready
    assert health.no_receive_path


def test_wide_peer_wifi_network_can_conflict_with_multiple_reserved_subnets() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["192.168.6.42"],
        wifi_ipv4_interfaces=["192.168.6.42/20"],
    )

    assert health.wifi_subnet_conflicts == (
        WifiSubnetConflict("192.168.6.42", FtpSourceKind.USB, "192.168.7.0/24", "192.168.0.0/20"),
        WifiSubnetConflict(
            "192.168.6.42",
            FtpSourceKind.HOTSPOT,
            "192.168.8.0/24",
            "192.168.0.0/20",
        ),
    )
    assert not health.home_wifi_ftp_ready


def test_conflicting_wifi_subnet_does_not_make_peer_ready() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["192.168.7.42"],
    )

    assert health.wifi_ipv4 is None
    assert health.home_wifi_ipv4 is None
    assert health.wifi_subnet_conflict
    assert not health.home_wifi_ftp_ready
    assert not health.can_accept_ftp


def test_ftp_activity_can_be_filtered_by_receive_mode() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["192.168.8.1", "192.168.5.149"],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="192.168.8.20"),
    )

    assert health.ftp_recently_active
    assert health.ftp_recently_active_for_mode(FtpReceiveMode.AUTO)
    assert health.ftp_recently_active_for_mode(FtpReceiveMode.HOTSPOT)
    assert not health.ftp_recently_active_for_mode(FtpReceiveMode.PEER)
    assert not health.ftp_recently_active_for_mode(FtpReceiveMode.WIRED)


def test_recent_ftp_source_must_be_accepted_by_receive_mode() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=True,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=["192.168.8.1", "192.168.5.149"],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="192.168.5.20"),
    )

    assert health.recent_ftp_source_for_mode(FtpReceiveMode.AUTO) is not None
    assert health.recent_ftp_source_for_mode(FtpReceiveMode.PEER) is not None
    assert health.recent_ftp_source_for_mode(FtpReceiveMode.WIRED) is None


def test_recent_peer_ftp_source_must_match_active_peer_network() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=True,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=["192.168.5.149"],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="192.168.6.20"),
    )

    assert health.ftp_recently_active
    assert health.recent_ftp_source_for_mode(FtpReceiveMode.AUTO) is None
    assert not health.ftp_recently_active_for_mode(FtpReceiveMode.PEER)


def test_recent_peer_ftp_source_uses_actual_peer_prefix() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=["10.42.5.149"],
        wifi_ipv4_interfaces=["10.42.5.149/22"],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="10.42.6.20"),
    )

    assert health.home_wifi_ipv4_networks == ("10.42.4.0/22",)
    assert health.recent_ftp_source_for_mode(FtpReceiveMode.PEER) is FtpSourceKind.PEER
    assert health.recent_ftp_source_ready_for_mode(FtpReceiveMode.PEER)


def test_recent_peer_ftp_source_is_not_ready_when_peer_network_conflicts() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=["192.168.7.1"],
        wifi_ipv4_addresses=["192.168.5.149"],
        wifi_ipv4_interfaces=["192.168.5.149/22"],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="192.168.5.20"),
    )

    assert health.ftp_recently_active
    assert health.recent_ftp_source_for_mode(FtpReceiveMode.PEER) is None
    assert not health.recent_ftp_source_ready_for_mode(FtpReceiveMode.PEER)


def test_recent_source_readiness_requires_current_path_for_matching_mode() -> None:
    health = build_connection_health(
        checked_at=1100,
        expected_usb_ipv4="192.168.7.1",
        expected_hotspot_ipv4="192.168.8.1",
        usb_carrier=False,
        usb_ipv4_addresses=[],
        wifi_ipv4_addresses=[],
        ftp_activity=FtpActivity(last_connected_at=1080, last_remote_ip="192.168.8.20"),
    )

    assert health.recent_ftp_source_for_mode(FtpReceiveMode.HOTSPOT) is FtpSourceKind.HOTSPOT
    assert not health.recent_ftp_source_ready_for_mode(FtpReceiveMode.HOTSPOT)


def test_ftp_activity_tracker_records_thread_safe_snapshots_with_clock() -> None:
    timestamps = iter([1000.0, 1010.0])
    tracker = FtpActivityTracker(clock=lambda: next(timestamps))

    tracker.record_connection("192.168.7.20")
    tracker.record_upload("192.168.7.20")

    activity = tracker.snapshot()
    assert activity == FtpActivity(
        last_connected_at=1000.0,
        last_upload_at=1010.0,
        last_remote_ip="192.168.7.20",
    )
    assert activity.last_activity_at == 1010.0
    assert activity.is_recent(1100.0, window_s=120)
    assert not activity.is_recent(1200.0, window_s=120)


def test_read_dnsmasq_leases_uses_first_discoverable_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.leases"
    lease_file = tmp_path / "dnsmasq.leases"
    lease_file.write_text(
        "1710000600 AA:BB:CC:DD:EE:01 192.168.7.21 camera-1 01:aabb\n",
        encoding="utf-8",
    )

    assert read_dnsmasq_leases([missing, lease_file]) == [
        DnsmasqLease(
            expires_at=1710000600,
            mac_address="aa:bb:cc:dd:ee:01",
            ipv4="192.168.7.21",
            hostname="camera-1",
            client_id="01:aabb",
        )
    ]
