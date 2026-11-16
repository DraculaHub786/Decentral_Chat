import io

js = io.open("frontend/app.js", encoding="utf-8").read().splitlines()
print("=== LOCAL_CONVERSION_MAP ===")
for i, line in enumerate(js):
    if "LOCAL_CONVERSION_MAP" in line and "=" in line:
        print("found at line", i + 1)
        for j in range(i, min(i + 55, len(js))):
            print(j + 1, js[j])
        break

html = io.open("frontend/index.html", encoding="utf-8").read().splitlines()
print("\n=== CONVERT MODAL (index.html) ===")
hits = [i for i, l in enumerate(html)
        if "targetFormatSelect" in l or "conversionProgress" in l or "convertFileBtn" in l]
print("marker lines:", [h + 1 for h in hits])
if hits:
    start = max(0, hits[0] - 35)
    for j in range(start, min(hits[-1] + 25, len(html))):
        print(j + 1, html[j])
