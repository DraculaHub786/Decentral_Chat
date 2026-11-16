"""Regression tests for the session, file-access and attachment fixes.

These drive the real handler code with a stub request, so they fail if the
behaviour regresses rather than merely if a name disappears.
"""
import asyncio
import datetime
import pathlib
import sys
import uuid

import jwt

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.globals import g
from app.core._mockredis import MockRedis
from app.core.config import SECRET_KEY, UPLOAD_DIR
from app.auth import handlers as auth_handlers
from app.files import handlers as file_handlers
from app.chats import membership

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  " + name)
    else:
        FAILED.append(name + " (" + str(detail) + ")")
        print("  FAIL  " + name + "  " + str(detail))


class StubRequest:
    """Only the surface the handlers touch."""

    def __init__(self, payload=None, headers=None, match=None, query=None):
        self._payload = payload or {}
        self.headers = headers or {}
        self.match_info = match or {}
        self.query = query or {}

    async def json(self):
        return self._payload


class StubServer:
    """Stands in for DecentralChatServer: just the token hooks."""

    db = None

    def generate_token(self, user_id):
        return "access-for-" + user_id

    async def _generate_refresh_token(self, user_id, device_fp):
        return "refresh-for-" + user_id


def _refresh_token_for(token_id, user_id):
    expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)
    return jwt.encode(
        {"type": "refresh", "token_id": token_id, "user_id": user_id, "exp": expires},
        SECRET_KEY,
        algorithm="HS256",
    )


async def test_refresh_survives_lost_response():
    """A rotated token stays usable briefly, so a dropped reply is not a logout."""
    print("\n[refresh] rotation grace window")
    g.redis_client = MockRedis()
    server = StubServer()

    token_id = str(uuid.uuid4())
    user_id = "user-1"
    token = _refresh_token_for(token_id, user_id)

    first = await auth_handlers.refresh_token(server, StubRequest({"refresh_token": token}))
    check("first refresh succeeds", first.status == 200, first.status)

    replay = await auth_handlers.refresh_token(server, StubRequest({"refresh_token": token}))
    check("replay inside grace window succeeds", replay.status == 200, replay.status)

    old = str(uuid.uuid4())
    long_ago = datetime.datetime.now(datetime.UTC).timestamp() - 600
    await g.redis_client.hset(
        "refresh_token:" + old,
        mapping={"revoked": "true", "rotated_at": str(long_ago)},
    )
    stale = await auth_handlers.refresh_token(
        server, StubRequest({"refresh_token": _refresh_token_for(old, user_id)})
    )
    check("replay after grace window refused", stale.status == 401, stale.status)

    unknown = str(uuid.uuid4())
    await g.redis_client.hset("refresh_token:" + unknown, mapping={"revoked": "true"})
    no_stamp = await auth_handlers.refresh_token(
        server, StubRequest({"refresh_token": _refresh_token_for(unknown, user_id)})
    )
    check("revoked token without timestamp refused", no_stamp.status == 401, no_stamp.status)


async def test_file_access_requires_entitlement():
    """Being logged in is not enough; you must own the file or share its chat."""
    print("\n[files] serve_upload entitlement")
    g.redis_client = MockRedis()

    upload_dir = pathlib.Path(UPLOAD_DIR)
    (upload_dir / "documents").mkdir(parents=True, exist_ok=True)
    name = "documents/" + str(uuid.uuid4()) + ".txt"
    probe = upload_dir / name
    probe.write_text("hello", encoding="utf-8")

    original = {
        "get_user_from_token": file_handlers.get_user_from_token,
        "_file_meta_for_path": file_handlers._file_meta_for_path,
        "is_chat_member": file_handlers.is_chat_member,
    }

    try:
        async def logged_in(request):
            return "user-recipient"

        async def no_token(request):
            return None

        async def meta_in_chat_one(path):
            return {"id": "file-1", "user_id": "user-owner", "chat_id": "chat-1"}

        async def member(chat_id, user_id):
            return True

        async def not_member(chat_id, user_id):
            return False

        req = StubRequest(match={"filename": name})

        file_handlers.get_user_from_token = no_token
        res = await file_handlers.serve_upload(req)
        check("anonymous request rejected", res.status == 401, res.status)

        file_handlers.get_user_from_token = logged_in
        file_handlers._file_meta_for_path = meta_in_chat_one
        file_handlers.is_chat_member = not_member
        res = await file_handlers.serve_upload(req)
        check("logged-in stranger rejected", res.status == 403, res.status)

        file_handlers.is_chat_member = member
        res = await file_handlers.serve_upload(req)
        check("chat member allowed", res.status == 200, res.status)

        async def meta_owned_by_caller(path):
            return {"id": "file-1", "user_id": "user-recipient"}

        file_handlers._file_meta_for_path = meta_owned_by_caller
        file_handlers.is_chat_member = not_member
        res = await file_handlers.serve_upload(req)
        check("uploader allowed", res.status == 200, res.status)

        async def no_record(path):
            return None

        file_handlers._file_meta_for_path = no_record
        res = await file_handlers.serve_upload(req)
        check("unindexed file denied", res.status == 403, res.status)
    finally:
        for attr, value in original.items():
            setattr(file_handlers, attr, value)
        probe.unlink(missing_ok=True)


