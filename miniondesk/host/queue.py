"""Per-group serialized message queue."""
from __future__ import annotations
import asyncio
import logging
from typing import Callable, Awaitable, Any

from . import config

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[Any]]

# Warn when a group queue reaches this fraction of max capacity
_QUEUE_WARN_THRESHOLD = 0.75


class GroupQueue:
    """Serializes coroutine execution per group JID.

    Each group has its own bounded queue (max QUEUE_MAX_PER_GROUP items).
    Submitting to a full queue logs a warning and discards the coroutine
    rather than blocking or growing without limit (backpressure).
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}

    def _get_queue(self, jid: str) -> asyncio.Queue:
        if jid not in self._queues:
            self._queues[jid] = asyncio.Queue(maxsize=config.QUEUE_MAX_PER_GROUP)
            self._locks[jid] = asyncio.Lock()
            self._workers[jid] = asyncio.create_task(self._worker(jid))
        return self._queues[jid]

    async def _worker(self, jid: str) -> None:
        q = self._queues[jid]
        while True:
            coro = await q.get()
            try:
                await coro
            except Exception as exc:
                logger.error("GroupQueue worker [%s] error: %s", jid, exc)
            finally:
                q.task_done()

    def submit(self, jid: str, coro) -> None:
        """Submit a coroutine for serialized execution in the given group.

        If the queue is full, the coroutine is discarded and a warning is logged
        rather than allowing unbounded memory growth (backpressure guard).
        """
        q = self._get_queue(jid)
        depth = q.qsize()
        max_size = config.QUEUE_MAX_PER_GROUP

        if depth >= max_size:
            logger.warning(
                "GroupQueue [%s] full (%d/%d) — dropping message (backpressure). "
                "Consider increasing QUEUE_MAX_PER_GROUP or CONTAINER_MAX_CONCURRENT.",
                jid, depth, max_size,
            )
            return

        if depth >= int(max_size * _QUEUE_WARN_THRESHOLD):
            logger.warning(
                "GroupQueue [%s] near capacity: %d/%d items queued",
                jid, depth, max_size,
            )

        q.put_nowait(coro)

    async def shutdown(self) -> None:
        """Cancel all worker tasks gracefully during host shutdown.

        Without this, queued-but-unstarted coroutines are silently abandoned
        when the event loop closes after SIGTERM. Calling shutdown() before
        stopping channels ensures in-progress work has a chance to log its
        cancellation and any pending items in the queue are dropped visibly.
        """
        for jid, task in list(self._workers.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                pending = self._queues[jid].qsize()
                if pending:
                    logger.warning(
                        "GroupQueue [%s] shutdown: %d queued item(s) dropped",
                        jid, pending,
                    )
        self._workers.clear()
        self._queues.clear()
        self._locks.clear()


_default_queue = GroupQueue()


def get_queue() -> GroupQueue:
    return _default_queue
