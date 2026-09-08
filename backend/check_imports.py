import re

def imports(path):
    print('###', path)
    for i, l in enumerate(open(path, encoding='utf-8').read().split('\n')):
        if 'import' in l:
            print(f'{i+1:4}: {l}')
    print()

imports('app/files/handlers.py')
imports('app/files/converters/service.py')

# Check for get_user_from_token usage without import
h = open('app/files/handlers.py', encoding='utf-8').read()
print('handlers uses get_user_from_token:', 'get_user_from_token' in h)
print('handlers imports get_user_from_token:', 'from app.auth.tokens import' in h and 'get_user_from_token' in h)
