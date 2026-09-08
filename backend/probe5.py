for f in ['app/files/handlers.py', 'app/files/converters/service.py']:
    print('###', f)
    lines = open(f, encoding='utf-8').read().split('\n')
    for i in range(9, 29):
        print(f'{i+1:4}: {lines[i]}')
