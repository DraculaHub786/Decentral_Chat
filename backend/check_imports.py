import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def imports(rel_path):
    p = BASE_DIR / rel_path
    print('###', rel_path)
    if p.exists():
        for i, l in enumerate(p.read_text(encoding='utf-8').split('\n')):
            if 'import' in l:
                print(f'{i+1:4}: {l}')
    else:
        print(f'File not found: {p}')
    print()

imports('app/files/handlers.py')
imports('app/files/converters/service.py')

h_path = BASE_DIR / 'app/files/handlers.py'
if h_path.exists():
    h = h_path.read_text(encoding='utf-8')
    print('handlers uses get_user_from_token:', 'get_user_from_token' in h)
    print('handlers imports get_user_from_token:', 'get_user_from_token' in h and 'tokens' in h)
