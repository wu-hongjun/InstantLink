#!/usr/bin/env python3
"""Build and reversibly install one pinned AP management-IE fix on the audited Pi kernel.

No module reload, Bluetooth change, initramfs edit, or firmware change is performed.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KERNEL = "6.12.47+rpt-rpi-v8"
SOURCE_COMMIT = "359f37f0faefb712add32a39f98751aea67d5c1f"
UPSTREAM_COMMIT = "aba23b0a6a0df84b06ed0323ce127bf7257e4025"
ARCHIVE_SHA256 = {
    "85c882310e7c74657855b25bba700b5a856327a31547fe49f5758951984c92d9",
    "c8431ce04c144c307fedfccd8b5c26b9e69cb3f0d5071e56f82c933478da3b71",
}
PATCH_SHA256 = "36a55fd0afb9aab74e787843d8e2f5ad16d2f6d38fc16fede0aa50cc451c6970"
BASE_CFG_SHA256 = "b3eab58af69380e0ff93b1d0af9e73e3d1810811018a7f98eca3f5fe5f599546"
PATCHED_CFG_SHA256 = "fd2b571a27aadce13ec49bdea9e61548f2cc39da7a46665716c0907a52794ed3"
STOCK_SRCVERSION = "FBBF7D1EF3ACBA683834518"
PATCHED_SRCVERSION = "2254D80EF43499080344466"
PREFIX = f"linux-{SOURCE_COMMIT}"
SUBTREE = Path("drivers/net/wireless/broadcom/brcm80211")
MODULE_TREE = SUBTREE / "brcmfmac"
PATCH = Path(__file__).resolve().parents[1] / "patches/brcmfmac-ap-management-ie-aba23b0a.patch"
HEADERS = Path(f"/lib/modules/{KERNEL}/build")
STOCK_DIR = Path(f"/lib/modules/{KERNEL}/kernel") / MODULE_TREE
OVERRIDE = Path(f"/lib/modules/{KERNEL}/updates/instantlink/brcmfmac.ko")
STATE_ROOT = Path("/var/lib/InstantLinkBridgeKernelBackports")
STATE = STATE_ROOT / KERNEL
BOOT = Path("/boot/firmware")
KERNEL_INITRD = Path(f"/boot/initrd.img-{KERNEL}")
SIG_ENFORCE = Path("/sys/module/module/parameters/sig_enforce")
LOCKDOWN = Path("/sys/kernel/security/lockdown")
_LOCK_FD: int | None = None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def command(args: list[str], *, cwd: Path | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        args,
        check=True,
        cwd=cwd,
        text=True,
        capture_output=capture,
        timeout=1800,
        env={**os.environ, "LC_ALL": "C"},
    )
    return result.stdout.strip() if capture else ""


def platform_gate(*, headers: bool = True) -> None:
    require(os.uname().release == KERNEL, f"This backport requires running kernel {KERNEL}")
    require(os.uname().machine == "aarch64", "This backport requires native aarch64")
    if not headers:
        return
    require(HEADERS.is_dir(), "Install the exact running-kernel headers first")
    require(
        command(["make", "-s", "-C", str(HEADERS), "kernelrelease"]) == KERNEL,
        "Kernel headers do not match the running kernel",
    )
    require((HEADERS / "Module.symvers").is_file(), "Headers must include Module.symvers")
    require(
        "CONFIG_MODULE_SIG_FORCE=y" not in (HEADERS / ".config").read_text(),
        "Unsigned overrides are unsupported when module signatures are enforced",
    )
    unsigned_module_gate()


def unsigned_module_gate() -> None:
    if SIG_ENFORCE.exists():
        require(
            SIG_ENFORCE.read_text().strip() in {"N", "0"},
            "Runtime module signature enforcement rejects unsigned overrides",
        )
    if LOCKDOWN.exists():
        require("[none]" in LOCKDOWN.read_text(), "Kernel lockdown rejects unsigned overrides")


def stock_module() -> Path:
    candidates = [path for path in STOCK_DIR.glob("brcmfmac.ko*") if path.is_file()]
    require(len(candidates) == 1, "Expected exactly one packaged stock brcmfmac module")
    return candidates[0]


def module_info(path: Path) -> dict[str, str]:
    return {
        field: command(["/sbin/modinfo", "-F", field, str(path)])
        for field in ("name", "vermagic", "srcversion", "depends", "license")
    }


def imports(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in command(["/sbin/modprobe", "--show-modversions", str(path)]).splitlines():
        crc, name = line.split()
        require(name not in result, "Duplicate imported module symbol")
        result[name] = int(crc, 16)
    require(bool(result), "Expected symbol version information")
    return result


def symbols(path: Path, *, module: str | None = None) -> dict[str, tuple[int, str, str]]:
    result: dict[str, tuple[int, str, str]] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        require(len(parts) in (4, 5), "Malformed Module.symvers record")
        crc, name, owner, export = parts[:4]
        if module is not None and Path(owner).name != module:
            continue
        require(name not in result, "Ambiguous symbol record")
        result[name] = (int(crc, 16), export, parts[4] if len(parts) == 5 else "")
    require(bool(result), "Expected matching symbol records")
    return result


def abi_gate(candidate: Path, stock: Path, exported: Path) -> dict[str, Any]:
    info, original = module_info(candidate), module_info(stock)
    require(info["name"] == original["name"] == "brcmfmac", "Unexpected module identity")
    for field in ("vermagic", "depends", "license"):
        require(info[field] == original[field], f"Module {field} differs from stock")
    require(info["vermagic"].split()[0] == KERNEL, "Module kernel release differs")
    header = candidate.read_bytes()[:20]
    require(
        header[:6] == b"\x7fELF\x02\x01" and int.from_bytes(header[18:20], "little") == 183,
        "Candidate must be an ELF64 little-endian AArch64 module",
    )
    candidate_imports, stock_imports = imports(candidate), imports(stock)
    require(candidate_imports == stock_imports, "Imported symbol CRCs differ from stock")
    all_headers = symbols(HEADERS / "Module.symvers")
    require(
        all(all_headers.get(name, (None,))[0] == crc for name, crc in candidate_imports.items()),
        "Imported CRC differs from headers",
    )
    expected_exports = symbols(HEADERS / "Module.symvers", module="brcmfmac")
    require(
        symbols(exported, module="brcmfmac") == expected_exports,
        "Exported symbol CRC/type/namespace differs; stock vendor plugins must remain compatible",
    )
    return {
        "candidate": info,
        "stock": original,
        "imported_symbols": len(candidate_imports),
        "exported_symbols": len(expected_exports),
    }


def archive_members(archive: Path) -> tuple[str, dict[Path, bytes]]:
    # Copy onto SD-backed private storage before hashing and parsing. Never
    # reopen a shared input path between verification and extraction.
    with tempfile.TemporaryFile(dir="/var/tmp") as snapshot:
        with archive.open("rb") as original:
            shutil.copyfileobj(original, snapshot)
        snapshot.seek(0)
        digest = hashlib.file_digest(snapshot, "sha256").hexdigest()
        require(digest in ARCHIVE_SHA256, "Source archive digest does not match the pinned source")
        snapshot.seek(0)
        with tarfile.open(fileobj=snapshot, mode="r:gz") as source:
            return _archive_entries(source, digest)


def _archive_entries(source: tarfile.TarFile, digest: str) -> tuple[str, dict[Path, bytes]]:
    selected: dict[Path, bytes] = {}
    for member in source:
        parts = Path(member.name).parts
        if not parts or parts[0] != PREFIX:
            continue
        relative = Path(*parts[1:])
        if relative not in (Path("COPYING"), Path("Makefile")) and not relative.is_relative_to(
            SUBTREE
        ):
            continue
        require(".." not in relative.parts and not relative.is_absolute(), "Unsafe source path")
        if member.isdir():
            continue
        require(member.isfile() and relative not in selected, "Unsafe or duplicated source entry")
        data = source.extractfile(member)
        require(data is not None, "Missing source entry")
        selected[relative] = data.read()
    require(MODULE_TREE / "cfg80211.c" in selected, "Archive lacks the pinned driver")
    return digest, selected


def verify_source(archive: Path, source: Path, *, patched: bool) -> str:
    digest, entries = archive_members(archive)
    for relative, original in entries.items():
        actual = source / relative
        expected = (
            (PATCHED_CFG_SHA256 if patched else BASE_CFG_SHA256)
            if relative == MODULE_TREE / "cfg80211.c"
            else hashlib.sha256(original).hexdigest()
        )
        require(
            actual.is_file() and not actual.is_symlink() and sha256(actual) == expected,
            f"Source differs from the pinned tree: {relative}",
        )
    return digest


def attest(archive: Path, source: Path, baseline: Path, candidate: Path, output: Path) -> None:
    platform_gate()
    require(sha256(PATCH) == PATCH_SHA256, "Upstream patch digest differs")
    archive_digest = verify_source(archive, source, patched=True)
    stock = stock_module()
    original_info = module_info(stock)
    baseline_info = module_info(baseline)
    require(
        baseline_info == original_info and original_info["srcversion"] == STOCK_SRCVERSION,
        "Unchanged build does not match the exact installed source/configuration",
    )
    exported = source / MODULE_TREE / "Module.symvers"
    abi = abi_gate(candidate, stock, exported)
    require(
        abi["candidate"]["srcversion"] == PATCHED_SRCVERSION,
        "Candidate does not match the exact patched source/configuration",
    )
    output.mkdir(mode=0o755, parents=False, exist_ok=False)
    shutil.copyfile(candidate, output / "brcmfmac.ko")
    shutil.copyfile(exported, output / "Module.symvers")
    manifest = {
        "schema_version": 1,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "kernel": KERNEL,
        "source_commit": SOURCE_COMMIT,
        "source_archive_sha256": archive_digest,
        "upstream_commit": UPSTREAM_COMMIT,
        "patch_sha256": PATCH_SHA256,
        "stock_path": str(stock.resolve()),
        "stock_sha256": sha256(stock),
        "baseline_sha256": sha256(baseline),
        "module_sha256": sha256(output / "brcmfmac.ko"),
        "exports_sha256": sha256(output / "Module.symvers"),
        "headers_config_sha256": sha256(HEADERS / ".config"),
        "headers_symvers_sha256": sha256(HEADERS / "Module.symvers"),
        "compiler": command(["gcc-14", "--version"]).splitlines()[0],
        "abi": abi,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Verified artifact: {output}")


def build(archive: Path, work: Path) -> None:
    platform_gate()
    require(command(["gcc-14", "-dumpfullversion"]).split(".")[0] == "14", "GCC 14 is required")
    require(sha256(PATCH) == PATCH_SHA256, "Upstream patch digest differs")
    _, entries = archive_members(archive)
    work.mkdir(mode=0o700, parents=False, exist_ok=False)
    source = work / PREFIX
    for relative, data in entries.items():
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    verify_source(archive, source, patched=False)
    flags = "-DDEBUG" if "CONFIG_BRCMDBG=y" in (HEADERS / ".config").read_text() else ""
    args = [
        "make",
        "-C",
        str(HEADERS),
        f"M={source / MODULE_TREE}",
        "CC=gcc-14",
        f"KCFLAGS={flags}",
        "-j2",
        "modules",
    ]
    command(args, capture=False)
    baseline = work / "baseline"
    baseline.mkdir()
    shutil.copyfile(source / MODULE_TREE / "brcmfmac.ko", baseline / "brcmfmac.ko")
    require(
        module_info(baseline / "brcmfmac.ko") == module_info(stock_module()),
        "Unpatched build differs from packaged stock; refusing to patch",
    )
    command(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)], cwd=source, capture=False)
    command(args, capture=False)
    attest(
        archive,
        source,
        baseline / "brcmfmac.ko",
        source / MODULE_TREE / "brcmfmac.ko",
        work / "artifacts",
    )


def root_directory(path: Path, mode: int) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == mode,
            f"Untrusted installation directory: {path}",
        )
    else:
        path.mkdir(mode=mode)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manifest-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def root_gate(*, headers: bool = True) -> None:
    global _LOCK_FD
    require(os.geteuid() == 0, "Installation and rollback require root")
    platform_gate(headers=headers)
    root_directory(STATE_ROOT, 0o700)
    root_directory(STATE, 0o700)
    _LOCK_FD = os.open(STATE / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(_LOCK_FD)
    require(
        stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600,
        "Untrusted maintenance lock",
    )
    fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)


def resolved_module() -> Path:
    return Path(command(["/sbin/modinfo", "-k", KERNEL, "-F", "filename", "brcmfmac"])).resolve()


def artifact_gate(directory: Path) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text())
    require(
        manifest["kernel"] == KERNEL
        and manifest["source_commit"] == SOURCE_COMMIT
        and manifest["upstream_commit"] == UPSTREAM_COMMIT
        and manifest["patch_sha256"] == PATCH_SHA256
        and manifest["source_archive_sha256"] in ARCHIVE_SHA256,
        "Artifact provenance differs",
    )
    for name, field in (("brcmfmac.ko", "module_sha256"), ("Module.symvers", "exports_sha256")):
        require(sha256(directory / name) == manifest[field], f"Artifact digest differs: {name}")
    require(sha256(stock_module()) == manifest["stock_sha256"], "Packaged stock module changed")
    require(
        sha256(HEADERS / ".config") == manifest["headers_config_sha256"]
        and sha256(HEADERS / "Module.symvers") == manifest["headers_symvers_sha256"],
        "Build headers changed",
    )
    require(
        abi_gate(directory / "brcmfmac.ko", stock_module(), directory / "Module.symvers")
        == manifest["abi"],
        "Artifact ABI evidence differs",
    )
    require(
        module_info(directory / "brcmfmac.ko")["srcversion"] == PATCHED_SRCVERSION,
        "Candidate source identity differs",
    )
    return manifest


def initramfs_gate() -> None:
    boot = BOOT
    pending, visited = [boot / "config.txt"], set()
    while pending:
        config = pending.pop()
        require(config.is_file() and not config.is_symlink(), "Unknown boot configuration layout")
        require(config not in visited, "Cyclic boot configuration include")
        visited.add(config)
        for raw in config.read_text().splitlines():
            fields = raw.split("#", 1)[0].split()
            if not fields:
                continue
            if fields[0] == "include":
                require(len(fields) == 2, "Unsupported boot configuration include")
                included = boot / fields[1]
                require(
                    included.resolve().is_relative_to(boot.resolve()), "Unsafe boot include path"
                )
                pending.append(included)
            elif fields[0] == "initramfs":
                require(
                    len(fields) >= 2 and fields[1] == "initramfs8",
                    "Custom initramfs needs explicit maintenance; audited default only",
                )
            elif "=" in raw:
                key, _, value = raw.split("#", 1)[0].partition("=")
                key, value = key.strip(), value.strip()
                if key == "kernel":
                    require(value == "kernel8.img", "Custom kernel image layout is unsupported")
                elif key in {"os_prefix", "ramfsfile"}:
                    require(not value, "Custom OS prefix or legacy initramfs layout is unsupported")
    for image in (KERNEL_INITRD, boot / "initramfs8"):
        if image.is_file():
            files = command(["lsinitramfs", str(image)]).splitlines()
            require(
                not any(Path(name).name.startswith("brcmfmac.ko") for name in files),
                "Initramfs contains brcmfmac; explicit initramfs maintenance is required first",
            )


def install(directory: Path) -> None:
    root_gate()
    require(
        not OVERRIDE.exists() and not OVERRIDE.is_symlink(),
        "Existing override must be preserved; roll back first",
    )
    require(
        resolved_module() == stock_module().resolve(), "Another module override is already selected"
    )
    # Do not silently leave an old initramfs module selected at the next boot.
    initramfs_gate()
    with tempfile.TemporaryDirectory(prefix="stage-", dir=STATE) as temporary:
        staged = Path(temporary)
        for name in ("manifest.json", "brcmfmac.ko", "Module.symvers"):
            shutil.copyfile(directory / name, staged / name)
        manifest = artifact_gate(staged)
        backup = STATE / f"stock-{stock_module().name}"
        require(not backup.is_symlink(), "Untrusted stock backup")
        if backup.exists():
            require(sha256(backup) == manifest["stock_sha256"], "Existing stock backup differs")
        else:
            shutil.copyfile(stock_module(), backup)
            backup.chmod(0o600)
        root_directory(OVERRIDE.parent.parent, 0o755)
        root_directory(OVERRIDE.parent, 0o755)
        manifest["override_path"] = str(OVERRIDE)
        manifest["state"] = "installed"
        atomic_json(STATE / "manifest.json", manifest)
        fd, pending = tempfile.mkstemp(prefix=".brcmfmac-", suffix=".pending", dir=OVERRIDE.parent)
        os.close(fd)
        temporary_module = Path(pending)
        try:
            shutil.copyfile(staged / "brcmfmac.ko", temporary_module)
            temporary_module.chmod(0o644)
            require(
                sha256(temporary_module) == manifest["module_sha256"],
                "Staged install digest differs",
            )
            os.replace(temporary_module, OVERRIDE)
            command(["/sbin/depmod", "-a", KERNEL])
            require(resolved_module() == OVERRIDE.resolve(), "depmod did not select the override")
        except BaseException:
            OVERRIDE.unlink(missing_ok=True)
            command(["/sbin/depmod", "-a", KERNEL])
            require(
                resolved_module() == stock_module().resolve(),
                "Failed installation could not restore stock selection",
            )
            manifest["state"] = "rolled_back"
            atomic_json(STATE / "manifest.json", manifest)
            raise
        finally:
            temporary_module.unlink(missing_ok=True)
    print(
        "Override installed; running driver unchanged. Reload Wi-Fi during the validation window."
    )


def rollback() -> None:
    root_gate(headers=False)
    manifest = json.loads((STATE / "manifest.json").read_text())
    require(manifest["override_path"] == str(OVERRIDE), "Recorded override path differs")
    require(sha256(stock_module()) == manifest["stock_sha256"], "Packaged stock module changed")
    if OVERRIDE.exists() or OVERRIDE.is_symlink():
        require(
            OVERRIDE.is_file()
            and not OVERRIDE.is_symlink()
            and sha256(OVERRIDE) == manifest["module_sha256"],
            "Refusing to delete an unowned override",
        )
        OVERRIDE.unlink()
    command(["/sbin/depmod", "-a", KERNEL])
    require(
        resolved_module() == stock_module().resolve(), "Rollback did not restore stock selection"
    )
    manifest["state"] = "rolled_back"
    atomic_json(STATE / "manifest.json", manifest)
    print("Stock module selection restored; reload Wi-Fi explicitly to restore the running driver.")


def verify_installed() -> None:
    root_gate(headers=False)
    manifest = json.loads((STATE / "manifest.json").read_text())
    installed = manifest["state"] == "installed"
    expected_path = OVERRIDE.resolve() if installed else stock_module().resolve()
    expected_version = manifest["abi"]["candidate" if installed else "stock"]["srcversion"]
    require(resolved_module() == expected_path, "Selected module differs from recorded state")
    require(sha256(stock_module()) == manifest["stock_sha256"], "Packaged stock module changed")
    if installed:
        require(
            not OVERRIDE.is_symlink() and sha256(OVERRIDE) == manifest["module_sha256"],
            "Installed override digest differs",
        )
    require(
        Path("/sys/module/brcmfmac/srcversion").read_text().strip() == expected_version,
        "Running Wi-Fi module differs; explicitly reload or reboot first",
    )
    print(
        json.dumps(
            {
                "state": manifest["state"],
                "selected_path": str(expected_path),
                "running_srcversion": expected_version,
                "stock_preserved": True,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    create = modes.add_parser("build")
    create.add_argument("archive", type=Path)
    create.add_argument("work", type=Path)
    verify = modes.add_parser(
        "attest", help="Verify/package a separately compiled baseline and candidate"
    )
    for name in ("archive", "source", "baseline", "candidate", "output"):
        verify.add_argument(name, type=Path)
    add = modes.add_parser("install")
    add.add_argument("artifact", type=Path)
    modes.add_parser("rollback")
    modes.add_parser(
        "verify", help="Verify selected and running module after explicit reload/reboot"
    )
    args = parser.parse_args()
    if args.mode == "build":
        build(args.archive.resolve(), args.work.absolute())
    elif args.mode == "attest":
        attest(
            args.archive.resolve(),
            args.source.resolve(),
            args.baseline.resolve(),
            args.candidate.resolve(),
            args.output.absolute(),
        )
    elif args.mode == "install":
        install(args.artifact.resolve())
    elif args.mode == "rollback":
        rollback()
    else:
        verify_installed()


if __name__ == "__main__":
    main()
