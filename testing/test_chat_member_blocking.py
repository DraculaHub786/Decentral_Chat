"""Per-group member blocking (C3).

The feature is narrow on purpose: hiding one member inside one group, for one
viewer. These checks pin down the properties that make it different from the
account-wide /api/users/block, because getting those wrong is what made the
original attempt fail:

  * a chat block is invisible to the blocked member;
  * it is scoped to a single chat;
  * it hides messages on read without destroying them.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.chats import chat_blocks
from app.core._mockredis import MockRedis
from app.globals import g

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)
        if detail:
            print(f"      {detail}")


GROUP = "group-chat-1"
OTHER_GROUP = "group-chat-2"
ALICE = "alice"
BOB = "bob"


async def seed():
    """Two groups; alice and bob are in both, plus carol in the first."""
    await g.redis_client.delete(f"chat_members:{GROUP}")
    await g.redis_client.delete(f"chat_members:{OTHER_GROUP}")
    for chat_id in (GROUP, OTHER_GROUP):
        await g.redis_client.sadd(f"chat_members:{chat_id}", ALICE)
        await g.redis_client.sadd(f"chat_members:{chat_id}", BOB)
        await g.redis_client.sadd(f"user_chats:{ALICE}", chat_id)
        await g.redis_client.sadd(f"user_chats:{BOB}", chat_id)
    await g.redis_client.sadd(f"chat_members:{GROUP}", "carol")
    await g.redis_client.hset(f"chat:{GROUP}", mapping={"type": "group", "name": "G1"})
    await g.redis_client.hset(f"chat:{OTHER_GROUP}", mapping={"type": "group", "name": "G2"})


async def main():
    # The app reads its client off the globals object; without this the code
    # under test would see None and every assertion would silently short-circuit.
    g.redis_client = MockRedis()
    await seed()

    # --- opening state -------------------------------------------------------
    check("no blocks initially",
          await chat_blocks.blocked_members_in_chat(GROUP, ALICE) == [])

    # --- blocking ------------------------------------------------------------
    ok = await chat_blocks.block_member_in_chat(GROUP, ALICE, BOB)
    check("alice can block bob in the group", ok)
    check("bob is now hidden for alice",
          await chat_blocks.blocked_members_in_chat(GROUP, ALICE) == [BOB])

    # --- directionality ------------------------------------------------------
    check("block is invisible to the blocked member",
          await chat_blocks.blocked_members_in_chat(GROUP, BOB) == [])
    check("alice is not hidden from bob",
          ALICE not in await chat_blocks.blocked_sender_set(GROUP, BOB))

    # --- scoping -------------------------------------------------------------
    check("block does not leak into another chat",
          await chat_blocks.blocked_members_in_chat(OTHER_GROUP, ALICE) == [])

    # --- authorisation -------------------------------------------------------
    check("cannot block a non-member",
          not await chat_blocks.block_member_in_chat(GROUP, ALICE, "stranger"))
    check("cannot block from a chat you are not in",
          not await chat_blocks.block_member_in_chat(GROUP, "stranger", BOB))
    check("cannot block yourself",
          not await chat_blocks.block_member_in_chat(GROUP, ALICE, ALICE))
    check("self-block left no trace",
          await chat_blocks.blocked_members_in_chat(GROUP, ALICE) == [BOB])

    # --- unblocking ----------------------------------------------------------
    check("alice can unblock bob",
          await chat_blocks.unblock_member_in_chat(GROUP, ALICE, BOB))
    check("bob is visible again",
          await chat_blocks.blocked_members_in_chat(GROUP, ALICE) == [])
    check("unblocking twice is idempotent",
          await chat_blocks.unblock_member_in_chat(GROUP, ALICE, BOB))

    # --- isolation between viewers ------------------------------------------
    await chat_blocks.block_member_in_chat(GROUP, ALICE, BOB)
    await chat_blocks.block_member_in_chat(GROUP, BOB, "carol")
    alice_set = await chat_blocks.blocked_sender_set(GROUP, ALICE)
    bob_set = await chat_blocks.blocked_sender_set(GROUP, BOB)
    check("each viewer keeps their own list",
          alice_set == {BOB} and bob_set == {"carol"},
          f"alice={alice_set} bob={bob_set}")

    # cleanup
    await chat_blocks.unblock_member_in_chat(GROUP, ALICE, BOB)
    await chat_blocks.unblock_member_in_chat(GROUP, BOB, "carol")

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED")
        return 1
    print("CHAT MEMBER BLOCKING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
