"""Compare complete rtnetlink message/link/address parsing with packed IPv4 input.

Run with the Bridge development Python from any working directory. No real
network probes, sockets, subprocesses, or hardware are used. The baseline is
the current address parser with only its interface-construction line restored.
"""

from __future__ import annotations

import fcntl
import inspect
import json
import platform
import socket
import statistics
import struct
import sys
import time
from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bridge" / "src"))
from instantlink_bridge.net import linux_snapshot as native

AddressParser = Callable[
    [list[tuple[int, bytes]], dict[int, str], tuple[str, ...]],
    dict[str, list[IPv4Interface]],
]


def attribute(kind: int, value: bytes) -> bytes:
    raw = struct.pack("=HH", 4 + len(value), kind) + value
    return raw + b"\0" * (-len(raw) % 4)


def message(kind: int, body: bytes, sequence: int) -> bytes:
    raw = struct.pack("=IHHII", 16 + len(body), kind, 0, sequence, 77) + body
    return raw + b"\0" * (-len(raw) % 4)


def fixture(accepted_count: int) -> tuple[bytes, bytes]:
    links = b"".join(
        message(
            16,
            struct.pack("=BBHiII", 0, 0, 1, index, 1, 0) + attribute(3, name.encode() + b"\0"),
            2,
        )
        for index, name in ((1, "lo"), (5, "wlan0"), (6, "usb0"), (7, "eth0"))
    )
    addresses: list[bytes] = []
    for number in range(accepted_count):
        index = 6 if number == 0 else 5
        label = b"usb0\0" if index == 6 else b"wlan0:camera\0"
        # Include local/peer precedence and non-/24 prefixes in every fixture.
        raw = struct.pack("=BBBBI", socket.AF_INET, (24, 22, 32)[number % 3], 0, 0, index)
        raw += attribute(1, socket.inet_aton("10.200.0.1"))
        raw += attribute(2, bytes((192, 168, 7 + number % 2, 1 + number)))
        raw += attribute(3, label) + attribute(6, bytes(16))
        addresses.append(message(20, raw, 1))
    for index, scope, family, packed in (
        (1, 254, socket.AF_INET, socket.inet_aton("127.0.0.1")),
        (7, 0, socket.AF_INET, socket.inet_aton("10.0.0.1")),
        (5, 0, socket.AF_INET6, socket.inet_pton(socket.AF_INET6, "fe80::1")),
    ):
        raw = struct.pack("=BBBBI", family, 24, 0, scope, index) + attribute(2, packed)
        addresses.append(message(20, raw, 1))
    return links, b"".join(addresses)


def parse_snapshot(
    parser: AddressParser, link_bytes: bytes, address_bytes: bytes
) -> dict[str, list[IPv4Interface]]:
    names = ("wlan0", "usb0", "missing")
    links = [(kind, body) for kind, _flags, _seq, _port, body in native._messages(link_bytes)]
    addresses = [
        (kind, body) for kind, _flags, _seq, _port, body in native._messages(address_bytes)
    ]
    selected = native._parse_links(links, names, require_up=True)
    return parser(addresses, selected, names)


def measure(
    parser: AddressParser, inputs: tuple[bytes, bytes], iterations: int
) -> tuple[float, float]:
    start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    for _ in range(iterations):
        parse_snapshot(parser, *inputs)
    cpu_elapsed = time.process_time_ns() - cpu_start
    elapsed = time.perf_counter_ns() - start
    return elapsed / iterations / 1000, cpu_elapsed / iterations / 1000


def main() -> None:
    source = inspect.getsource(native._parse_addresses)
    optimized_line = "IPv4Interface((local, prefix))"
    assert source.count(optimized_line) == 1, "update baseline reconstruction for changed parser"
    baseline_source = source.replace(
        optimized_line, 'IPv4Interface(f"{IPv4Address(local)}/{prefix}")'
    )
    namespace = dict(vars(native), IPv4Address=IPv4Address)
    exec(compile(baseline_source, "<baseline-address-parser>", "exec"), namespace)
    baseline = cast(AddressParser, namespace["_parse_addresses"])
    variants = {"baseline": baseline, "packed": native._parse_addresses}
    workloads = [
        ("bridge_3_addresses", fixture(3), 2000),
        ("many_64_addresses", fixture(64), 500),
    ]
    for _name, inputs, _iterations in workloads:
        assert parse_snapshot(baseline, *inputs) == parse_snapshot(native._parse_addresses, *inputs)

    results: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "unit": "microseconds_per_complete_message_link_address_parse",
        "sample_pairs": 9,
        "excludes": "kernel/socket I/O; fixture generation; baseline reconstruction",
        "workloads": {},
    }
    with Path("/tmp/instantlink-099-benchmark.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name, inputs, iterations in workloads:
            for parser in variants.values():
                measure(parser, inputs, 200)
            samples: dict[str, list[float]] = {variant: [] for variant in variants}
            cpu_samples: dict[str, list[float]] = {variant: [] for variant in variants}
            for sample in range(9):
                order = tuple(variants) if sample % 2 == 0 else tuple(reversed(variants))
                for variant in order:
                    elapsed, cpu_elapsed = measure(variants[variant], inputs, iterations)
                    samples[variant].append(elapsed)
                    cpu_samples[variant].append(cpu_elapsed)
            medians = {variant: statistics.median(values) for variant, values in samples.items()}
            cpu_medians = {variant: statistics.median(v) for variant, v in cpu_samples.items()}
            workloads_result = cast(dict[str, object], results["workloads"])
            workloads_result[name] = {
                "iterations_per_sample": iterations,
                "samples_us": samples,
                "median_us": medians,
                "min_max_us": {variant: [min(v), max(v)] for variant, v in samples.items()},
                "median_reduction_percent": 100 * (1 - medians["packed"] / medians["baseline"]),
                "speedup": medians["baseline"] / medians["packed"],
                "cpu_samples_us": cpu_samples,
                "cpu_median_us": cpu_medians,
                "cpu_min_max_us": {variant: [min(v), max(v)] for variant, v in cpu_samples.items()},
                "cpu_median_reduction_percent": (
                    100 * (1 - cpu_medians["packed"] / cpu_medians["baseline"])
                ),
            }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
