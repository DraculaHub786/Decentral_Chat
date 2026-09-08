import re, glob

def scan(pattern, root):
    for f in glob.glob(root + '/**/*.py', recursive=True):
        try:
            txt = open(f, encoding='utf-8').read()
        except Exception:
            continue
        for i, l in enumerate(txt.split('\n')):
            if re.search(pattern, l):
                print(f"{f}:{i+1}: {l.strip()}")

print("=== generate_token callers ===")
scan(r'generate_token\(', 'app')
print("\n=== get_user_from_token callers ===")
scan(r'get_user_from_token\(', 'app')
print("\n=== class definitions with def methods (self) ===")
scan(r'^\s*async def \w+\(self', 'app')
print("\n=== g.db assignments in firebase_client ===")
for f in ['app/core/firebase_client.py', 'app/globals.py']:
    try:
        for i,l in enumerate(open(f, encoding='utf-8').read().split('\n')):
            if 'g.db' in l or 'def init_firebase' in l:
                print(f"{f}:{i+1}: {l.strip()}")
    except Exception as e:
        print(e)