async def test_membership_survives_cache_loss():
    """After an eviction, membership is rebuilt from the database."""
    print("\n[membership] cache repair")
    redis = MockRedis()
    g.redis_client = redis

    class Doc:
        exists = True

        def to_dict(self):
            return {"members": ["alice", "bob"]}

    class DocRef:
        def get(self):
            return Doc()

    class Collection:
        def document(self, chat_id):
            return DocRef()

    class Db:
        def collection(self, name):
            return Collection()

    original_db = g.db
    g.db = Db()
    try:
        check("cache is cold", not await redis.smembers("chat_members:chat-9"))
        check("member recognised from database",
              await membership.is_chat_member("chat-9", "alice"))
        check("non-member still refused",
              not await membership.is_chat_member("chat-9", "mallory"))
        check("cache repaired",
              {"alice", "bob"} <= await redis.smembers("chat_members:chat-9"))
        check("sidebar repaired", "chat-9" in await redis.smembers("user_chats:alice"))
    finally:
        g.db = original_db


async def test_attachment_bound_to_chat():
    """Sending a file records the chat, which is what grants recipients access."""
    print("\n[attachments] chat binding")
    redis = MockRedis()
    g.redis_client = redis
    original_db = g.db
    g.db = None
    try:
        await membership.bind_file_to_chat("file-7", "chat-3")
        stored = await redis.hget("file:file-7", "chat_id")
        check("chat id recorded on file", stored == "chat-3", stored)
        check("file listed under chat", "file-7" in await redis.smembers("chat_files:chat-3"))

        found = await membership.chat_id_for_file("file-7")
        check("chat resolvable from file", found == "chat-3", found)

        await membership.bind_file_to_chat("", "chat-3")
        check("blank file id ignored", await redis.hget("file:", "chat_id") is None)
    finally:
        g.db = original_db


async def test_signed_media_urls():
    """Media tokens authorise one file, one user, until they expire."""
    print("\n[media] signed URL tokens")
    import app.files.media_tokens as mt

    name = "images/abc.png"
    good = mt.issue_media_token(name, "alice")

    check("token verifies", mt.read_media_token(good) is not None)
    check("right user, right file", mt.token_allows(good, name, "alice"))
    check("wrong user refused", not mt.token_allows(good, name, "bob"))
    check("wrong file refused", not mt.token_allows(good, "images/x.png", "alice"))
    check("anonymous refused", not mt.token_allows(good, name, None))
    check("garbage refused", not mt.token_allows("not-a-token", name, "alice"))
    check("empty refused", not mt.token_allows("", name, "alice"))

    tampered = good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb")
    check("tampered refused", not mt.token_allows(tampered, name, "alice"))

    original_ttl = mt.MEDIA_TOKEN_TTL_SECONDS
    try:
        mt.MEDIA_TOKEN_TTL_SECONDS = -1
        check("expired refused", not mt.token_allows(mt.issue_media_token(name, "alice"), name, "alice"))
    finally:
        mt.MEDIA_TOKEN_TTL_SECONDS = original_ttl

    url = mt.signed_media_url(name, "alice")
    check("url targets upload path", url.startswith("/api/uploads/images/abc.png?mt="), url)


async def main():
    await test_refresh_survives_lost_response()
    await test_file_access_requires_entitlement()
    await test_membership_survives_cache_loss()
    await test_attachment_bound_to_chat()
    await test_signed_media_urls()

    print("\n" + str(len(PASSED)) + " passed, " + str(len(FAILED)) + " failed")
    if FAILED:
        for failure in FAILED:
            print("  - " + failure)
        return 1
    print("ALL SECURITY REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
