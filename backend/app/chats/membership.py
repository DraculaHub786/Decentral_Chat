"""Chat membership checks that survive a Redis eviction.

Redis is a cache here; Firestore is the source of truth. Everything that
needs to answer "may this user see this chat's content" goes through
`is_chat_member`, so the answer stays correct after a restart, an eviction,
or a multi-day gap between messages.
"""
import json
import logging
from typing import List, Optional

from app.globals import g

logger = logging.getLogger(__name__)


def _as_text(value) -> str:
    """Redis hands back bytes; Firestore hands back str."""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _member_ids_from_doc(chat_data: dict) -> List[str]:
    """Extract member ids from any shape this codebase has written."""
    raw = (
        chat_data.get("members")
        or chat_data.get("participant_ids")
        or chat_data.get("member_ids")
        or []
    )
    if not isinstance(raw, list):
        return []
    if raw and isinstance(raw[0], dict):
        return [
            _as_text(m.get("id") or m.get("user_id") or m.get("uid"))
            for m in raw
            if isinstance(m, dict) and (m.get("id") or m.get("user_id") or m.get("uid"))
        ]
    return [_as_text(m) for m in raw if isinstance(m, (str, bytes))]


async def get_chat_members(chat_id: str) -> List[str]:
    """Member ids for a chat, preferring Redis and repairing it from Firestore."""
    cached = set()
    try:
        cached = await g.redis_client.smembers(f"chat_members:{chat_id}")
    except Exception as err:
        logger.warning("Redis member lookup failed for %s: %s", chat_id, err)

    members = {_as_text(m) for m in cached} if cached else set()
    if members:
        return sorted(members)

    if not g.db:
        return []

    try:
        snapshot = g.db.collection("chats").document(chat_id).get()
        if not snapshot.exists:
            return []
        members = set(_member_ids_from_doc(snapshot.to_dict() or {}))
    except Exception as err:
        logger.error("Firestore member lookup failed for %s: %s", chat_id, err)
        return []

    # Repopulate the cache, and heal the per-user chat lists too, otherwise the
    # conversation vanishes from a recipient's sidebar after an eviction.
    for member_id in members:
        try:
            await g.redis_client.sadd(f"chat_members:{chat_id}", member_id)
            await g.redis_client.sadd(f"user_chats:{member_id}", chat_id)
        except Exception:
            pass

    if members:
        logger.info("Repaired membership cache for chat %s (%d members)",
                    chat_id, len(members))
    return sorted(members)


async def is_chat_member(chat_id: str, user_id: str) -> bool:
    """True when `user_id` belongs to `chat_id`, cache or database."""
    if not chat_id or not user_id:
        return False
    try:
        if await g.redis_client.sismember(f"chat_members:{chat_id}", user_id):
            return True
    except Exception:
        pass
    members = await get_chat_members(chat_id)
    return _as_text(user_id) in members


async def chat_id_for_file(file_id: str) -> Optional[str]:
    """Which chat a stored file was sent to, if any (Redis, then Firestore)."""
    if not file_id:
        return None
    try:
        cached = await g.redis_client.hget(f"file:{file_id}", "chat_id")
        if cached:
            return _as_text(cached)
    except Exception:
        pass

    if not g.db:
        return None

    try:
        snapshot = g.db.collection("files").document(file_id).get()
        if snapshot.exists:
            chat_id = (snapshot.to_dict() or {}).get("chat_id")
            return _as_text(chat_id) if chat_id else None
    except Exception as err:
        logger.warning("Firestore file lookup failed for %s: %s", file_id, err)
    return None


def _attachment_file_ids(raw) -> List[str]:
    """Attachment ids from any payload shape this codebase has written."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    file_ids = []
    for entry in raw:
        file_id = entry.get("id") if isinstance(entry, dict) else entry
        if isinstance(file_id, (str, bytes)) and file_id:
            file_ids.append(_as_text(file_id))
    return file_ids


async def backfill_attachment_chat_ids(limit: int = 5000) -> int:
    """Rebuild the chat binding for attachments sent before it existed.

    Files uploaded before `bind_file_to_chat` was introduced carry no
    `chat_id`, so the download endpoint refuses them even to the recipient.
    Each message names both its chat and its attachments, so the link can be
    reconstructed from the message that already references the file.

    Returns how many files gained a binding. Safe to re-run: files that
    already resolve to a chat are skipped.
    """
    if not g.db:
        return 0

    repaired = 0
    try:
        for doc in g.db.collection("messages").stream():
            data = doc.to_dict() or {}
            chat_id = _as_text(data.get("chat_id") or "")
            if not chat_id:
                continue
            for file_id in _attachment_file_ids(data.get("attachments")):
                if await chat_id_for_file(file_id):
                    continue
                await bind_file_to_chat(file_id, chat_id)
                repaired += 1
                if repaired >= limit:
                    logger.info("Attachment backfill hit its limit of %d", limit)
                    return repaired
    except Exception as err:
        logger.error("Attachment chat-id backfill failed: %s", err)

    if repaired:
        logger.info("Backfilled chat binding for %d legacy attachment(s)", repaired)
    return repaired


async def bind_file_to_chat(file_id: str, chat_id: str) -> None:
    """Record that a file belongs to a chat so recipients may fetch it later.

    Without this the download endpoint cannot tell a recipient from a
    stranger, which is why it previously admitted any logged-in user.
    """
    if not file_id or not chat_id:
        return
    try:
        await g.redis_client.hset(f"file:{file_id}", mapping={"chat_id": chat_id})
        await g.redis_client.sadd(f"chat_files:{chat_id}", file_id)
    except Exception as err:
        logger.warning("Could not tag file %s with chat %s in Redis: %s",
                       file_id, chat_id, err)

    if g.db:
        try:
            g.db.collection("files").document(file_id).set(
                {"chat_id": chat_id}, merge=True
            )
        except Exception as err:
            logger.error("Could not tag file %s with chat %s in Firestore: %s",
                         file_id, chat_id, err)
