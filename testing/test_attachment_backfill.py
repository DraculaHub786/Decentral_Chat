"""Legacy attachments must regain the chat binding they were sent without.

Files uploaded before `bind_file_to_chat` existed carry no `chat_id`, so the
download endpoint refuses them even to the recipient. The binding is rebuilt
from the message that already references each file.
"""
import asyncio
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.globals import g
from app.core._mockredis import MockRedis
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


class Doc:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class Collection:
    def __init__(self, docs):
        self._docs = docs

    def stream(self):
        return list(self._docs)

    def document(self, _id):
        return None


class Db:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        return Collection(self._docs)


async def run_checks():
    redis = MockRedis()
    g.redis_client = redis
    original_db = g.db

    docs = [
        Doc({"chat_id": "chat-a", "attachments": ["old-1", "old-2"]}),
        Doc({"chat_id": "chat-b", "attachments": '[{"id": "old-3"}]'}),
        Doc({"chat_id": "", "attachments": ["orphan"]}),
        Doc({"chat_id": "chat-c", "attachments": "not-json"}),
    ]

    try:
        g.db = Db(docs)
        repaired = await membership.backfill_attachment_chat_ids()

        check("three bindings repaired", repaired == 3, repaired)
        check("first file bound",
              await redis.hget("file:old-1", "chat_id") == "chat-a")
        check("second file bound",
              await redis.hget("file:old-2", "chat_id") == "chat-a")
        check("json-string payload parsed",
              await redis.hget("file:old-3", "chat_id") == "chat-b")
        check("chatless message skipped",
              await redis.hget("file:orphan", "chat_id") is None)
        check("unparseable payload skipped",
              not await redis.smembers("chat_files:chat-c"))
        check("file listed under its chat",
              "old-1" in await redis.smembers("chat_files:chat-a"))

        again = await membership.backfill_attachment_chat_ids()
        check("re-run is a no-op", again == 0, again)

        g.db = None
        check("no database is a no-op",
              await membership.backfill_attachment_chat_ids() == 0)
    finally:
        g.db = original_db


def main():
    print("[attachments] legacy chat-id backfill")
    asyncio.run(run_checks())
    total = len(PASSED) + len(FAILED)
    print("\n" + str(len(PASSED)) + " passed, " + str(len(FAILED)) + " failed")
    if FAILED:
        for failure in FAILED:
            print("  - " + failure)
        return 1
    print("ATTACHMENT BACKFILL CHECKS PASSED (" + str(total) + " checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
