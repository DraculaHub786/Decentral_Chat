import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "backend/app/chats/handlers.py", encoding="utf-8").read().splitlines()

print("=== head (1-28) ===")
for i in range(0, min(28, len(lines))):
    print("%5d| %s" % (i + 1, lines[i]))

print("\n=== functions ===")
for i, l in enumerate(lines):
    if "async def " in l:
        print("%5d| %s" % (i + 1, l.strip()))

print("\n=== tail (last 30) ===")
for i in range(max(0, len(lines) - 30), len(lines)):
    print("%5d| %s" % (i + 1, lines[i]))

print("\ntotal lines:", len(lines))
