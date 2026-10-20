from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
files = [
    'app/files/converters/service.py',
    'app/files/converters/images.py',
    'app/files/converters/documents.py',
    'app/files/converters/audio.py',
    'app/files/converters/video.py',
]

for f in files:
    p = BASE_DIR / f
    if p.exists():
        print(f'OK: {f} ({p.stat().st_size} bytes)')
    else:
        print(f'Missing: {f}')
