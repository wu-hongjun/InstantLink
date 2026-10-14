from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
from typing import Any, cast

import pytest
from aiohttp import ClientResponse, web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_manager import fake_system_info, signed_headers

from instantlink_bridge import system_stats
from instantlink_bridge.manager import api, status
from instantlink_bridge.manager.auth import (
    AuthorizedClient,
    ClientStore,
    PairingWindowStore,
    SignedRequestVerifier,
    public_key_text,
)
from instantlink_bridge.manager.contract import JsonObject
from instantlink_bridge.manager.update_flow import ManagerEnvironment, UpdateFlowError
from instantlink_bridge.system_info import SystemInfo
from instantlink_bridge.system_stats import CPUSampler, SystemStatsSnapshot

STATS = SystemStatsSnapshot(12.0, 100, 400, 1.0, 8.0, 40.0)


def manager_app(tmp_path: Path) -> tuple[web.Application, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    store = ClientStore(tmp_path / "clients")
    store.save_client(
        AuthorizedClient(
            client_id="macbook",
            client_name="Test Mac",
            public_key=public_key_text(key.public_key()),
            created_at="2026-05-26T15:30:00Z",
        )
    )
    return (
        api.create_app(
            config_path=tmp_path / "config.toml",
            auth_verifier=SignedRequestVerifier(store, now_seconds=lambda: 1000),
            pairing_store=PairingWindowStore(tmp_path / "pairing.json"),
        ),
        key,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/hello", "/v1/status"])
async def test_http_collectors_allow_heartbeat_and_other_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    ticks = 0

    def hold_worker() -> None:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2), "collector blocked the event loop"

    def read_info() -> SystemInfo:
        if path == "/v1/hello":
            hold_worker()
        return fake_system_info()

    def read_stats(_sampler: CPUSampler) -> SystemStatsSnapshot:
        if path == "/v1/status":
            hold_worker()
        return STATS

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.002)

    monkeypatch.setattr(status, "read_system_info", read_info)
    monkeypatch.setattr(status, "read_system_stats", read_stats)
    app, key = manager_app(tmp_path)
    async with TestClient(TestServer(app)) as client:

        async def fetch() -> ClientResponse:
            return await client.get(path, headers=signed_headers(key, path=path))

        beat = asyncio.create_task(heartbeat())
        request = asyncio.create_task(fetch())
        try:
            await asyncio.wait_for(started.wait(), 0.5)
            before = ticks
            await asyncio.sleep(0.03)
            assert ticks >= before + 3
            other = await asyncio.wait_for(client.get("/v1/time"), 0.5)
            assert other.status == 200
            assert not request.done()
            release.set()
            response = await asyncio.wait_for(request, 0.5)
            assert response.status == 200
            assert (await response.json())["ok"] is True
        finally:
            release.set()
            beat.cancel()
            await asyncio.gather(beat, request, return_exceptions=True)


@pytest.mark.asyncio
async def test_cached_versions_keep_config_pairing_and_metrics_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = 0
    samples = 0

    def read_info() -> SystemInfo:
        nonlocal probes
        probes += 1
        return fake_system_info()

    def read_stats(_sampler: CPUSampler) -> SystemStatsSnapshot:
        nonlocal samples
        samples += 1
        return replace(STATS, cpu_percent=float(samples))

    monkeypatch.setattr(status, "read_system_info", read_info)
    monkeypatch.setattr(status, "read_system_stats", read_stats)
    app, key = manager_app(tmp_path)
    async with TestClient(TestServer(app)) as client:
        first = await client.get("/v1/hello")
        assert (await first.json())["device"]["pairing_open"] is False
        app[api.PAIRING_STORE_KEY].open_window()
        app[api.CONFIG_PATH_KEY].write_text(
            '[ftp]\nmode = "wired"\nhost = "192.168.7.9"\n', encoding="utf-8"
        )
        second = await client.get("/v1/hello")
        data = await second.json()
        assert data["device"]["pairing_open"] is True
        assert data["network_labels"][0]["address"] == "192.168.7.9"
        for index in (1, 2):
            response = await client.get(
                "/v1/status", headers=signed_headers(key, nonce=f"nonce-000{index}")
            )
            data = await response.json()
            assert response.status == 200
            assert data["status"]["active_upload_mode"] == "usb_debug"
            assert data["status"]["system_stats"]["cpu_percent"] == index
        assert probes == 1
        assert samples == 2
        # Each app owns its cache; a new listener app starts with a fresh snapshot.
        other_app, _ = manager_app(tmp_path)
        async with TestClient(TestServer(other_app)) as other_client:
            response = await other_client.get("/v1/hello")
            assert response.status == 200
        assert probes == 2


def test_system_info_cache_expires_and_can_be_invalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    probes = 0

    def read_info() -> SystemInfo:
        nonlocal probes
        probes += 1
        return replace(fake_system_info(), app_version=str(probes))

    monkeypatch.setattr(status, "read_system_info", read_info)
    cache = status.SystemInfoCache(now=lambda: now)
    assert cache.read().app_version == "1"
    now += 59.0
    assert cache.read().app_version == "1"
    now += 1.0
    assert cache.read().app_version == "2"
    cache.invalidate()
    assert cache.read().app_version == "3"


