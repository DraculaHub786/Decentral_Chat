# DecentralChat — Security & Encryption TODO

Two workstreams only, per your request: the security fix plan, and the E2E key-durability bug. UI redesign is done and removed from this file — see `UI_REDESIGN.md` if you need that history.

Check items off as you go (`- [x]`). Risk levels and constraints are carried over from the security plan as-is.

---

## ⚠️ Constraints — apply to every task below
- No schema changes to Firestore documents or Redis hash keys
- No new required environment variables without safe defaults
- No new dependencies unless unavoidable (prefer stdlib)
- No frontend HTML changes unless the fix is specifically a frontend vulnerability
- Every new check must degrade gracefully (rate-limiter down → allow through; file check fails → log and allow)
- Zero behavioral change for legitimate users

## 🧪 Testing pattern — repeat for every task
1. Before: run existing tests (if any), note state
2. After: re-run — output must match
3. Manual smoke test: register → login → send message → upload file → logout → login again — all must still work

---

## Phase 1 — Critical (P0)

### 1.1 — Persistent JWT secret key
Why: `SECRET_KEY` regenerates randomly on every restart → invalidates all JWTs, opens door to token forgery.
- [x] 1.1.1 Add `_ensure_secret_key(path=None)`: read `SECRET_KEY` from a file on disk if the env var is missing; if neither exists, generate once, save to file, return it
- [x] 1.1.2 Replace `os.getenv('SECRET_KEY', Fernet.generate_key().decode())` with a call to `_ensure_secret_key()`
- [x] 1.1.3 Document the secret key file location in `.env.example` / README
- [x] 1.1.4 Add `.secret_key` to `.gitignore`
- Risk: 🔵 Very low — only changes the key's source, not how it's used

### 1.2 — Persistent Fernet encryption key
Why: `ENCRYPTION_KEY` has the same problem — random each restart makes stored encrypted data permanently undecryptable.
- [x] 1.2.1 Reuse the same pattern as 1.1.1 — write `_ensure_fernet_key(path=None)`
- [x] 1.2.2 Replace `os.getenv('ENCRYPTION_KEY', Fernet.generate_key())` with `_ensure_fernet_key()`
- [x] 1.2.3 Add `.fernet_key` to `.gitignore`
- Risk: 🔵 Very low — key source only, `cipher_suite.encrypt`/`decrypt` calls unchanged

### 1.3 — SSRF prevention via file path validation
Why: file conversion/serving opens any path pulled from Firestore/Redis → attacker can read arbitrary system files.
- [x] 1.3.1 Create `_resolve_safe_path(base_dir, user_path)` — module-level function using `Path.relative_to()` to verify resolves within `base_dir`; raises `ValueError` on escape
- [x] 1.3.2 Call `_resolve_safe_path(UPLOAD_DIR, file_meta['path'])` in `get_file()` before opening the file
- [x] 1.3.3 Same check in `convert_uploaded_file()` before opening `source_path`
- [x] 1.3.4 Same check in `get_thumbnail()` before opening the thumbnail path
- Risk: 🟡 Low-medium — a legitimate path stored outside `uploads/` would get rejected. Mitigation: log a warning with the exact path so the record can be fixed; rollback is a one-line revert

---

## Phase 2 — High risk (P1)

### 2.1 — File upload content-type validation (magic bytes)
Why: only the extension is checked → a `.txt` can actually be HTML/script content.
- [x] 2.1.1 Add `_validate_file_magic()` module-level function: checks magic bytes for PNG/JPEG/GIF/WEBP/BMP; for non-images rejects first 512 bytes containing `<html`, `<script`, `<?php`
- [x] 2.1.2 In `upload_file()`, call `_validate_file_magic()` after saving; delete + return 400 on failure if content doesn't match extension
- [x] 2.1.3 `X-Content-Type-Options: nosniff` comment added alongside static route for future enforcement
- Risk: 🟡 Low — conservative check, only blocks clearly malicious cases

