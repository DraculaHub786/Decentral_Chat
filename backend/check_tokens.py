import re
# tokens.py definitions
s = open('app/auth/tokens.py', encoding='utf-8').read()
print('tokens.py defs:', [l.strip() for l in s.split('\n') if re.match(r'\s*(async\s+)?def get_user_from_token', l)])
# how chats/handlers imports it
c = open('app/chats/handlers.py', encoding='utf-8').read()
for l in c.split('\n'):
    if 'get_user_from_token' in l and ('import' in l):
        print('chats import:', l.strip())
