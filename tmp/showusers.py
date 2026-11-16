import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "backend/app/users/handlers.py", encoding="utf-8").read().splitlines()

print("===== functions =====")
for i, l in enumerate(lines):
    if "async def " in l:
        print("%6d| %s" % (i + 1, l.strip()))

print("\n===== lines 100-185 =====")
for i in range(99, min(185, len(lines))):
    print("%6d| %s" % (i + 1, lines[i]))
