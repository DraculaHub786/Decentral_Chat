import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "backend/app/messages/handlers.py", encoding="utf-8").read().splitlines()
for i in range(98, 235):
    if i < len(lines):
        print("%5d| %s" % (i + 1, lines[i]))