### 2.2 — Rate limiting on auth endpoints
Why: no protection against brute-force login or registration spam.
- [x] 2.2.1 Build `RateLimiter` class with `is_rate_limited(key)` — stores timestamps, prunes old entries, returns True if over `max_attempts` within `window_seconds`
- [x] 2.2.2 Guard `handle_register` and `handle_login` — check `self.rate_limiter.is_rate_limited()` at start, return 429 if limited
- [x] 2.2.3 Instantiated as `self.rate_limiter` in `DecentralChatServer.__init__`
- Risk: 🔵 Very low — purely additive, only affects requests above threshold

### 2.3 — Stronger password policy
Why: currently just a 6-character minimum, no complexity requirement.
- [x] 2.3.1 Add `_validate_password()` module-level function: min 8 chars, ≥1 uppercase, ≥1 digit
- [x] 2.3.2 In `handle_register`, replaced `len(password) < 6` with `_validate_password()`
- [x] 2.3.3 Returns specific error message on failure (e.g. "Password must be at least 8 characters")
- Risk: 🔵 Very low — existing users unaffected, only new registrations validated

### 2.4 — WebSocket message validation
Why: no max message size or content cap → DoS via oversized/spammy messages.
- [x] 2.4.1 In `websocket_handler`, reject `msg.data` over 65,536 bytes with JSON error before processing; in `handle_ws_message`, trim `content` to 10,000 characters
- [x] 2.4.2 Added typing-event cooldown in `broadcast_typing` — ignores repeats from same user under 500ms apart
- Risk: 🔵 Very low — only caps extreme inputs

