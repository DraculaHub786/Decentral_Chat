import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ch = io.open(ROOT / "backend/app/chats/handlers.py", encoding="utf-8").read()
lines = ch.splitlines()

print("=== get_chats ===")
start = None
for i, l in enumerate(lines):
    if "async def get_chats" in l:
        start = i
        break
if start is not None:
    for i in range(start, min(start + 95, len(lines))):
        print("%5d| %s" % (i + 1, lines[i]))
else:
    print("NOT FOUND")

print("\n=== avatar mentions in chats handler ===")
for i, l in enumerate(lines):
    if "avatar" in l.lower():
        print("%5d| %s" % (i + 1, l.strip()))
