from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/brcmfmac-ap-ie-backport.py"


@pytest.fixture
def backport() -> ModuleType:
    spec = importlib.util.spec_from_file_location("brcmfmac_backport_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_patch_and_provenance_match_pins(backport: ModuleType) -> None:
    provenance = json.loads(
        (backport.PATCH.parent / "brcmfmac-ap-management-ie-provenance.json").read_text()
    )
    assert backport.sha256(backport.PATCH) == backport.PATCH_SHA256
    assert provenance["upstream_patch_sha256"] == backport.PATCH_SHA256
    assert provenance["patched_cfg80211_sha256"] == backport.PATCHED_CFG_SHA256
    assert provenance["patched_srcversion"] == backport.PATCHED_SRCVERSION
    assert provenance["source_archive_sha256"] in backport.ARCHIVE_SHA256
    assert provenance["audited_subtree_archive_sha256"] in backport.ARCHIVE_SHA256


@pytest.mark.parametrize("bad", ["symlink", "traversal", "duplicate"])
def test_source_archive_entries_reject_unsafe_paths(
    backport: ModuleType, tmp_path: Path, bad: str
) -> None:
    archive = tmp_path / "source.tar"
    cfg = f"{backport.PREFIX}/{backport.MODULE_TREE}/cfg80211.c"
    with tarfile.open(archive, "w") as target:
        entry = tarfile.TarInfo(cfg)
        entry.size = 4
        target.addfile(entry, io.BytesIO(b"code"))
        other = tarfile.TarInfo(
            cfg
            if bad == "duplicate"
            else f"{backport.PREFIX}/{backport.MODULE_TREE}/../evil"
            if bad == "traversal"
            else f"{backport.PREFIX}/{backport.MODULE_TREE}/evil"
        )
        if bad == "symlink":
            other.type = tarfile.SYMTYPE
            other.linkname = "/etc/passwd"
        target.addfile(other)
    with tarfile.open(archive) as source, pytest.raises(RuntimeError, match="Unsafe"):
        backport._archive_entries(source, "test")


def test_unknown_archive_digest_fails_before_extraction(
    backport: ModuleType, tmp_path: Path
) -> None:
    archive = tmp_path / "untrusted.tar.gz"
    archive.write_bytes(b"untrusted")
    with pytest.raises(RuntimeError, match="digest"):
        backport.archive_members(archive)
    assert list(tmp_path.iterdir()) == [archive]


@pytest.mark.parametrize("drift", ["other_file", "cfg", "symlink"])
def test_attestation_source_allows_only_exact_patched_cfg(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: str
) -> None:
    cfg = backport.MODULE_TREE / "cfg80211.c"
    other = backport.MODULE_TREE / "p2p.c"
    entries = {cfg: b"stock", other: b"unchanged"}
    for path, content in entries.items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (tmp_path / cfg).write_bytes(b"patched")
    monkeypatch.setattr(backport, "archive_members", lambda _: ("digest", entries))
    monkeypatch.setattr(backport, "PATCHED_CFG_SHA256", backport.sha256(tmp_path / cfg))
    assert backport.verify_source(tmp_path / "archive", tmp_path, patched=True) == "digest"
    if drift == "symlink":
        (tmp_path / other).unlink()
        (tmp_path / other).symlink_to(tmp_path / cfg)
    else:
        (tmp_path / (cfg if drift == "cfg" else other)).write_bytes(b"wrong")
    with pytest.raises(RuntimeError, match="pinned tree"):
        backport.verify_source(tmp_path / "archive", tmp_path, patched=True)


@pytest.fixture
def abi_fixture(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, Any]:
    candidate, stock = tmp_path / "candidate.ko", tmp_path / "stock.ko"
    elf = bytearray(20)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (183).to_bytes(2, "little")
    candidate.write_bytes(elf)
    stock.write_bytes(b"stock")
    headers = tmp_path / "headers"
    headers.mkdir()
    (headers / "Module.symvers").write_text(
        "0x12345678 imported vmlinux EXPORT_SYMBOL\n"
        "0x11112222 public driver/brcmfmac EXPORT_SYMBOL_GPL NAMESPACE\n"
    )
    exports = tmp_path / "Module.symvers"
    exports.write_text("0x11112222 public absolute/build/brcmfmac EXPORT_SYMBOL_GPL NAMESPACE\n")
    metadata = {
        "name": "brcmfmac",
        "vermagic": backport.KERNEL + " SMP preempt mod_unload modversions aarch64",
        "depends": "brcmutil,cfg80211",
        "license": "Dual BSD/GPL",
        "srcversion": "candidate",
    }
    original = {**metadata, "srcversion": "stock"}
    imported = {"imported": 0x12345678}
    monkeypatch.setattr(backport, "HEADERS", headers)
    monkeypatch.setattr(
        backport, "module_info", lambda path: metadata if path == candidate else original
    )
    monkeypatch.setattr(
        backport,
        "imports",
        lambda path: imported if path == candidate else {"imported": 0x12345678},
    )
    return {
        "candidate": candidate,
        "stock": stock,
        "exports": exports,
        "metadata": metadata,
        "imported": imported,
    }


@pytest.mark.parametrize(
    "drift", ["vermagic", "depends", "license", "name", "imports", "exports", "elf"]
)
def test_abi_gate_rejects_incompatible_module(
    backport: ModuleType, abi_fixture: dict[str, Any], drift: str
) -> None:
    f = abi_fixture
    assert backport.abi_gate(f["candidate"], f["stock"], f["exports"])["exported_symbols"] == 1
    if drift == "imports":
        f["imported"]["imported"] = 0
    elif drift == "exports":
        f["exports"].write_text("0x11112222 public driver/brcmfmac EXPORT_SYMBOL_GPL WRONG\n")
    elif drift == "elf":
        f["candidate"].write_bytes(b"not an ELF module")
    else:
        f["metadata"][drift] = "different"
    with pytest.raises(RuntimeError):
        backport.abi_gate(f["candidate"], f["stock"], f["exports"])


def test_installer_preserves_existing_override(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "brcmfmac.ko"
    override.write_bytes(b"another operator")
    monkeypatch.setattr(backport, "root_gate", lambda **_: None)
    monkeypatch.setattr(backport, "OVERRIDE", override)
    with pytest.raises(RuntimeError, match="Existing override"):
        backport.install(tmp_path / "artifact")
    assert override.read_bytes() == b"another operator"


def test_installer_does_not_follow_dangling_stock_backup(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stock = tmp_path / "stock.ko"
    stock.write_bytes(b"stock")
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    for filename in ("manifest.json", "Module.symvers", "brcmfmac.ko"):
        (artifact / filename).write_bytes(b"artifact")
    state = tmp_path / "state"
    state.mkdir()
    outside = tmp_path / "outside"
    (state / "stock-stock.ko").symlink_to(outside)
    monkeypatch.setattr(backport, "STATE", state)
    monkeypatch.setattr(backport, "OVERRIDE", tmp_path / "absent.ko")
    monkeypatch.setattr(backport, "root_gate", lambda **_: None)
    monkeypatch.setattr(backport, "stock_module", lambda: stock)
    monkeypatch.setattr(backport, "resolved_module", lambda: stock)
    monkeypatch.setattr(backport, "initramfs_gate", lambda: None)
    monkeypatch.setattr(
        backport, "artifact_gate", lambda _: {"stock_sha256": backport.sha256(stock)}
    )
    with pytest.raises(RuntimeError, match="Untrusted stock backup"):
        backport.install(artifact)
    assert not outside.exists()
    assert stock.read_bytes() == b"stock"


@pytest.mark.parametrize(
    ("signature", "lockdown", "accepted"),
    [
        (None, None, True),
        ("N", "[none] integrity confidentiality", True),
        ("1", "[none] integrity confidentiality", False),
        ("Y", None, False),
        ("N", "none [integrity] confidentiality", False),
        ("N", "none integrity [confidentiality]", False),
    ],
)
def test_runtime_unsigned_module_enforcement_gate(
    backport: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    signature: str | None,
    lockdown: str | None,
    accepted: bool,
) -> None:
    sig = tmp_path / "sig_enforce"
    lock = tmp_path / "lockdown"
    if signature is not None:
        sig.write_text(signature)
    if lockdown is not None:
        lock.write_text(lockdown)
    monkeypatch.setattr(backport, "SIG_ENFORCE", sig)
    monkeypatch.setattr(backport, "LOCKDOWN", lock)
    if accepted:
        backport.unsigned_module_gate()
    else:
        with pytest.raises(RuntimeError):
            backport.unsigned_module_gate()


@pytest.mark.parametrize(
    "directive",
    [
        "os_prefix=other/",
        "ramfsfile=custom.img",
        "kernel = custom.img",
        "initramfs custom.img followkernel",
        "include ../outside.txt",
    ],
)
def test_boot_gate_rejects_unchecked_custom_image_layout(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, directive: str
) -> None:
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "config.txt").write_text("include usercfg.txt\n")
    (boot / "usercfg.txt").write_text(directive + "\n")
    monkeypatch.setattr(backport, "BOOT", boot)
    monkeypatch.setattr(backport, "KERNEL_INITRD", tmp_path / "initrd")
    with pytest.raises(RuntimeError):
        backport.initramfs_gate()


def test_boot_gate_rejects_stock_driver_in_default_initramfs(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "config.txt").write_text("kernel=kernel8.img\ninitramfs initramfs8 followkernel\n")
    (tmp_path / "initramfs8").write_bytes(b"initrd")
    monkeypatch.setattr(backport, "BOOT", tmp_path)
    monkeypatch.setattr(backport, "KERNEL_INITRD", tmp_path / "absent")
    monkeypatch.setattr(backport, "command", lambda _: "usr/lib/modprobe.d/rpi-brcmfmac.conf")
    backport.initramfs_gate()
    monkeypatch.setattr(backport, "command", lambda _: "usr/lib/modules/old/brcmfmac.ko.xz")
    with pytest.raises(RuntimeError, match="contains brcmfmac"):
        backport.initramfs_gate()


@pytest.mark.parametrize("tampered", [True, False])
def test_rollback_removes_only_owned_override_and_does_not_need_headers(
    backport: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tampered: bool
) -> None:
    stock, override = tmp_path / "stock.ko", tmp_path / "override.ko"
    stock.write_bytes(b"packaged stock")
    override.write_bytes(b"owned candidate")
    manifest = {
        "override_path": str(override),
        "module_sha256": backport.sha256(override),
        "stock_sha256": backport.sha256(stock),
        "state": "installed",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    gate_calls: list[bool] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(backport, "root_gate", lambda *, headers=True: gate_calls.append(headers))
    monkeypatch.setattr(backport, "STATE", tmp_path)
    monkeypatch.setattr(backport, "OVERRIDE", override)
    monkeypatch.setattr(backport, "stock_module", lambda: stock)
    monkeypatch.setattr(backport, "resolved_module", lambda: stock)
    monkeypatch.setattr(backport, "command", lambda args: commands.append(args) or "")
    if tampered:
        override.write_bytes(b"someone else")
        with pytest.raises(RuntimeError, match="unowned"):
            backport.rollback()
        assert override.read_bytes() == b"someone else"
        assert not commands
    else:
        backport.rollback()
        assert not override.exists()
        assert commands == [["/sbin/depmod", "-a", backport.KERNEL]]
        assert json.loads((tmp_path / "manifest.json").read_text())["state"] == "rolled_back"
    assert gate_calls == [False]
    assert stock.read_bytes() == b"packaged stock"
