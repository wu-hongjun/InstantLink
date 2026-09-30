"""CPU performance policy, independent of LCD brightness and Printer transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

LOGGER = logging.getLogger(__name__)
CPU_HELPER = Path("/usr/local/sbin/instantlink-bridge-cpu-mode")


async def set_cpu_governor(governor: str) -> None:
    """Use the provisioned, root-owned helper without granting general sudo access."""

    process = await asyncio.create_subprocess_exec(
        "sudo",
        "-n",
        str(CPU_HELPER),
        governor,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=3.0)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip())


class CpuPerformanceController:
    """Run awake/work at stock maximum; let an idle, dark screen scale down.

    Requests coalesce under a lock. A photo job holds a boost through preview,
    edits, image preparation and print completion even if the LCD stays locked.
    """

    def __init__(
        self,
        setter: Callable[[str], Awaitable[None]] = set_cpu_governor,
    ) -> None:
        self._setter = setter
        self._power_saving = False
        self._jobs = 0
        self._applied: str | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._failure_reported = False

    async def start(self) -> None:
        """Apply awake performance before starting Bridge services."""

        await self._apply()

    def set_power_saving(self, enabled: bool) -> None:
        """Schedule a mode transition without blocking rendering or input."""

        if self._closed or enabled == self._power_saving:
            return
        self._power_saving = enabled
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._apply())

    @asynccontextmanager
    async def boost(self) -> AsyncIterator[None]:
        """Ensure maximum performance before beginning photo processing."""

        self._jobs += 1
        try:
            await self._apply()
            yield
        finally:
            self._jobs -= 1
            await self._apply()

    async def close(self) -> None:
        """Restore automatic scaling when the Bridge exits."""

        self._closed = True
        if self._task is not None:
            await self._task
        await self._apply()

    async def _apply(self) -> None:
        async with self._lock:
            while True:
                governor = self._desired_governor()
                if governor == self._applied:
                    return
                try:
                    await self._setter(governor)
                except Exception:
                    # Missing helper must not break printing or spam every render.
                    if not self._failure_reported:
                        LOGGER.warning("power.cpu_mode_failed governor=%s", governor, exc_info=True)
                        self._failure_reported = True
                    return
                self._applied = governor
                self._failure_reported = False
                LOGGER.info("power.cpu_mode governor=%s photo_jobs=%s", governor, self._jobs)
                # The screen can change while the helper is running. Reconcile
                # again so a wake request cannot be lost behind an idle write.

    def _desired_governor(self) -> str:
        if self._closed or (self._power_saving and self._jobs == 0):
            return "ondemand"
        return "performance"
