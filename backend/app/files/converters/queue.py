"""Job queue abstraction (plan §3.6 CONVERTER_QUEUE_BACKEND).

Two backends, one interface:

* ``memory`` — an ``asyncio.Queue``. Correct for a single process and for
  tests, and the default when Redis is not reachable.
* ``redis`` — a real Redis list. A separate worker process can drain it, so
  a conversion no longer has to run inside the API process that holds the
  Firebase credentials and the signing key.

The queue carries job ids only. Payload bytes are staged into the job
workspace before enqueueing, so no plaintext ever enters Redis.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_KEY = "converter:jobs"


class QueueUnavailable(Exception):
    """The configured backend could not be reached."""


class MemoryQueue:
    """In-process queue. Bounded so a runaway client cannot exhaust memory."""

    name = "memory"

    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def get(self, timeout: float = 5.0) -> Optional[str]:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def position(self, job_id: str) -> int:
        """Approximate queue position, or 0 when it is not waiting."""
        for index, queued in enumerate(list(self._queue._queue)):  # noqa: SLF001
            if queued == job_id:
                return index
        return 0

    async def depth(self) -> int:
        return self._queue.qsize()


class RedisQueue:
    """Redis-list queue, safe across processes.

    ``LPUSH`` + ``BRPOP`` gives FIFO order: the newest id goes on the left,
    the worker pops from the right.
    """

    name = "redis"

    def __init__(self, redis_client, key: str = QUEUE_KEY) -> None:
        self._redis = redis_client
        self._key = key

    async def put(self, job_id: str) -> None:
        try:
            await self._redis.lpush(self._key, job_id)
        except Exception as err:
            raise QueueUnavailable(str(err)) from err

    async def get(self, timeout: float = 5.0) -> Optional[str]:
        try:
            result = await self._redis.brpop(self._key, timeout=int(timeout))
        except Exception as err:
            raise QueueUnavailable(str(err)) from err
        if not result:
            return None
        _, job_id = result
        return job_id.decode() if isinstance(job_id, bytes) else job_id

    async def position(self, job_id: str) -> int:
        try:
            waiting = await self._redis.lrange(self._key, 0, -1)
        except Exception:
            return 0
        for index, queued in enumerate(reversed(waiting)):
            queued_id = queued.decode() if isinstance(queued, bytes) else queued
            if queued_id == job_id:
                return index
        return 0

    async def depth(self) -> int:
        try:
            return int(await self._redis.llen(self._key))
        except Exception:
            return 0


_queue = None


def get_queue(redis_client=None, backend: Optional[str] = None):
    """Return the process-wide queue, choosing a backend on first use.

    A ``redis`` request that cannot reach Redis falls back to the in-process
    queue with a warning rather than failing the upload: a conversion that
    works in one process beats an upload that 500s.
    """
    global _queue
    if _queue is not None:
        return _queue

    from . import settings

    wanted = (backend or settings.CONVERTER_QUEUE_BACKEND or "memory").lower()

    # A dev fallback client (MockRedis) is in-process only: it can never be
    # drained by a separate worker process, and it does not implement the
    # blocking list ops the Redis backend needs. Treat it as unavailable so
    # the in-process queue is used and conversions still run.
    usable = redis_client is not None and _supports_blocking_pop(redis_client)

    if wanted == "redis" and usable:
        _queue = RedisQueue(redis_client)
        logger.info("Converter queue: redis (%s)", QUEUE_KEY)
    else:
        if wanted == "redis":
            logger.warning(
                "Converter queue: redis requested but %s, using memory",
                "client is not a real Redis" if usable is False else "unavailable",
            )
        _queue = MemoryQueue()
        logger.info("Converter queue: memory")
    return _queue


def _supports_blocking_pop(redis_client) -> bool:
    """True only for a client that can actually serve the worker loop.

    ``BRPOP`` is what a real Redis-backed worker blocks on. The in-memory
    development fallback has no such method, so advertising it as the queue
    backend would leave every job stuck and log a traceback per poll.
    """
    return callable(getattr(redis_client, "brpop", None))


def reset_queue() -> None:
    """Drop the cached queue. Tests use this between cases."""
    global _queue
    _queue = None
