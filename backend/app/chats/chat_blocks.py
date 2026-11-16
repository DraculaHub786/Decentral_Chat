"""Per-chat (group) member blocking.

The existing `/api/users/block` hides a person everywhere: it is account-level
and it is symmetric. A group needs something narrower - "I want to stay in this
group, but I do not want to see this one member". Call that a chat block.

Design notes:
  * Directional and private. A block is stored from the blocker's side only, so
    the blocked member is never told and is unaffected in other chats.
  * Scoped to one chat. The same person can be blocked in one group and still
    visible in a direct chat, which is the whole point of the feature.
  * Enforced on read, not on write. The message is still delivered, stored and
    visible to everyone else; only the blocker's `get_messages` drops it. This
    keeps history consistent if the block is later removed.
  * Self-contained. It reuses `is_chat_member` for authorisation and writes to
    the same Redis structure style as `deleted_messages:{user}` already does.
"""
import logging
from typing import List, Set

from app.globals import g

from .membership import is_chat_member

logger = logging.getLogger(__name__)


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _key(chat_id: str, user_id: str) -> str:
    return f"chat_blocks:{chat_id}:{user_id}"


async def block_member_in_chat(chat_id: str, blocker_id: str, blocked_id: str) -> bool:
    """Record that ``blocker_id`` does not want to see ``blocked_id`` in a chat.

    Returns False (without raising) when the request cannot be honoured: both
    parties must belong to the chat, and self-blocking is meaningless.
    """
    if not chat_id or not blocker_id or not blocked_id:
        return False
    if blocker_id == blocked_id:
        return False

    # Both must actually be in the chat; otherwise this endpoint would let a
    # stranger write rows against chats they have nothing to do with.
    if not await is_chat_member(chat_id, blocker_id):
        return False
    if not await is_chat_member(chat_id, blocked_id):
        return False

    try:
        await g.redis_client.sadd(_key(chat_id, blocker_id), blocked_id)
        logger.info("User %s blocked %s in chat %s", blocker_id, blocked_id, chat_id)
        return True
    except Exception as err:
        logger.error("Could not store chat block %s/%s: %s", chat_id, blocked_id, err)
        return False


async def unblock_member_in_chat(chat_id: str, blocker_id: str, blocked_id: str) -> bool:
    """Remove a chat block. Idempotent: removing a non-existent block succeeds."""
    if not chat_id or not blocker_id or not blocked_id:
        return False
    if not await is_chat_member(chat_id, blocker_id):
        return False
    try:
        await g.redis_client.srem(_key(chat_id, blocker_id), blocked_id)
        logger.info("User %s unblocked %s in chat %s", blocker_id, blocked_id, chat_id)
        return True
    except Exception as err:
        logger.error("Could not remove chat block %s/%s: %s", chat_id, blocked_id, err)
        return False


async def blocked_members_in_chat(chat_id: str, blocker_id: str) -> List[str]:
    """Member ids this user has blocked inside one chat."""
    if not chat_id or not blocker_id:
        return []
    try:
        raw = await g.redis_client.smembers(_key(chat_id, blocker_id))
    except Exception as err:
        logger.warning("Could not read chat blocks for %s/%s: %s", chat_id, blocker_id, err)
        return []
    return sorted({_as_text(item) for item in (raw or [])})


async def blocked_sender_set(chat_id: str, blocker_id: str) -> Set[str]:
    """The same list as a set, for cheap filtering in a message loop."""
    return set(await blocked_members_in_chat(chat_id, blocker_id))
