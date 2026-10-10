"""Scope for speculative model calls: started early, always settled on exit."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable


class SpeculativeScope:
    """Owns tasks started ahead of their consumer.

    On exit every unfinished task is cancelled and awaited, and every finished
    task's exception is retrieved, so a discarded speculative call can never leave
    a pending task or an "exception was never retrieved" log behind. A task that was
    awaited by its consumer behaves exactly as if the call had been made serially.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Future] = []

    def start(self, awaitable: Awaitable[Any]) -> asyncio.Future:
        task = asyncio.ensure_future(awaitable)
        self.adopt(task)
        return task

    def adopt(self, task: asyncio.Future) -> asyncio.Future:
        self._tasks.append(task)
        return task

    async def discard(self, task: asyncio.Future | None) -> None:
        """Cancel a speculative task whose result is not needed."""
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def aclose(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def __aenter__(self) -> "SpeculativeScope":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()
