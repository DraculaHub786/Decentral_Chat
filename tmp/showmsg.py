import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "backend/app/messages/handlers.py", encoding="utf-8").read().splitlines()

print("=== functions ===")
for i, l in enumerate(lines):
    if "async def " in l:
        print("%5d| %s" % (i + 1, l.strip()))

start = None
for i, l in enumerate(lines):
    if "async def get_messages" in l:
        start = i
        break
if start is not None:
    print("\n=== get_messages ===")
    for i in range(start, min(start + 70, len(lines))):
        print("%5d| %s" % (i + 1, lines[i]))
