from __future__ import annotations

import asyncio


class DeepSearchRuntime:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def get(self, run_id: str) -> asyncio.Task | None:
        async with self._lock:
            task = self._tasks.get(run_id)
            if task is not None and task.done():
                self._tasks.pop(run_id, None)
                return None
            return task

    async def start(self, run_id: str, coroutine) -> asyncio.Task:
        async with self._lock:
            existing = self._tasks.get(run_id)
            if existing is not None and not existing.done():
                return existing
            task = asyncio.create_task(coroutine, name=f"deep-search:{run_id}")
            self._tasks[run_id] = task
            task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
            return task

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


deep_search_runtime = DeepSearchRuntime()
