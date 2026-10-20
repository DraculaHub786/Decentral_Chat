from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
files = [
    'app/files/handlers.py',
    'app/files/converters/service.py',
    'app/files/converters/images.py',
    'app/files/converters/documents.py',
]

for f in files:
    p = BASE_DIR / f
    if p.exists():
        print(f'OK: {f}')
    else:
        print(f'Missing: {f}')
