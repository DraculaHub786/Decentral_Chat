# DecentralChat — Security Audit Report

> **Audit Date:** 2026-07-26  
> **Scope:** `backend/server.py`, `frontend/index.html`

---

## 🔴 CRITICAL VULNERABILITIES

### 1. JWT Secret Key Exposure (Backdoor)

**File:** `backend/server.py`, line 35
```python
SECRET_KEY = os.getenv('SECRET_KEY', Fernet.generate_key().decode())
```

If the `SECRET_KEY` env var is **not** set, a **new random key is generated on every server restart**. This means:
- All existing JWT tokens are instantly **invalidated** after a restart.
- No persistent signing key → token forgery is trivially possible if an attacker can restart the server.

Also, the JWT algorithm is **never validated** — the code does not enforce `algorithms=['HS256']` at every decode call (only at `get_user_from_token`). The `refresh_token` handler re-encodes with the same weakness.

### 2. Fernet Encryption Key Mismanagement

**File:** `backend/server.py`, line 55
```python
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', Fernet.generate_key())
cipher_suite = Fernet(ENCRYPTION_KEY if isinstance(ENCRYPTION_KEY, bytes) else ENCRYPTION_KEY.encode())
```

Same problem: no env var → random key each restart. All encrypted message content becomes **permanently undecryptable** after restart.

### 3. Server-Side Request Forgery (SSRF) via File Conversion

**File:** `backend/server.py`, `convert_uploaded_file` + `get_file`

The system accepts file paths from Firestore/Redis (`file_meta['path']`) and opens them:
```python
source_path = Path(file_meta['path'])
```
If an attacker can poison the `path` field in Firestore or Redis, they could point it to:
- `/etc/passwd`
- `C:\Windows\System32\config\SAM`
- Any UNC path (`\\attacker-server\malicious`)

**Impact:** Full server file read / write.

---

## 🟠 HIGH-RISK VULNERABILITIES

### 4. Arbitrary File Upload — No Content-Type Validation

**File:** `backend/server.py`, `upload_file`

The code checks only the **file extension**:
```python
ext = filename.rsplit('.', 1)[-1].lower()
file_type = self.get_file_type(ext)
```

An attacker can:
- Upload a `.txt` file that is actually a **PHP/ASP shell**
- Upload a `.jpg` that is actually a **JavaScript/HTML file** (polyglot)
- The file is stored in `uploads/` and served at `/api/uploads/...` with no MIME-type sanitisation

**Impact:** Stored XSS, remote code execution if any server-side include feature is added later.

### 5. Path Traversal in File Upload

**File:** `backend/server.py` lines ~1600–1650

```python
file_path = UPLOAD_DIR / subdir / f"{file_id}.{ext}"
```

`file_id` is a UUID (safe), but `ext` comes from user-supplied filename. While only lowercase is stored, if an attacker can inject a path separator via extension (e.g. `../../evil.exe`), it could traverse directories.

**Current mitigation:** Only the part after the last `.` is used, so `../../evil.exe.txt` saves as `.txt`. But relying on extension alone is fragile.

### 6. No Rate Limiting on Auth Endpoints

**File:** `backend/server.py`, `handle_register` and `handle_login`

- No CAPTCHA
- No IP-based rate limiting
- No account lockout after N failed attempts
- An attacker can brute-force passwords indefinitely at full speed
- An attacker can exhaust server resources by registering thousands of accounts

### 7. Password Policy Bypass

**File:** `backend/server.py`, `handle_register`

```python
if not password or len(password) < 6:
    return web.json_response({"error": "Password must be at least 6 characters"})
```

- Minimum is only **6 characters** — well below any modern standard (OWASP recommends 8+ with complexity)
- No check for common passwords (`password123`, `qwerty`, etc.)
- No check for password == username

### 8. WebSocket Message Injection — No Server-Side Validation

**File:** `backend/server.py`, `websocket_handler`

The WebSocket handler processes arbitrary JSON from clients. Specifically:
```python
elif data.get('type') == 'message':
    chat_id = data.get('chat_id')
    content = data.get('content', '')
```

- No maximum message length enforced
- No content sanitisation
- An attacker can send unlimited `typing` events to flood other users

### 9. Missing CSRF Protection

All POST/PUT/DELETE endpoints rely **only** on the `Authorization: Bearer <token>` header. There is:
- No CSRF token
- No origin/referer validation
- If an attacker can XSS any same-origin page, they can forge authenticated requests

---

## 🟡 MEDIUM-RISK VULNERABILITIES

### 10. Information Leakage via Debug Endpoints

**File:** `backend/server.py`, routes:
```
/api/debug/check-user/{username}
/api/debug/redis/{username}
/api/debug/my-chats
```

These endpoints exist in **production** with minimal access control. They leak:
- Username availability
- Redis internal state
- User chat lists with member IDs

### 11. Session Token in URL / Logs

```python
logger.info(f"📥 Registration data keys: {data.keys()}")
logger.info(f"📝 Parsed values - username: '{username}', email: '{email}'")
```

Passwords are not logged (good), but token-bearing URLs could be logged elsewhere. Sensitive data in logs is a compliance issue (GDPR, etc.).