@pytest.mark.asyncio
async def test_concurrent_workers_share_one_cold_system_info_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    probes = 0

    def read_info() -> SystemInfo:
        nonlocal probes
        probes += 1
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        return fake_system_info()

    monkeypatch.setattr(status, "read_system_info", read_info)
    cache = status.SystemInfoCache()
    first = asyncio.create_task(asyncio.to_thread(cache.read))
    others: list[asyncio.Task[SystemInfo]] = []
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        others = [asyncio.create_task(asyncio.to_thread(cache.read)) for _ in range(3)]
        await asyncio.sleep(0.03)
        assert probes == 1
        release.set()
        results = await asyncio.gather(first, *others)
        assert all(info == fake_system_info() for info in results)
        assert probes == 1
    finally:
        release.set()
        await asyncio.gather(first, *others, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_status_workers_serialize_cpu_warmup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = asyncio.get_running_loop()
    warming = asyncio.Event()
    second_config = asyncio.Event()
    release = Event()
    config_lock = Lock()
    configs = 0
    original_config_reader = status.read_config_snapshot

    class Sampler(CPUSampler):
        samples = 0

        def sample(self, *, path: str = "") -> float | None:
            self.samples += 1
            return None if self.samples == 1 else float(self.samples * 12)

    sampler = Sampler()

    def warmup(_seconds: float) -> None:
        loop.call_soon_threadsafe(warming.set)
        assert release.wait(2)

    def read_stats(cpu: CPUSampler) -> SystemStatsSnapshot:
        return system_stats.read_system_stats(cpu, sleep=warmup)

    def read_config(path: Path) -> status.ConfigSnapshot:
        nonlocal configs
        with config_lock:
            configs += 1
            if configs == 2:
                loop.call_soon_threadsafe(second_config.set)
        return original_config_reader(path)

    monkeypatch.setattr(status, "read_system_info", fake_system_info)
    monkeypatch.setattr(status, "read_system_stats", read_stats)
    monkeypatch.setattr(status, "read_config_snapshot", read_config)
    monkeypatch.setattr(status, "_status_cpu_sampler", sampler)
    first = asyncio.create_task(
        asyncio.to_thread(status.collect_http_status_payload, tmp_path / "config.toml")
    )
    second: asyncio.Task[JsonObject] | None = None
    try:
        await asyncio.wait_for(warming.wait(), 0.5)
        second = asyncio.create_task(
            asyncio.to_thread(status.collect_http_status_payload, tmp_path / "config.toml")
        )
        await asyncio.wait_for(second_config.wait(), 0.5)
        await asyncio.sleep(0.03)
        assert sampler.samples == 1, "another request sampled during the first CPU warm-up"
        release.set()
        results = await asyncio.gather(first, second)
        assert [
            cast(dict[str, Any], result["status"])["system_stats"]["cpu_percent"]
            for result in results
        ] == [
            24.0,
            36.0,
        ]
        assert sampler.samples == 3
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "rollback"])
@pytest.mark.parametrize("fails", [False, True])
async def test_firmware_operations_invalidate_cached_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, fails: bool
) -> None:
    info = fake_system_info()

    def change_firmware(_env: ManagerEnvironment, _argument: object) -> JsonObject:
        nonlocal info
        info = replace(info, app_version="new-version")
        if fails:
            raise UpdateFlowError("update_failed", "Changed files before failure", http_status=409)
        return {"update": {"phase": "complete"}}

    monkeypatch.setattr(status, "read_system_info", lambda: info)
    monkeypatch.setattr(api, f"run_{operation}", change_firmware)
    app, key = manager_app(tmp_path)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/v1/hello")
        assert (await response.json())["device"]["software_version"] == info.app_version
        path = f"/v1/update/{operation}"
        body = json.dumps(
            {"package": {}} if operation == "install" else {"reason": "test"}
        ).encode()
        response = await client.post(
            path, data=body, headers=signed_headers(key, method="POST", path=path, body=body)
        )
        assert response.status == (409 if fails else 200)
        refreshed = await client.get("/v1/hello")
        assert (await refreshed.json())["device"]["software_version"] == "new-version"


@pytest.mark.asyncio
async def test_cancelled_firmware_request_still_invalidates_after_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = fake_system_info()
    monkeypatch.setattr(status, "read_system_info", lambda: info)
    cache = status.SystemInfoCache()
    assert cache.read() == info
    release = Event()
    finished = Event()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()

    def operation() -> JsonObject:
        nonlocal info
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        info = replace(info, app_version="new-version")
        return {}

    def worker() -> JsonObject:
        try:
            return api.run_firmware_change(cache, operation)
        finally:
            finished.set()

    request = asyncio.create_task(asyncio.to_thread(worker))
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        release.set()
        assert await asyncio.to_thread(finished.wait, 0.5)
        assert cache.read().app_version == "new-version"
    finally:
        release.set()
        await asyncio.to_thread(finished.wait, 2)
