import urllib.request, urllib.error, json, uuid, time

BASE = 'http://localhost:8080/api'

def req(url, method='GET', data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(f'{BASE}{url}', data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw) if raw else {'error': str(e)}

def run_integration_tests():
    uid_suffix = uuid.uuid4().hex[:6]
    user_a = f'testuser_a_{uid_suffix}'
    user_b = f'testuser_b_{uid_suffix}'
    pwd = 'Password123!'

    print('--- 1. Testing Registration ---')
    s, r = req('/auth/register', 'POST', {'username': user_a, 'password': pwd, 'email': f'{user_a}@test.com'})
    print(f'Register {user_a}: status={s}, success={r.get("success")}')
    token_a = r.get('token')
    id_a = r.get('user', {}).get('id')

    s, r = req('/auth/register', 'POST', {'username': user_b, 'password': pwd, 'email': f'{user_b}@test.com'})
    print(f'Register {user_b}: status={s}, success={r.get("success")}')
    token_b = r.get('token')
    id_b = r.get('user', {}).get('id')

    print('--- 2. Testing Login ---')
    s, r = req('/auth/login', 'POST', {'username': user_a, 'password': pwd})
    print(f'Login {user_a}: status={s}, success={r.get("success")}, has_refresh={bool(r.get("refresh_token"))}')

    print('--- 3. Testing Contacts & Blocking ---')
    s, r = req('/contacts', 'POST', {'identifier': user_b}, token=token_a)
    print(f'Add contact {user_b}: status={s}, success={r.get("success")}')

    s, r = req('/users/block', 'POST', {'user_id': id_b}, token=token_a)
    print(f'Block user B: status={s}, success={r.get("success")}')

    s, r = req(f'/users/{id_b}/blocked-status', 'GET', token=token_a)
    print(f'Check blocked status: status={s}, is_blocked={r.get("is_blocked")}, blocked_by_you={r.get("blocked_by_you")}')

    # Try call while blocked
    s, r = req('/calls/initiate', 'POST', {'recipient_id': id_b, 'type': 'audio'}, token=token_a)
    print(f'Call while blocked: status={s} (expect 403), error={r.get("error")}')

    s, r = req('/users/unblock', 'POST', {'user_id': id_b}, token=token_a)
    print(f'Unblock user B: status={s}, success={r.get("success")}')

    print('--- 4. Testing Chat & Messages ---')
    s, r = req('/chats', 'POST', {'participants': [id_b], 'type': 'direct'}, token=token_a)
    chat_id = r.get('chat_id') or r.get('chat', {}).get('id')
    print(f'Create direct chat: status={s}, chat_id={chat_id}')

    if chat_id:
        # Send unencrypted message
        s, r = req(f'/chats/{chat_id}/messages', 'POST', {'content': 'Hello unencrypted message', 'encrypted': False, 'message_type': 'text'}, token=token_a)
        print(f'Send plaintext message: status={s}, success={r.get("success")}')

        # Send encrypted message
        s, r = req(f'/chats/{chat_id}/messages', 'POST', {'content': 'U2FsdGVkX1+vupppZksvRf5pq5g=', 'encrypted': True, 'message_type': 'text'}, token=token_a)
        print(f'Send encrypted message: status={s}, success={r.get("success")}')

        # Load messages
        s, r = req(f'/chats/{chat_id}/messages?limit=20', 'GET', token=token_b)
        msgs = r.get('messages', [])
        print(f'User B load messages: status={s}, count={len(msgs)}')
        for m in msgs:
            print(f'  Msg ID: {m.get("id")}, encrypted={m.get("encrypted")}, content="{m.get("content")}"')

    print('--- 5. Testing Calls ---')
    s, r = req('/calls/initiate', 'POST', {'recipient_id': id_b, 'type': 'audio'}, token=token_a)
    print(f'Initiate call: status={s}, call_id={r.get("call", {}).get("id")}')
    call_id = r.get('call', {}).get('id')
    if call_id:
        s, r = req(f'/calls/{call_id}/signal', 'POST', {'signal': {'type': 'offer', 'sdp': 'dummy_sdp'}}, token=token_a)
        print(f'Send signal: status={s}, success={r.get("success")}')
        s, r = req(f'/calls/{call_id}/end', 'POST', {}, token=token_a)
        print(f'End call: status={s}, success={r.get("success")}')

    print('--- 6. Testing Conversion Formats ---')
    s, r = req('/files/conversion-formats', 'GET')
    print(f'Conversion formats: status={s}, categories={list(r.keys())}')


if __name__ == '__main__':
    run_integration_tests()
