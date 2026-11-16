import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "frontend/app.js", encoding="utf-8").read().splitlines()
for i in range(724, 800):
    if i < len(lines):
        print("%6d| %s" % (i + 1, lines[i]))
