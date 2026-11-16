import io

path = "frontend/app.js"
lines = io.open(path, encoding="utf-8").read().splitlines()
print("TOTAL LINES:", len(lines))
start, end = 2940, 3200
for i in range(start, min(end, len(lines))):
    print(i + 1, lines[i])
