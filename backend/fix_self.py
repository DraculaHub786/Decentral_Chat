import re

def fix(path):
    s = open(path, encoding='utf-8').read()
    orig = s

    # 1) Drop `self` from method/function defs: `name(self,` -> `name(`
    s = re.sub(r'def\s+(\w+)\(self(,\s*|\s*\))', r'def \1(\2', s)

    # 2) Replace self.<attr> / self.<method> references
    repl = {
        'self.get_user_from_token': 'get_user_from_token',
        'self._check_upload_rate_limit': '_check_upload_rate_limit',
        'self.get_file_type': 'get_file_type',
        'self.generate_thumbnail': 'generate_thumbnail',
        'self.convert_image_format': 'convert_image_format',
        'self.convert_video_format': 'convert_video_format',
        'self.convert_audio_format': 'convert_audio_format',
        'self.convert_document_format': 'convert_document_format',
        'self.get_supported_conversions': 'get_supported_conversions',
        'self.db': 'g.db',
        'self.firebase': 'g.firebase',
    }
    for k, v in repl.items():
        s = s.replace(k, v)

    if s != orig:
        open(path, 'w', encoding='utf-8').write(s)
    # Report remaining
    rem = [(i+1, l) for i, l in enumerate(s.split('\n')) if 'self.' in l or re.search(r'def\s+\w+\(self', l)]
    print(path, '-> remaining self usages:', len(rem))
    for ln, l in rem:
        print(f'  {ln}: {l}')

for f in ['app/files/converters/service.py', 'app/files/handlers.py']:
    fix(f)
