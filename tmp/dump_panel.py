import io

js = io.open("frontend/app.js", encoding="utf-8").read().splitlines()

for needle in ("function showConversionPanel", "function hideConversionPanel",
               "function addFilePreview", "function handleFileSelect"):
    for i, line in enumerate(js):
        if needle in line:
            print("--- %s @ %d ---" % (needle, i + 1))
            start = max(0, i - 2)
            for j in range(start, min(i + 40, len(js))):
                print(j + 1, js[j])
            print()
            break
    else:
        print("--- %s NOT FOUND ---\n" % needle)
