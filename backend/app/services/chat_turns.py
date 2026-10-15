"""Explicit cancellation, independent of SSE transport lifetime (one worker)."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock


class TurnCancelled(asyncio.CancelledError):
    pass


@dataclass
class ChatTurn:
    session_id: str
    turn_id: str
    owner: str
    cancelled: bool = False
    committed: bool = False
    cleanup_failed: bool = False
    task: asyncio.Task | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    _commit_lock: Lock = field(default_factory=Lock)

    def check(self):
        if self.cancelled:
            raise TurnCancelled()

    def cancel(self) -> bool:
        # Only the short SQL commit shares this lock, never layout or LLM work.
        with self._commit_lock:
            if self.committed or self.done.is_set():
                return False
            first = not self.cancelled
            self.cancelled = True
        if first and self.task:
            self.task.cancel()
        return True

    def commit(self, db, *, final=True):
        with self._commit_lock:
            self.check()
            db.commit()
            if final:
                self.committed = True


current_turn: ContextVar[ChatTurn | None] = ContextVar('current_chat_turn', default=None)
active_turns: dict[tuple[str, str], ChatTurn] = {}
