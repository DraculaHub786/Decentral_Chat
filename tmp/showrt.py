import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "backend/app/files/converters/routes_table.py", encoding="utf-8").read().splitlines()

print("===== functions =====")
for i, l in enumerate(lines):
    if l.startswith("def "):
        print("%6d| %s" % (i + 1, l.strip()))

print("\n===== capabilities() and tail =====")
start = None
for i, l in enumerate(lines):
    if l.startswith("def capabilities"):
        start = i
        break
if start is not None:
    for i in range(start, min(start + 45, len(lines))):
        print("%6d| %s" % (i + 1, lines[i]))

print("\n===== queue.py public API =====")
ql = io.open(ROOT / "backend/app/files/converters/queue.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(ql):
    s = l.strip()
    if s.startswith("def ") or s.startswith("async def ") or s.startswith("class "):
        print("%6d| %s" % (i + 1, s))
