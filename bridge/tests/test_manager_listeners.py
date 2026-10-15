from __future__ import annotations

import asyncio
import errno
from collections import Counter
from typing import cast

import pytest
from aiohttp import web

from instantlink_bridge.manager import cli


@pytest.mark.asyncio
async def test_missing_hotspot_retries_without_rebinding_usb_or_leaking_failed_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: Counter[str] = Counter()
    registered: set[object] = set()
    live: set[str] = set()

    class Site:
        def __init__(self, _runner: web.AppRunner, host: str, port: int) -> None:
            assert port == 8742
            self.host = host

        async def start(self) -> None:
            registered.add(self)
            calls[self.host] += 1
            if self.host == "192.168.8.1" and calls[self.host] < 3:
                raise OSError(errno.EADDRNOTAVAIL, "address not ready")
            live.add(self.host)

        async def stop(self) -> None:
            registered.remove(self)

    monkeypatch.setattr(cli.web, "TCPSite", Site)
    monkeypatch.setattr(cli, "BIND_RETRY_DELAYS_S", (0.001,))
    runner = cast(web.AppRunner, object())
    assert await cli.start_listener(runner, "192.168.7.1", 8742)
    assert not await cli.start_listener(runner, "192.168.8.1", 8742, report_failure=True)
    assert len(registered) == 1
    await asyncio.wait_for(
        cli.retry_missing_listeners(runner, ["192.168.8.1"], 8742, asyncio.Event()), timeout=1
    )
    assert calls == {"192.168.7.1": 1, "192.168.8.1": 3}
    assert live == {"192.168.7.1", "192.168.8.1"}
    assert len(registered) == 2


@pytest.mark.asyncio
async def test_shutdown_interrupts_listener_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_start(*_args: object, **_kwargs: object) -> bool:
        pytest.fail("shutdown must not attempt another socket")

    monkeypatch.setattr(cli, "start_listener", unexpected_start)
    monkeypatch.setattr(cli, "BIND_RETRY_DELAYS_S", (30.0,))
    stop = asyncio.Event()
    task = asyncio.create_task(
        cli.retry_missing_listeners(cast(web.AppRunner, object()), ["192.168.8.1"], 8742, stop)
    )
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_no_missing_hosts_performs_no_background_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_start(*_args: object, **_kwargs: object) -> bool:
        pytest.fail("healthy listeners need no polling")

    monkeypatch.setattr(cli, "start_listener", unexpected_start)
    await cli.retry_missing_listeners(cast(web.AppRunner, object()), [], 8742, asyncio.Event())
