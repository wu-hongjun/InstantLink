"""CPU performance policy, independent of LCD brightness and Printer transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

LOGGER = logging.getLogger(__name__)
CPU_HELPER = Path("/usr/local/sbin/instantlink-bridge-cpu-mode")
CPU_SETTER_TIMEOUT = 4.0
CPU_RETRY_DELAY = 0.25
CPU_RETRY_MAX_DELAY = 30.0


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
    """Run awake/work at stock maximum; pin idle, dark screens to stock minimum.

    Requests coalesce under a lock. Image preparation and accepted prints hold
    a boost even with the LCD locked. Waiting for a person's confirmation has
    no boost, so a locked Bridge returns to its idle clock between operations.
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
        self._retry_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
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
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._shutdown())
        cancellation: asyncio.CancelledError | None = None
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError as exc:
                # Repeated caller cancellation must still join cleanup: a
                # helper may have changed sysfs before returning a result.
                cancellation = exc
        self._close_task.result()
        if cancellation is not None:
            raise cancellation

    async def _shutdown(self) -> None:
        tasks = [task for task in (self._task, self._retry_task) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._apply()

    async def _apply(self) -> None:
        async with self._lock:
            while True:
                governor = self._desired_governor()
                if governor == self._applied:
                    return
                # External writes are not transactional. A timeout or cancelled
                # helper can have written the governor before it exits.
                self._applied = None
                try:
                    async with asyncio.timeout(CPU_SETTER_TIMEOUT):
                        await self._setter(governor)
                except asyncio.CancelledError:
                    self._schedule_retry()
                    raise
                except Exception:
                    # Missing helper must not break printing or spam every render.
                    if not self._failure_reported:
                        LOGGER.warning("power.cpu_mode_failed governor=%s", governor, exc_info=True)
                        self._failure_reported = True
                    self._schedule_retry()
                    return
                self._applied = governor
                self._failure_reported = False
                LOGGER.info("power.cpu_mode governor=%s photo_jobs=%s", governor, self._jobs)
                # The screen can change while the helper is running. Reconcile
                # again so a wake request cannot be lost behind an idle write.

    def _schedule_retry(self) -> None:
        if self._closed:
            return
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry())

    async def _retry(self) -> None:
        delay = CPU_RETRY_DELAY
        while not self._closed and self._desired_governor() != self._applied:
            await asyncio.sleep(delay)
            if self._closed:
                return
            await self._apply()
            delay = min(delay * 2, CPU_RETRY_MAX_DELAY)

    def _desired_governor(self) -> str:
        if self._closed:
            return "ondemand"
        if self._power_saving and self._jobs == 0:
            return "powersave"
        return "performance"
