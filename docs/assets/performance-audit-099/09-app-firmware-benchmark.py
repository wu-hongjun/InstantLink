#!/usr/bin/env python3
"""Compare the original whole-file hash with the current App package validator on macOS.

Run from any directory: python3 path/to/09-app-firmware-benchmark.py > results.json
Requires the macOS Swift toolchain. All fixtures and binaries are temporary. Compilation,
fixture generation and measurements share the audit flock; only package validation is timed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import platform
import re
import statistics
import subprocess
import tempfile
from pathlib import Path

BASELINE_HASH = """    private static func sha256Hex(_ url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
"""

BENCHMARK_MAIN = """import Foundation

@main
struct FirmwareBenchmark {
    static func main() throws {
        let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let start = ProcessInfo.processInfo.systemUptime
        guard let package = BridgeFirmwareBundleService.package(in: directory) else {
            fatalError("Fixture validation failed")
        }
        let elapsed = ProcessInfo.processInfo.systemUptime - start
        let result: [String: Any] = [
            "seconds": elapsed,
            "archive_sha256": package.archiveSHA256,
            "manifest_sha256": package.manifestSHA256,
            "checksum_sha256": package.checksumSHA256,
        ]
        print(String(data: try JSONSerialization.data(withJSONObject: result), encoding: .utf8)!)
    }
}
"""


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def make_fixture(directory: Path, size_mib: int) -> dict[str, str]:
    directory.mkdir()
    block = bytes(range(256)) * 4096
    archive_hash = hashlib.sha256()
    with (directory / "firmware.tar.gz").open("wb") as archive:
        for _ in range(size_mib):
            archive.write(block)
            archive_hash.update(block)
    manifest = b'{"schema_version":1}\n'
    checksum = archive_hash.hexdigest().encode() + b"  firmware.tar.gz\n"
    (directory / "firmware.manifest.json").write_bytes(manifest)
    (directory / "firmware.tar.gz.sha256").write_bytes(checksum)
    # This App service checks signature presence. Cryptographic signature verification
    # belongs to the Bridge; this benchmark preserves the service's existing behavior.
    (directory / "firmware.manifest.sig").write_bytes(b"fixture-signature")
    (directory / "latest.json.sig").write_bytes(b"fixture-signature")
    digests = {
        "archive_sha256": archive_hash.hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "checksum_sha256": hashlib.sha256(checksum).hexdigest(),
    }
    metadata = {
        "schema_version": 1,
        "package_kind": "instantlink_bridge_firmware",
        "bridge_version": "0.1.0",
        "target": "linux-aarch64",
        "archive_name": "firmware.tar.gz",
        "manifest_name": "firmware.manifest.json",
        "checksum_name": "firmware.tar.gz.sha256",
        **digests,
    }
    (directory / "latest.json").write_text(json.dumps(metadata))
    return digests


def sample(binary: Path, fixture: Path, digests: dict[str, str]) -> dict[str, float | int]:
    process = subprocess.run(
        ["/usr/bin/time", "-l", str(binary), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(process.stdout)
    assert all(result[key] == value for key, value in digests.items()), result
    rss = re.search(r"(\d+)\s+maximum resident set size", process.stderr)
    assert rss, process.stderr
    return {"seconds": result["seconds"], "peak_rss_bytes": int(rss.group(1))}


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    source_path = root / "macos/InstantLink/Core/BridgeFirmwareBundle.swift"
    current = source_path.read_text()
    marker = "    private static func sha256Hex(_ url: URL) -> String? {"
    assert current.count(marker) == 1
    start = current.index(marker)
    # sha256Hex is the final method. Only that method changes in the baseline binary.
    assert current[start:].rstrip().endswith("}\n}")
    baseline = current[:start] + BASELINE_HASH + "}\n"
    report: dict[str, object] = {
        "host": output(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "os": output(["sw_vers"]),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "swift": output(["swiftc", "--version"]),
        "production_source_sha256": hashlib.sha256(current.encode()).hexdigest(),
        "baseline_source_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "compiler_flags": ["-O", "-target", "arm64-apple-macosx15.0"],
        "chunk_bytes": 1024 * 1024,
        "trials_per_variant_per_size": 5,
        "method": (
            "Fresh child per sample; one discarded warmup per variant/size; alternating order"
        ),
        "cache": "Warm filesystem cache; fixture creation and warmups precede samples",
        "rss": "Darwin /usr/bin/time -l maximum resident set size, bytes, whole child process",
    }
    cases = []
    with (
        Path("/tmp/instantlink-099-benchmark.lock").open("a") as lock,
        tempfile.TemporaryDirectory(prefix="instantlink-firmware-benchmark-") as temp,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX)
        work = Path(temp)
        main_path = work / "Benchmark.swift"
        main_path.write_text(BENCHMARK_MAIN)
        binaries = {}
        for variant, source in [("baseline", baseline), ("streamed", current)]:
            swift_path = work / f"{variant}.swift"
            swift_path.write_text(source)
            binary = work / variant
            subprocess.run(
                [
                    "swiftc",
                    "-O",
                    "-target",
                    "arm64-apple-macosx15.0",
                    str(swift_path),
                    str(main_path),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            binaries[variant] = binary
        for size in [16, 64, 256]:
            fixture = work / f"fixture-{size}"
            digests = make_fixture(fixture, size)
            for binary in binaries.values():
                sample(binary, fixture, digests)
            samples: dict[str, list[dict[str, float | int]]] = {name: [] for name in binaries}
            order = []
            for trial in range(5):
                variants = ["baseline", "streamed"] if trial % 2 == 0 else ["streamed", "baseline"]
                order.append(variants)
                for variant in variants:
                    samples[variant].append(sample(binaries[variant], fixture, digests))
            summary = {}
            for variant, measurements in samples.items():
                seconds = [item["seconds"] for item in measurements]
                rss = [item["peak_rss_bytes"] for item in measurements]
                summary[variant] = {
                    "median_seconds": statistics.median(seconds),
                    "seconds_range": [min(seconds), max(seconds)],
                    "median_peak_rss_bytes": statistics.median(rss),
                    "peak_rss_bytes_range": [min(rss), max(rss)],
                }
            cases.append(
                {
                    "archive_mib": size,
                    "digests": digests,
                    "order": order,
                    "samples": samples,
                    "summary": summary,
                }
            )
    report["cases"] = cases
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
