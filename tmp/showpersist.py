import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = io.open(ROOT / "frontend/app.js", encoding="utf-8").read()
lines = src.splitlines()


def show_fn(name):
    m = re.search(r"\n\s+(?:async\s+)?" + name + r"\s*\([^)]*\)\s*\{", src)
    if not m:
        print("NOT FOUND:", name)
        return
    start = m.start() + 1
    start_line = src[:start].count("\n")
    i = src.index("{", start)
    depth = 1
    j = i + 1
    while j < len(src) and depth:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    end_line = src[:j].count("\n")
    print("\n===== %s (lines %d-%d) =====" % (name, start_line + 1, end_line + 1))
    for k in range(start_line, end_line + 1):
        print("%6d| %s" % (k + 1, lines[k]))


for fn in ("persistChatKey", "loadStoredChatKeys", "hasKey"):
    show_fn(fn)

print("\n===== persistChatKey call sites =====")
for i, l in enumerate(lines):
    if "persistChatKey" in l:
        print("%6d| %s" % (i + 1, l.strip()))

print("\n===== encryptText call sites =====")
for i, l in enumerate(lines):
    if "encryptText" in l:
        print("%6d| %s" % (i + 1, l.strip()))
