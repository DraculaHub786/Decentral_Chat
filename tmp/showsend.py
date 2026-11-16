import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "frontend/app.js", encoding="utf-8").read().splitlines()


def show(start, end, label):
    print("\n===== %s (lines %d-%d) =====" % (label, start, end))
    for i in range(max(0, start - 1), min(end, len(lines))):
        print("%6d| %s" % (i + 1, lines[i]))


show(922, 955, "encryptBuffer tail + decryptBuffer")
show(3500, 3570, "sendMessage encryption")
show(3960, 4040, "attachment encrypt/upload")
