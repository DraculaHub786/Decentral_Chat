"""Check frontend/app.js for syntax errors and leftover v1 references."""
import re
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
app_js = root / "frontend" / "app.js"
text = app_js.read_text(encoding="utf-8", errors="replace")

# 1. Syntax check via node if available.
node = shutil.which("node")
if node:
    result = subprocess.run([node, "--check", str(app_js)],
                            capture_output=True, text=True)
    print("node --check:", "OK" if result.returncode == 0 else "FAILED")
    if result.returncode != 0:
        print(result.stderr[:2000])
else:
    print("node not found; skipping syntax check")

# 2. Leftover v1 endpoint usage.
print("\nleftover v1 references:")
for needle in ("files/convert`", "files/convert?", "conversion-formats",
               "conversion-progress", "__converted"):
    hits = [i for i, line in enumerate(text.splitlines(), 1) if needle in line]
    print(f"  {needle:24s} -> {len(hits)} hit(s) {hits[:6]}")

# 3. New v2 wiring present.
print("\nv2 wiring present:")
for needle in ("files/capabilities", "files/formats", "files/jobs",
               "result?token=", "CryptoEngine.encryptBuffer"):
    print(f"  {needle:26s} -> {text.count(needle)} occurrence(s)")
