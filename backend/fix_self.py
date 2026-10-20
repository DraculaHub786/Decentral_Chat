import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def fix(rel_path):
    p = BASE_DIR / rel_path
    if not p.exists():
        print(f'Not found: {p}')
        return
    s = p.read_text(encoding='utf-8')
    orig = s

    # Drop self from method/function defs: name(self, -> name(
    s = re.sub(r'def\s+(\w+)\(\s*self\s*,\s*', r'def \1(', s)
    s = re.sub(r'def\s+(\w+)\(\s*self\s*\)', r'def \1()', s)

    if s != orig:
        p.write_text(s, encoding='utf-8')
        print(f'Fixed: {rel_path}')
    else:
        print(f'No changes: {rel_path}')

if __name__ == '__main__':
    fix('app/files/converters/service.py')
