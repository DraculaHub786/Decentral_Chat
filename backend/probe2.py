import re, glob

files = [
    'app/files/converters/service.py',
    'app/files/converters/images.py',
    'app/files/converters/documents.py',
    'app/files/converters/audio.py',
    'app/files/converters/video.py',
    'app/files/handlers.py',
]
for f in files:
    print('='*70)
    print(f)
    print('='*70)
    lines = open(f, encoding='utf-8').read().split('\n')
    in_class = False
    for i, l in enumerate(lines):
        if re.search(r'\bself\b', l):
            print(f"{i+1:4}: {l}")
    # detect class defs
    classes = [i+1 for i,l in enumerate(lines) if re.match(r'^\s*class ', l)]
    if classes:
        print('CLASSES at lines:', classes)
