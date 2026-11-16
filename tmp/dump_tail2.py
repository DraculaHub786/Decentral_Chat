import io

js = io.open("frontend/app.js", encoding="utf-8").read().splitlines()
for j in range(3199, 3275):
    print(j + 1, js[j])
print("\n=== panel format load ===")
for j in range(3312, 3418):
    print(j + 1, js[j])
