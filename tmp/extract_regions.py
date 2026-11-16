import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
js_lines = io.open(ROOT / "frontend/app.js", encoding="utf-8").read().splitlines()


def show(start, end, label):
    print(f"\n===== {label} (lines {start}-{end}) =====")
    for i in range(max(0, start - 1), min(end, len(js_lines))):
        print(f"{i+1:6}| {js_lines[i]}")


joined = "\n".join(js_lines)


def find_line(pattern):
    m = re.search(pattern, joined)
    if not m:
        return None
    return joined[:m.start()].count("\n") + 1


ln = find_line(r"function createChatCardElement\s*\(")
if ln:
    show(ln, ln + 55, "H3 createChatCardElement")

show(2855, 2900, "H2 updateChatPreviewInList")
show(8566, 8620, "H2 deleteMessageForMe")

ln = find_line(r"async function blockUserFromChat\s*\(")
if ln:
    show(ln, ln + 60, "C3 blockUserFromChat")

show(1878, 1912, "C1 setupChatKey on direct chat open")

ln = find_line(r"async function renderChats\s*\(")
if ln:
    show(ln, ln + 40, "H3 renderChats")
