import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = io.open(ROOT / "frontend/app.js", encoding="utf-8").read().splitlines()


def show(start, end, label):
    print("\n===== %s =====" % label)
    for i in range(max(0, start - 1), min(end, len(lines))):
        print("%6d| %s" % (i + 1, lines[i]))


show(1025, 1055, "init call 1")
show(2180, 2205, "init call 2")
show(2740, 2765, "init call 3")
show(8245, 8275, "init call 4")

print("\n=== uploadPublicKey call sites ===")
for i, l in enumerate(lines):
    if "uploadPublicKey" in l:
        print("%6d| %s" % (i + 1, l.strip()))

print("\n=== CryptoEngine.init() call sites (exhaustive) ===")
for i, l in enumerate(lines):
    if "CryptoEngine.init" in l:
        print("%6d| %s" % (i + 1, l.strip()))
