import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
js = io.open(ROOT / "frontend/app.js", encoding="utf-8").read()
lines = js.splitlines()

m = re.search(r"(async\s+)?function\s+(showGroupMembers|viewGroupMembers|openGroupMembers)\w*\s*\(", js)
if m:
    start = js[:m.start()].count("\n")
    print("=== group members renderer at line %d ===" % (start + 1))
    for i in range(start, min(start + 60, len(lines))):
        print("%6d| %s" % (i + 1, lines[i]))
else:
    print("renderer not found; searching references")
    for i, l in enumerate(lines):
        if "groupMembersList" in l or "groupMembersModal" in l:
            print("%6d| %s" % (i + 1, l.strip()))
