"""Real state: registry availability, sidebar render, progress, delete-for-me."""
import io
import re
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def engines():
    print("=== Real engine availability (registry) ===")
    from app.files.converters import registry, routes_table
    for name, spec in registry.ENGINES.items():
        print(f"  {name:12} available={spec.available!s:5} binary={spec.binary}")

    caps = routes_table.capabilities()
    total = len(caps["routes"])
    avail = sum(1 for r in caps["routes"] if r["available"])
    print(f"\n  routes: {avail}/{total} available")
    by_eng = Counter()
    for r in caps["routes"]:
        if r["available"] and r["active_engine"]:
            by_eng[r["active_engine"]] += 1
    print("  available routes per engine:", dict(by_eng))
    dead = [r for r in caps["routes"] if not r["available"]]
    if dead:
        print("  unavailable route engine chains:", dict(Counter(
            tuple(r["engines"]) for r in dead)))


def sidebar():
    print("\n=== H3: sidebar / chat list render ===")
    js = io.open(ROOT / "frontend/app.js", encoding="utf-8").read()
    for m in re.finditer(r"function\s+(\w*[Cc]hat\w*)\s*\(", js):
        line = js[:m.start()].count("\n") + 1
        print(f"  line {line}: {m.group(1)}")
    for kw in ("chat-item", "chatListItem", "chatsList", "chat-list"):
        hits = [js[:m.start()].count("\n") + 1 for m in re.finditer(re.escape(kw), js)]
        print(f"  '{kw}': lines {hits[:8]}")


def delete_for_me():
    print("\n=== H2: delete for me ===")
    js = io.open(ROOT / "frontend/app.js", encoding="utf-8").read()
    m = re.search(r"async function deleteMessageForMe\s*\([^)]*\)\s*\{", js)
    if not m:
        print("  not found")
        return
    start = m.end()
    depth = 1
    i = start
    while i < len(js) and depth:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    body = js[m.start():i]
    line = js[:m.start()].count("\n") + 1
    print(f"  deleteMessageForMe at line {line}, {body.count(chr(10))} lines")
    for ln in body.splitlines():
        s = ln.strip()
        if any(k in s for k in ("last_message", "preview", "renderChat",
                                "chatList", "updateChatList", "lastMessage")):
            print("    ->", s[:100])


def progress():
    print("\n=== H4: progress ===")
    jobs = io.open(ROOT / "backend/app/files/converters/jobs.py", encoding="utf-8").read()
    for m in re.finditer(r"percent", jobs):
        line = jobs[:m.start()].count("\n") + 1
        seg = jobs[max(0, m.start() - 60):m.start() + 60].replace("\n", " ")
        print(f"  jobs line {line}: ...{seg.strip()[:110]}...")
    disp = io.open(ROOT / "backend/app/files/converters/dispatch.py", encoding="utf-8").read()
    print("\n  dispatch.py mentions progress:", "progress" in disp)
    combined = disp + jobs
    for m in re.finditer(r"def (\w*progress\w*)\s*\(", combined):
        print("   def", m.group(1))


engines()
sidebar()
delete_for_me()
progress()
