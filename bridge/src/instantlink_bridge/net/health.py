"""Connection health model for wired and wireless FTP paths."""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
from threading import Lock

from instantlink_bridge.config import (
    FtpReceiveMode,
    FtpSourceKind,
    ipv4_24_network,
)
from instantlink_bridge.net.addresses import (
    detect_ipv4_addresses_for_interface,
    detect_ipv4_interfaces_for_interface,
    detect_link_carrier,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_USB_INTERFACE = "usb0"
DEFAULT_WIFI_INTERFACE = "wlan0"
DEFAULT_DNSMASQ_LEASE_PATHS = (
    Path("/var/lib/misc/dnsmasq.leases"),
    Path("/var/lib/dnsmasq/dnsmasq.leases"),
    Path("/run/dnsmasq/dnsmasq.leases"),
)
DEFAULT_FTP_RECENT_WINDOW_S = 300.0


@dataclass(frozen=True, slots=True)
class DnsmasqLease:
    """A parsed dnsmasq DHCP lease entry."""

    expires_at: int
    mac_address: str
    ipv4: str
    hostname: str | None
    client_id: str | None

    def is_active(self, now: float) -> bool:
        """Return whether this lease is currently active."""

        return self.expires_at == 0 or self.expires_at > now


@dataclass(frozen=True, slots=True)
class FtpActivity:
    """Recent FTP activity visible to the health model."""

    last_connected_at: float | None = None
    last_upload_at: float | None = None
    last_remote_ip: str | None = None

    @property
    def last_activity_at(self) -> float | None:
        """Return the newest recorded FTP activity time."""

        values = [
            value for value in (self.last_connected_at, self.last_upload_at) if value is not None
        ]
        return max(values) if values else None

    def is_recent(self, now: float, window_s: float = DEFAULT_FTP_RECENT_WINDOW_S) -> bool:
        """Return whether any FTP event happened within the requested window."""

        last_activity_at = self.last_activity_at
        return last_activity_at is not None and now - last_activity_at <= window_s


class FtpActivityTracker:
    """Thread-safe hooks for recording FTP connection and upload activity."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = Lock()
        self._activity = FtpActivity()

    def record_connection(self, remote_ip: str) -> None:
        """Record a remote FTP connection attempt or session."""

        now = self._clock()
        with self._lock:
            self._activity = FtpActivity(
                last_connected_at=now,
                last_upload_at=self._activity.last_upload_at,
                last_remote_ip=remote_ip,
            )

    def record_upload(self, remote_ip: str) -> None:
        """Record a completed FTP upload."""

        now = self._clock()
        with self._lock:
            self._activity = FtpActivity(
                last_connected_at=self._activity.last_connected_at,
                last_upload_at=now,
                last_remote_ip=remote_ip,
            )

    def snapshot(self) -> FtpActivity:
        """Return an immutable snapshot of current FTP activity."""

        with self._lock:
            return self._activity


@dataclass(frozen=True, slots=True)
class WifiSubnetConflict:
    """A Wi-Fi address that overlaps a reserved FTP transport subnet."""

    ipv4: str
    reserved_source: FtpSourceKind
    reserved_network: str
    wifi_network: str


@dataclass(frozen=True, slots=True)
class ConnectionHealth:
    """Current network health for InstantLink Bridge FTP receive paths."""

    checked_at: float
    usb_interface: str
    expected_usb_ipv4: str
    expected_hotspot_ipv4: str
    usb_carrier: bool
    usb_ipv4_addresses: tuple[str, ...]
    camera_lease: DnsmasqLease | None
    wifi_interface: str
    wifi_ipv4_addresses: tuple[str, ...]
    wifi_ipv4_interfaces: tuple[IPv4Interface, ...] = ()
    ftp_activity: FtpActivity | None = None
    ftp_recent_window_s: float = DEFAULT_FTP_RECENT_WINDOW_S

    @property
    def usb_ipv4(self) -> str | None:
        """Return the primary USB IPv4 address, preferring the expected host address."""

        if self.expected_usb_ipv4 in self.usb_ipv4_addresses:
            return self.expected_usb_ipv4
        return self.usb_ipv4_addresses[0] if self.usb_ipv4_addresses else None

    @property
    def usb_configured(self) -> bool:
        """Return whether USB has the expected host IPv4 address configured."""

        return self.expected_usb_ipv4 in self.usb_ipv4_addresses

    @property
    def camera_lease_active(self) -> bool:
        """Return whether a discoverable camera DHCP lease is usable now."""

        return (
            self.wired_ftp_ready
            and self.camera_lease is not None
            and self.camera_lease.is_active(self.checked_at)
        )

    @property
    def wired_ftp_ready(self) -> bool:
        """Return whether the USB FTP path has carrier and expected host addressing."""

        return self.usb_carrier and self.usb_configured

    @property
    def wired_configured_no_carrier(self) -> bool:
        """Return whether USB has its host address but no physical link carrier."""

        return self.usb_configured and not self.usb_carrier

    @property
    def wired_carrier(self) -> bool:
        """Return whether the USB interface reports physical link carrier."""

        return self.usb_carrier

    @property
    def wireless_ftp_ready(self) -> bool:
        """Return whether any Wi-Fi FTP path has an IPv4 address."""

        return self.wifi_ipv4 is not None

    @property
    def wifi_ipv4(self) -> str | None:
        """Return the primary Wi-Fi IPv4 address, preferring the hotspot address."""

        if self.expected_hotspot_ipv4 in self.wifi_ipv4_addresses:
            return self.expected_hotspot_ipv4
        return self.home_wifi_ipv4

    @property
    def hotspot_ipv4(self) -> str | None:
        """Return the active bridge hotspot IPv4 address."""

        if self.expected_hotspot_ipv4 in self.wifi_ipv4_addresses:
            return self.expected_hotspot_ipv4
        return None

    @property
    def home_wifi_ipv4(self) -> str | None:
        """Return the active infrastructure/home Wi-Fi IPv4 address."""

        return self.home_wifi_ipv4_addresses[0] if self.home_wifi_ipv4_addresses else None

    @property
    def home_wifi_ipv4_addresses(self) -> tuple[str, ...]:
        """Return active peer Wi-Fi addresses that do not overlap reserved subnets."""

        return tuple(str(address.ip) for address in self.home_wifi_ipv4_interfaces)

    @property
    def home_wifi_ipv4_interfaces(self) -> tuple[IPv4Interface, ...]:
        """Return active peer Wi-Fi interfaces that do not overlap reserved subnets."""

        return tuple(
            address
            for address in self._wifi_ipv4_interfaces
            if _is_home_wifi_ipv4(
                address,
                usb_host=self.expected_usb_ipv4,
                hotspot_host=self.expected_hotspot_ipv4,
            )
        )

    @property
    def home_wifi_ipv4_networks(self) -> tuple[str, ...]:
        """Return active peer Wi-Fi networks that do not overlap reserved subnets."""

        networks: list[str] = []
        for address in self.home_wifi_ipv4_interfaces:
            network = str(address.network)
            if network not in networks:
                networks.append(network)
        return tuple(networks)

    @property
    def wifi_subnet_conflicts(self) -> tuple[WifiSubnetConflict, ...]:
        """Return Wi-Fi networks that overlap reserved USB or hotspot /24 subnets."""

        conflicts: list[WifiSubnetConflict] = []
        for address in self._wifi_ipv4_interfaces:
            conflicts.extend(
                _wifi_subnet_conflicts(
                    address,
                    usb_host=self.expected_usb_ipv4,
                    hotspot_host=self.expected_hotspot_ipv4,
                )
            )
        return tuple(conflicts)

    @property
    def wifi_subnet_conflict(self) -> bool:
        """Return whether Wi-Fi has an address on a reserved transport subnet."""

        return bool(self.wifi_subnet_conflicts)

    @property
    def hotspot_ftp_ready(self) -> bool:
        """Return whether the bridge hotspot FTP path is active."""

        return self.hotspot_ipv4 is not None

    @property
    def hotspot_active(self) -> bool:
        """Return whether the bridge hotspot path is active."""

        return self.hotspot_ftp_ready

    @property
    def home_wifi_ftp_ready(self) -> bool:
        """Return whether the home/infrastructure Wi-Fi FTP path is active."""

        return self.home_wifi_ipv4 is not None

    @property
    def peer_same_wifi_ready(self) -> bool:
        """Return whether peer FTP can receive from the active same-Wi-Fi network."""

        return self.home_wifi_ftp_ready

    @property
    def ftp_recently_active(self) -> bool:
        """Return whether FTP has seen recent connection or upload activity."""

        if self.ftp_activity is None:
            return False
        return self.ftp_activity.is_recent(self.checked_at, self.ftp_recent_window_s)

    def ftp_recently_active_for_mode(
        self,
        mode: FtpReceiveMode = FtpReceiveMode.AUTO,
    ) -> bool:
        """Return whether recent FTP activity came from a source allowed by mode."""

        return self.recent_ftp_source_for_mode(mode) is not None

    def recent_ftp_source_for_mode(
        self,
        mode: FtpReceiveMode = FtpReceiveMode.AUTO,
    ) -> FtpSourceKind | None:
        """Return the source kind for recent FTP activity accepted by mode."""

        if not self.ftp_recently_active or self.ftp_activity is None:
            return None
        remote_ip = self.ftp_activity.last_remote_ip
        if remote_ip is None:
            return None
        source = self._ftp_source_for_remote_ip(remote_ip)
        if source is None or not _ftp_source_allowed_by_mode(source, mode):
            return None
        return source

    def recent_ftp_source_ready_for_mode(
        self,
        mode: FtpReceiveMode = FtpReceiveMode.AUTO,
    ) -> bool:
        """Return whether recent FTP activity came from a currently ready mode source."""

        source = self.recent_ftp_source_for_mode(mode)
        return source is not None and self.ftp_source_ready(source)

    def ftp_source_ready(self, source: FtpSourceKind) -> bool:
        """Return whether the current network state can receive from a source."""

        if source is FtpSourceKind.USB:
            return self.wired_ftp_ready
        if source is FtpSourceKind.HOTSPOT:
            return self.hotspot_ftp_ready
        if source is FtpSourceKind.PEER:
            return self.home_wifi_ftp_ready
        return False

    @property
    def can_accept_ftp(self) -> bool:
        """Return whether any FTP receive path is addressable."""

        return self.can_accept_ftp_for_mode()

    @property
    def no_receive_path(self) -> bool:
        """Return whether no FTP receive path is currently addressable."""

        return not self.can_accept_ftp

    def can_accept_ftp_for_mode(
        self,
        mode: FtpReceiveMode = FtpReceiveMode.AUTO,
    ) -> bool:
        """Return whether the selected FTP receive mode has an addressable path."""

        if mode is FtpReceiveMode.WIRED:
            return False
        if mode is FtpReceiveMode.HOTSPOT:
            return self.hotspot_ftp_ready
        if mode is FtpReceiveMode.PEER:
            return self.home_wifi_ftp_ready
        return self.hotspot_ftp_ready or self.home_wifi_ftp_ready

    @property
    def _wifi_ipv4_interfaces(self) -> tuple[IPv4Interface, ...]:
        if self.wifi_ipv4_interfaces:
            return self.wifi_ipv4_interfaces
        return _coerce_ipv4_interfaces(self.wifi_ipv4_addresses)

    @property
    def _home_wifi_ipv4_network_objects(self) -> tuple[IPv4Network, ...]:
        networks: list[IPv4Network] = []
        for address in self.home_wifi_ipv4_interfaces:
            if address.network not in networks:
                networks.append(address.network)
        return tuple(networks)

    def _ftp_source_for_remote_ip(self, remote_ip: str) -> FtpSourceKind | None:
        source_ip = _usable_client_ipv4(remote_ip)
        if source_ip is None:
            return None
        try:
            usb_network = ipv4_24_network(self.expected_usb_ipv4)
            hotspot_network = ipv4_24_network(self.expected_hotspot_ipv4)
        except ValueError:
            return None
        if source_ip in usb_network:
            return FtpSourceKind.USB
        if source_ip in hotspot_network:
            return FtpSourceKind.HOTSPOT
        if _ipv4_in_any_network(source_ip, self._home_wifi_ipv4_network_objects):
            return FtpSourceKind.PEER
        return None


def build_connection_health(
    *,
    checked_at: float,
    expected_usb_ipv4: str,
    expected_hotspot_ipv4: str = "192.168.8.1",
    usb_carrier: bool,
    usb_ipv4_addresses: Iterable[str],
    wifi_ipv4_addresses: Iterable[str],
    leases: Iterable[DnsmasqLease] = (),
    usb_interface: str = DEFAULT_USB_INTERFACE,
    wifi_interface: str = DEFAULT_WIFI_INTERFACE,
    wifi_ipv4_interfaces: Iterable[str | IPv4Interface] | None = None,
    ftp_activity: FtpActivity | None = None,
    ftp_recent_window_s: float = DEFAULT_FTP_RECENT_WINDOW_S,
) -> ConnectionHealth:
    """Build a health snapshot from already-collected facts."""

    usb_addresses = tuple(usb_ipv4_addresses)
    wifi_addresses = tuple(wifi_ipv4_addresses)
    wifi_interfaces = (
        _coerce_ipv4_interfaces(wifi_ipv4_interfaces)
        if wifi_ipv4_interfaces is not None
        else _coerce_ipv4_interfaces(wifi_addresses)
    )
    if not wifi_addresses:
        wifi_addresses = tuple(str(address.ip) for address in wifi_interfaces)
    camera_lease = select_camera_lease(leases, expected_usb_ipv4, now=checked_at)
    return ConnectionHealth(
        checked_at=checked_at,
        usb_interface=usb_interface,
        expected_usb_ipv4=expected_usb_ipv4,
        expected_hotspot_ipv4=expected_hotspot_ipv4,
        usb_carrier=usb_carrier,
        usb_ipv4_addresses=usb_addresses,
        camera_lease=camera_lease,
        wifi_interface=wifi_interface,
        wifi_ipv4_addresses=wifi_addresses,
        wifi_ipv4_interfaces=wifi_interfaces,
        ftp_activity=ftp_activity,
        ftp_recent_window_s=ftp_recent_window_s,
    )


def probe_connection_health(
    *,
    expected_usb_ipv4: str,
    expected_hotspot_ipv4: str = "192.168.8.1",
    usb_interface: str = DEFAULT_USB_INTERFACE,
    wifi_interface: str = DEFAULT_WIFI_INTERFACE,
    dnsmasq_lease_paths: Iterable[Path] = DEFAULT_DNSMASQ_LEASE_PATHS,
    ftp_activity: FtpActivity | None = None,
    clock: Callable[[], float] = time.time,
) -> ConnectionHealth:
    """Collect a connection health snapshot using local non-root probes where possible."""

    checked_at = clock()
    leases = read_dnsmasq_leases(dnsmasq_lease_paths)
    wifi_ipv4_interfaces = detect_ipv4_interfaces_for_interface(wifi_interface)
    return build_connection_health(
        checked_at=checked_at,
        expected_usb_ipv4=expected_usb_ipv4,
        expected_hotspot_ipv4=expected_hotspot_ipv4,
        usb_carrier=detect_link_carrier(usb_interface),
        usb_ipv4_addresses=detect_ipv4_addresses_for_interface(usb_interface),
        wifi_ipv4_addresses=[str(address.ip) for address in wifi_ipv4_interfaces],
        wifi_ipv4_interfaces=wifi_ipv4_interfaces,
        leases=leases,
        usb_interface=usb_interface,
        wifi_interface=wifi_interface,
        ftp_activity=ftp_activity,
    )


def detect_camera_link_health(
    expected_usb_ipv4: str = "192.168.7.1",
    expected_hotspot_ipv4: str = "192.168.8.1",
    *,
    usb_interface: str = DEFAULT_USB_INTERFACE,
    wifi_interface: str = DEFAULT_WIFI_INTERFACE,
    dnsmasq_lease_paths: Iterable[Path] = DEFAULT_DNSMASQ_LEASE_PATHS,
    ftp_activity: FtpActivity | None = None,
    clock: Callable[[], float] = time.time,
) -> ConnectionHealth:
    """Compatibility wrapper for UI/main-thread camera link health checks."""

    return probe_connection_health(
        expected_usb_ipv4=expected_usb_ipv4,
        expected_hotspot_ipv4=expected_hotspot_ipv4,
        usb_interface=usb_interface,
        wifi_interface=wifi_interface,
        dnsmasq_lease_paths=dnsmasq_lease_paths,
        ftp_activity=ftp_activity,
        clock=clock,
    )


def read_dnsmasq_leases(paths: Iterable[Path] = DEFAULT_DNSMASQ_LEASE_PATHS) -> list[DnsmasqLease]:
    """Read and parse the first discoverable dnsmasq lease file."""

    for path in paths:
        try:
            return parse_dnsmasq_leases(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except OSError:
            LOGGER.debug("network.dnsmasq_lease_read_failed path=%s", path, exc_info=True)
    return []


def parse_dnsmasq_leases(text: str) -> list[DnsmasqLease]:
    """Parse dnsmasq lease-file text.

    dnsmasq lease rows use:
    ``expires_at mac_address ipv4 hostname client_id``
    """

    leases: list[DnsmasqLease] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 5:
            continue
        lease = _parse_dnsmasq_lease_fields(fields)
        if lease is not None:
            leases.append(lease)
    return leases


def select_camera_lease(
    leases: Iterable[DnsmasqLease],
    expected_usb_ipv4: str,
    *,
    now: float,
    prefix_len: int = 24,
) -> DnsmasqLease | None:
    """Return the best active lease on the USB camera subnet."""

    try:
        host_ip = ipaddress.IPv4Address(expected_usb_ipv4)
        network = ipaddress.IPv4Network(f"{expected_usb_ipv4}/{prefix_len}", strict=False)
    except ValueError:
        return None

    candidates: list[DnsmasqLease] = []
    for lease in leases:
        if not lease.is_active(now):
            continue
        try:
            lease_ip = ipaddress.IPv4Address(lease.ipv4)
        except ValueError:
            continue
        if lease_ip != host_ip and lease_ip in network:
            candidates.append(lease)
    return max(candidates, key=lambda lease: lease.expires_at) if candidates else None


def _parse_dnsmasq_lease_fields(fields: list[str]) -> DnsmasqLease | None:
    try:
        expires_at = int(fields[0])
        ipaddress.IPv4Address(fields[2])
    except ValueError:
        return None
    return DnsmasqLease(
        expires_at=expires_at,
        mac_address=fields[1].lower(),
        ipv4=fields[2],
        hostname=_optional_dnsmasq_field(fields[3]),
        client_id=_optional_dnsmasq_field(fields[4]),
    )


def _optional_dnsmasq_field(value: str) -> str | None:
    return None if value == "*" else value


def _is_home_wifi_ipv4(
    address: IPv4Interface,
    *,
    usb_host: str,
    hotspot_host: str,
) -> bool:
    ipv4 = str(address.ip)
    if ipv4 == hotspot_host:
        return False
    parsed = _usable_client_ipv4(ipv4)
    if parsed is None:
        return False
    return not _wifi_subnet_conflicts(address, usb_host=usb_host, hotspot_host=hotspot_host)


def _wifi_subnet_conflicts(
    address: IPv4Interface,
    *,
    usb_host: str,
    hotspot_host: str,
) -> tuple[WifiSubnetConflict, ...]:
    ipv4 = str(address.ip)
    parsed = _usable_client_ipv4(ipv4)
    if parsed is None or ipv4 == hotspot_host:
        return ()
    try:
        reserved_networks = (
            (FtpSourceKind.USB, ipv4_24_network(usb_host)),
            (FtpSourceKind.HOTSPOT, ipv4_24_network(hotspot_host)),
        )
    except ValueError:
        return ()

    return tuple(
        WifiSubnetConflict(
            ipv4=ipv4,
            reserved_source=source,
            reserved_network=str(reserved_network),
            wifi_network=str(address.network),
        )
        for source, reserved_network in reserved_networks
        if address.network.overlaps(reserved_network)
    )


def _coerce_ipv4_interfaces(
    addresses: Iterable[str | IPv4Interface] | None,
    *,
    default_prefix_len: int = 24,
) -> tuple[IPv4Interface, ...]:
    if addresses is None:
        return ()
    interfaces: list[IPv4Interface] = []
    for address in addresses:
        interface = _coerce_ipv4_interface(address, default_prefix_len=default_prefix_len)
        if interface is not None:
            interfaces.append(interface)
    return tuple(interfaces)


def _coerce_ipv4_interface(
    address: str | IPv4Interface,
    *,
    default_prefix_len: int = 24,
) -> IPv4Interface | None:
    if isinstance(address, IPv4Interface):
        return address
    text = str(address)
    if "/" not in text:
        text = f"{text}/{default_prefix_len}"
    try:
        return IPv4Interface(text)
    except ValueError:
        return None


def _ftp_source_allowed_by_mode(source: FtpSourceKind, mode: FtpReceiveMode) -> bool:
    if source is FtpSourceKind.USB:
        return False
    if mode is FtpReceiveMode.AUTO:
        return True
    if mode is FtpReceiveMode.WIRED:
        return False
    if mode is FtpReceiveMode.HOTSPOT:
        return source is FtpSourceKind.HOTSPOT
    if mode is FtpReceiveMode.PEER:
        return source is FtpSourceKind.PEER
    return False


def _ipv4_in_any_network(address: IPv4Address, networks: Iterable[IPv4Network]) -> bool:
    return any(address in network for network in networks)


def _usable_client_ipv4(address: str) -> IPv4Address | None:
    try:
        parsed = IPv4Address(address)
    except ValueError:
        return None
    if parsed.is_link_local or parsed.is_loopback or parsed.is_multicast or parsed.is_unspecified:
        return None
    return parsed
