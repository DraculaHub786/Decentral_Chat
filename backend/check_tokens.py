import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# tokens.py definitions
t_path = BASE_DIR / 'app/auth/tokens.py'
if t_path.exists():
    s = t_path.read_text(encoding='utf-8')
    print('tokens.py defs:', [l.strip() for l in s.split('\n') if re.match(r'\s*(async\s+)?def get_user_from_token', l)])

# how chats/handlers imports it
c_path = BASE_DIR / 'app/chats/handlers.py'
if c_path.exists():
    c = c_path.read_text(encoding='utf-8')
    for l in c.split('\n'):
        if 'get_user_from_token' in l and ('import' in l):
            print('chats import:', l.strip())
