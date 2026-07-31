from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError


@dataclass
class RuntimeEntry:
    conversation_id: int
    task: asyncio.Task
    assistant_message_id: int | None = None


class ConversationRuntimeRegistry:
    """Process-local active generation registry.

    This deliberately makes no distributed-cancellation claim. A Redis-backed
    implementation can replace this class without changing the service API.
    """

    def __init__(self) -> None:
        self._entries: dict[int, RuntimeEntry] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, conversation_id: int, task: asyncio.Task) -> None:
        async with self._lock:
            current = self._entries.get(conversation_id)
            if current and not current.task.done():
                raise AIError(
                    AIErrorCode.conversation_busy,
                    "This conversation is already generating a response.",
                    retryable=True,
                    status_code=409,
                )
            self._entries[conversation_id] = RuntimeEntry(conversation_id=conversation_id, task=task)

    async def bind_message(self, conversation_id: int, assistant_message_id: int, task: asyncio.Task) -> None:
        async with self._lock:
            entry = self._entries.get(conversation_id)
            if entry and entry.task is task:
                entry.assistant_message_id = assistant_message_id

    async def cancel(self, conversation_id: int) -> RuntimeEntry | None:
        async with self._lock:
            entry = self._entries.get(conversation_id)
            if not entry or entry.task.done():
                return None
            entry.task.cancel()
            return entry

    async def active(self, conversation_id: int) -> RuntimeEntry | None:
        async with self._lock:
            entry = self._entries.get(conversation_id)
            return entry if entry and not entry.task.done() else None

    async def unregister(self, conversation_id: int, task: asyncio.Task) -> None:
        async with self._lock:
            entry = self._entries.get(conversation_id)
            if entry and entry.task is task:
                self._entries.pop(conversation_id, None)


runtime_registry = ConversationRuntimeRegistry()
