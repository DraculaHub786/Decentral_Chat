for f in ['app/files/handlers.py', 'app/files/converters/service.py',
          'app/files/converters/images.py', 'app/files/converters/documents.py',
          'app/files/converters/audio.py', 'app/files/converters/video.py']:
    print('###', f)
    for l in open(f, encoding='utf-8').read().split('\n'):
        if 'import' in l and ('converter' in l or 'service' in l or 'from app.files' in l or 'handlers' in l):
            print('   ', l.strip())
