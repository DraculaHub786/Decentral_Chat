for f in ['app/files/converters/service.py', 'app/files/handlers.py']:
    print('###', f)
    lines = open(f, encoding='utf-8').read().split('\n')
    for i, l in enumerate(lines):
        if 'self.' in l or 'def ' in l and '(self' in l:
            print(f'{i+1:4}: {l}')
