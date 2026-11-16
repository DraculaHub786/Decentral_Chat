import io

path = "Decentral_Chat \u2014 Todo.md"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

lines = text.splitlines()
print("LINES=", len(lines))
print("CHARS=", len(text))
for index, line in enumerate(lines):
    if line.startswith("## ") or line.startswith("### "):
        print(index + 1, line)