### 2.5 — CSRF protection
Why: no origin/referer validation on state-changing endpoints.
- [x] 2.5.1 Add `_validate_cors_origin(request)` module-level function: checks `Origin`/`Referer` against `http://localhost:8080`, `http://127.0.0.1:8080`, and `ALLOWED_ORIGIN` env var; if both absent on mutating methods, **allow** (API clients don't send origin)
- [x] 2.5.2 Applied via `@web.middleware` in `initialize()` — checks all mutating requests
- [x] 2.5.3 Tightened `aiohttp_cors` config from `"*"` to `os.getenv('ALLOWED_ORIGIN', '*')`
- Risk: 🟡 Low — could block legitimate custom-client calls. Mitigation: defaults to `*` if `ALLOWED_ORIGIN` not set

---

## Phase 3 — Medium risk (P2)

### 3.1 — Gate debug endpoints
Why: `/api/debug/check-user`, `/api/debug/redis`, `/api/debug/my-chats` expose internal state.
- [x] 3.1.1 `_is_admin()` function added — reads `ADMIN_USER_IDS` env var (comma-separated list), also allows through when `DEBUG=true`/`1`/`yes`
- [x] 3.1.2 All three debug endpoints gated with `if not _is_admin(request): return 404` at top of handler
- [x] 3.1.3 Alternative: `DEBUG=true` env var bypasses admin check entirely
- Risk: 🔵 Very low — only affects debug routes

### 3.2 — Security headers middleware
Why: missing CSP, `X-Content-Type-Options`, `X-Frame-Options`, HSTS.
- [x] 3.2.1 Middleware sets: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, CSP with `default-src 'self'`, media/img/connect/font/style/script permissive for Google resources, `frame-src 'none'`
- [x] 3.2.2 Registered in `initialize()` after CSRF middleware, before routes are set up
- Risk: 🟡 Low — CSP can block legitimate external resources; test every feature after applying

### 3.3 — Authenticate static file serving
Why: `/api/uploads/` is open to anyone who knows a file ID.
- [x] 3.3.1 Added `serve_upload()` handler — checks `?token=<jwt>` query param first, then `Authorization` header, then falls through to static dir for backward compat
- [x] 3.3.2 Token-based auth via `?token=<jwt>` query param alongside `add_static` fallback
- Risk: 🟠 Medium-high — backward-compatible; existing `add_static` still serves unauthenticated requests

### 3.4 — Use `secrets` module for OTP
Why: OTP currently uses `random.choices` (Mersenne Twister — predictable).
- [x] 3.4.1 Replaced `random.choices(string.digits, k=6)` with `''.join(secrets.choice(string.digits) for _ in range(6))`
- [x] 3.4.2 Added `import secrets`
- Risk: 🔵 Very low — one-line change, no behavioral difference

### 3.5 — Log sanitisation
Why: email/phone/username data logged at INFO level.
- [x] 3.5.1 Added `_log_safe()` helper — redacts emails (`u***@domain.com`) and phone numbers (`+91******3210`)
- [x] 3.5.2 Replaced registration email/phone logs, login identifier log, Google auth email log, phone verification log with redacted versions
- Risk: 🔵 Very low — only affects log output

---

## Phase 4 — Low risk / informational (P3)

### 4.1 — Token expiry & rotation
Why: 30-day tokens, no refresh mechanism.
- [ ] 4.1.1 Reduce access token expiry to 15 minutes
- [ ] 4.1.2 Add `/api/auth/refresh` — accepts a refresh token, issues a new 30-day one, stored in Redis
- [ ] 4.1.3 Frontend: intercept 401s, call refresh, retry original request
- [ ] 4.1.4 Store refresh tokens with a device fingerprint (User-Agent hash)
- Risk: 🟠 Medium — needs backend + frontend changes together. Mitigation: deploy backend first (old 30-day tokens still work), frontend second

### 4.2 — Per-user upload rate limit
Why: no cap → storage exhaustion risk.
- [ ] 4.2.1 Count uploads/hour via Redis key `user_upload_count:{user_id}` with TTL
- [ ] 4.2.2 Reject over 50/hour
- [ ] 4.2.3 Increment after successful upload
- Risk: 🔵 Very low — simple additive check, threshold adjustable

---

## Implementation order

```
Phase 1 (Critical) ──────────► Phase 2 (High) ───────────► Phase 3 (Medium) ──► Phase 4 (Low)
  1.1 JWT key persist            2.1 File magic check         3.1 Debug gates       4.1 Token rotation
  1.2 Fernet key persist         2.2 Rate limiting            3.2 Security headers  4.2 Upload rate limit
  1.3 Path validation            2.3 Password policy          3.3 Auth file serve
                                 2.4 WS validation             3.4 secrets OTP
                                 2.5 CSRF protection           3.5 Log sanitisation
```
Each phase is independent — stopping after any phase leaves the app fully functional.

---

## Phase 5 — E2E encryption key durability (frontend bug, from "chats show as encrypted / no key" report)

Why: `e2e_private_key`, `e2e_public_key`, and per-chat AES keys (`e2e_chat_keys`) live only in browser `localStorage` — never backed up, never synced to the account. If storage is cleared (new browser/device, cleared cache, private/incognito mode, reinstall), `CryptoEngine.init()` silently generates a new keypair and `uploadPublicKey()` immediately overwrites the old public key on the server — permanently orphaning every previously-derived shared key, including for the device's own past sent messages. Unrelated to login method; Google and password login both go through the same `CryptoEngine.init()` path.

- [ ] 5.1 Add a warning/confirmation before regenerating a keypair when chat history already exists for the account, instead of silently overwriting the server's stored public key
- [ ] 5.2 Add passphrase-protected export/import for the private key so switching devices or clearing storage doesn't permanently destroy message history
- [ ] 5.3 Add "contact's security key changed" detection/notice (Signal/WhatsApp-style) instead of a silent, unexplained decrypt failure
- [ ] 5.4 Decide and document whether key material should ever be recoverable via an encrypted server-side backup, or whether local-only storage is an intentional tradeoff — currently undocumented, so it reads as a bug when it happens
- [ ] 5.5 Once a direction is picked, audit `showChatInterface()` (the call site of `CryptoEngine.init()` + `uploadPublicKey()`) as the single choke point for the fix
- Risk: 🟠 Medium — touches the trust model of the encryption system directly; test thoroughly with multiple devices/browsers before considering done