### 12. No Helmet/Security Headers

The server sets **no security headers**:
- No `Content-Security-Policy`
- No `X-Content-Type-Options: nosniff`
- No `X-Frame-Options: DENY`
- No `Strict-Transport-Security` (though this is HTTP-only anyway)
- No `X-XSS-Protection`

### 13. MockRedis Fallback — No Auth

**File:** `backend/server.py`, `MockRedis` class

When Redis is unavailable, the server falls back to `MockRedis` — an in-memory dictionary with **zero access control**. If Redis goes down, any authenticated user can potentially read/write any other user's data via race conditions or injection into the mock store.

### 14. Static File Serving Without Restrictions

```python
self.app.router.add_static('/api/uploads/', path=str(UPLOAD_DIR))
```

The entire `uploads/` directory is served at `/api/uploads/` with **no authentication**. Anyone who knows a file ID can:
- Download any file
- Enumerate files if IDs are guessable
- Access files from chats they are not part of

### 15. Firestore Data Inconsistency After Restart

The `preload_critical_data_from_firestore()` method loads user data into MockRedis on restart. If MockRedis is in use, any changes made during a session are **lost** on restart (no persistence). This can lead to:
- Phantom users appearing
- Lost messages
- Inconsistent chat membership states

---

## 🔵 LOW-RISK / INFORMATIONAL

### 16. Weak Randomness for OTP

```python
otp = ''.join(random.choices(string.digits, k=6))
```

Uses `random` (Mersenne Twister, **not** cryptographically secure) instead of `secrets`. OTP codes can be predicted if an attacker can sample a few values.

### 17. UUID v4 for Session IDs — Predictable Under Some Conditions

`uuid.uuid4()` uses `os.urandom()` (secure), but message IDs, call IDs, and file IDs are all UUIDs. If an attacker can observe a sequence, they can enumerate resources.

### 18. No Token Expiry Enforcement

```python
payload = {
    'user_id': user_id,
    'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30),
}
```

Tokens are valid for **30 days** with no refresh-token rotation. If a token leaks, the attacker has a month of access.

---

## 📋 SUMMARY TABLE

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| 1 | 🔴 CRITICAL | JWT secret key lost on restart | Unresolved |
| 2 | 🔴 CRITICAL | Fernet encryption key lost on restart | Unresolved |
| 3 | 🔴 CRITICAL | SSRF via file path in Firestore | Unresolved |
| 4 | 🟠 HIGH | Arbitrary file upload (no content validation) | Unresolved |
| 5 | 🟠 HIGH | Path traversal via file extension | Partially mitigated |
| 6 | 🟠 HIGH | No rate limiting on auth | Unresolved |
| 7 | 🟠 HIGH | Weak password policy (6 chars) | Unresolved |
| 8 | 🟠 HIGH | WebSocket message injection | Unresolved |
| 9 | 🟠 HIGH | Missing CSRF protection | Unresolved |
| 10 | 🟡 MEDIUM | Debug endpoints exposed in production | Unresolved |
| 11 | 🟡 MEDIUM | Sensitive data in logs | Unresolved |
| 12 | 🟡 MEDIUM | Missing security headers | Unresolved |
| 13 | 🟡 MEDIUM | MockRedis with no access control | Unresolved |
| 14 | 🟡 MEDIUM | Unauthenticated file access | Unresolved |
| 15 | 🟡 MEDIUM | Data inconsistency with MockRedis | Unresolved |
| 16 | 🔵 LOW | Predictable OTP (not using `secrets`) | Unresolved |
| 17 | 🔵 LOW | Resource enumeration via UUIDs | Informational |
| 18 | 🔵 LOW | 30-day token expiry with no rotation | Unresolved |

---

## ✅ REMEDIATION PRIORITIES

### Immediate (P0)

1. **Make JWT/Fernet keys persistent** — Generate once, store in `.env`, read from file on disk if env var absent.
2. **Remove debug endpoints** from production or gate behind an admin-only role.
3. **Sanitise file paths** — Validate that `file_meta['path']` is within `UPLOAD_DIR` using `Path.resolve()`.

### Short-term (P1)

4. **Add rate limiting** — Use an in-memory counter per IP per endpoint (e.g. 5 attempts/min for login).
5. **Enforce password policy** — Minimum 8 chars, require uppercase + digit, check against common password list.
6. **Add Content-Type validation** on file upload — Reject files whose magic bytes don't match their claimed extension.
7. **Add CSRF protection** — Validate `Origin` and `Referer` headers on state-changing requests.

### Medium-term (P2)

8. **Add Content-Security-Policy** header.
9. **Validate WebSocket message sizes** — Reject messages > 64KB.
10. **Use `secrets` module** for OTP generation.
11. **Add authentication to static file serving** — Serve files through a protected endpoint that checks chat membership.
12. **Implement token refresh rotation** — Short-lived access tokens (15 min) + long-lived refresh tokens.

---

*This audit is based on a manual review of `backend/server.py` and `frontend/index.html`. Automated tooling (e.g., bandit, npm audit, OWASP ZAP) would likely find additional issues.*
