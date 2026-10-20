from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
for f in ['app/files/converters/service.py', 'app/files/handlers.py']:
    p = BASE_DIR / f
    print('###', f)
    if p.exists():
        lines = p.read_text(encoding='utf-8').split('\n')
        print(f'Lines: {len(lines)}')
    else:
        print('Missing')
