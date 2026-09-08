## 🚨 Do this before anything else (5 minutes)

Your `backend/.env` contains a **real** Google OAuth client secret, a **real** Twilio Account SID + Auth Token, and a hardcoded JWT `SECRET_KEY`. Good news: I checked `git log --all` across every commit and none of `.env`, `.fernet_key`, or `firebase-config.json` were ever committed — they're correctly gitignored. But:

- [ ] Confirm on GitHub itself (not just locally) that these files never appear in any commit — go to the repo, use the "Go to file" search for `.env`, and check `git log --all --full-history -- backend/.env` on your machine too.
- [ ] Even though it's not leaked, **rotate the Twilio Auth Token and Google OAuth secret anyway** before going to production — they've been sitting in a plaintext file, possibly synced to cloud drives, shared in this chat's zip, etc. Cheap insurance.
- [ ] Move all of these into your cloud provider's secret manager (Render/Railway secrets, AWS Secrets Manager, GCP Secret Manager) — never a `.env` file — once you deploy. Covered in the cloud-native section below.
- [ ] Remove `os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'` (`server.py` line 30) before production — this globally disables HTTPS enforcement for OAuth token exchange. It's a local-dev convenience flag that has no business running in prod.

---

## 1. Why login fails / is flaky (root cause, not a guess)

**File:** `backend/server.py`, lines 505–525

```python
async def init_redis(self):
    try:
        redis_client = await redis.from_url(REDIS_URL, ...)
        await redis_client.ping()
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {e}")
        redis_client = MockRedis()   # <-- silent fallback to IN-MEMORY dict
```

Your `.env` has `REDIS_URL=redis://localhost:6379`. On your own machine that's fine because Redis is running locally. **The moment you deploy to any cloud host, there is no `localhost:6379` inside that container**, so this silently falls back to `MockRedis` — a plain Python dict living in one process's RAM.

This explains almost every "can't log in" symptom you'll see in production:
- Register a user → works (data goes into the in-memory dict).
- Container restarts, redeploys, or auto-scales to a second instance (which cloud hosts do constantly) → the dict is gone or a *different* dict on a *different* instance now answers the request → "user not found."
- If you ever run more than one instance/replica behind a load balancer, half your login requests land on an instance that has never heard of the user you just registered on the other instance.

**Fix — make Redis a hard requirement in production, fail loudly instead of silently degrading:**

```python
async def init_redis(self):
    global redis_client
    is_production = os.getenv('ENVIRONMENT', 'development') == 'production'
    try:
        redis_client = await redis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True, socket_connect_timeout=5
        )
        await redis_client.ping()
        logger.info("✅ Redis connected successfully")
    except Exception as e:
        if is_production:
            logger.critical(f"❌ Redis is REQUIRED in production and connection failed: {e}")
            raise SystemExit(1)  # fail fast — don't limp along on MockRedis in prod
        logger.warning(f"⚠️ Redis connection failed, using in-memory mock (dev only): {e}")
        redis_client = MockRedis()
```

- [x] Apply the fix above. (DONE: `app/core/redis_client.py` `init_redis()` raises in prod, falls back to MockRedis only in dev.)
- [ ] Add `ENVIRONMENT=production` to your cloud host's env vars.
- [ ] Provision a **managed Redis** instance (Render Redis, Upstash, AWS ElastiCache, Railway Redis addon) and point `REDIS_URL` at it. This is non-negotiable for cloud deployment — it's covered again in the infra section.

---

## 2. Why sessions don't stay logged in (the real bug)

**File:** `frontend/index.html`, line 12084–12088 (the login/register success handler) vs. line 5356 (`_doRefreshToken`)

Your login flow stores the access token, but **never stores the refresh token it receives**:

```javascript
if (response.ok && data.success) {
    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('auth_token', authToken);
    localStorage.setItem('current_user', JSON.stringify(currentUser));
    // ❌ data.refresh_token is completely ignored here
```

Meanwhile your access tokens are intentionally short-lived (`backend/server.py` line 1255, 15-minute expiry — this was a correct security decision from your own `TODO.md` item 4.1.1). The auto-refresh interceptor (`_doRefreshToken`, line 5344) reads `localStorage.getItem('refresh_token')` — which was **never set**, because the login handler didn't save it. So:

1. User logs in, gets a 15-minute access token.
2. 15 minutes pass.
3. Any API call 401s.
4. The interceptor tries to refresh — finds no refresh token in storage — refresh fails.
5. User is force-logged-out with "Session expired."

This is exactly the symptom of "session management isn't proper" and it's a **one-line-missing bug**, not a design flaw. Your own `TODO.md` (item 4.1.3) even flags this exact integration step as unchecked: `[ ] Frontend: intercept 401s, call refresh, retry original request`. The interceptor was built, but the piece that actually stores the refresh token after login was never wired in.

**Fix:**

```javascript
if (response.ok && data.success) {
    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('auth_token', authToken);
    localStorage.setItem('refresh_token', data.refresh_token); // ADD THIS LINE
    localStorage.setItem('current_user', JSON.stringify(currentUser));
```

- [ ] Add that line at the auth success handler (~line 12088).
- [ ] Also check `handle_google_auth` on the backend and its frontend callback — confirm the Google Sign-In success path stores `refresh_token` too (search the file for every place `localStorage.setItem('auth_token'` appears — there are several login paths: password, Google, and the app currently only fixes this in one).
- [ ] Also fix the async race in refresh token persistence — see next section.

### 2b. Refresh token persistence has a race condition

**File:** `backend/server.py`, lines 1260–1285

```python
def _generate_refresh_token(self, user_id: str, device_fingerprint: str = '') -> str:
    ...
    loop = asyncio.get_event_loop()
    try:
        ...
        asyncio.run_coroutine_threadsafe(self._store_refresh_token(token_id, token_data), loop)
    except Exception:
        pass  # Gracefully degrade: refresh still works, just no persistence
```

`run_coroutine_threadsafe` is meant for scheduling work *from a different thread* onto a running loop. Calling it from inside a coroutine that's already running on that same loop is a code smell — it fires the storage write asynchronously with **no guarantee it completes before the HTTP response is sent back**. If a refresh happens immediately after login/register (e.g., another tab opens instantly), the revocation-check logic in `refresh_token()` (line 1227, `stored = await redis_client.hgetall(...)`) can find nothing stored yet, silently skipping the revocation check.

**Fix — make `_generate_refresh_token` genuinely async and await the store directly, since you're always calling it from an async handler anyway:**

```python
async def _generate_refresh_token(self, user_id: str, device_fingerprint: str = '') -> str:
    """Generate a 30-day refresh token, stored in Redis for rotation."""
    token_id = str(uuid.uuid4())
    payload = {
        'user_id': user_id, 'token_id': token_id, 'type': 'refresh',
        'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30),
        'iat': datetime.datetime.now(datetime.UTC)
    }
    refresh_token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    await self._store_refresh_token(token_id, {
        'user_id': user_id,
        'device_fingerprint': device_fingerprint,
        'created_at': datetime.datetime.now(datetime.UTC).isoformat()
    })
    return refresh_token
```

- [x] Change the signature to `async def`. (DONE: `app/auth/tokens.py` `_generate_refresh_token` is async and awaits `_store_refresh_token` directly.)
- [x] Update every call site (`handle_login`, `handle_register`, `refresh_token`, Google auth handler) to `await self._generate_refresh_token(...)`. (DONE: call sites await it.)
- [x] Delete the `asyncio.get_event_loop()` / `run_coroutine_threadsafe` block entirely. (DONE: removed.)

---

## 3. Session architecture — what "proper" actually requires at scale

Beyond the two bugs above, a couple of structural gaps will bite you once this is running in the cloud with more than one instance:

- [ ] **WebSocket fan-out is process-local.** `active_connections` (`server.py` line 353) is a plain Python `Dict` in one process's memory. If you ever run 2+ backend replicas (which any real cloud deployment eventually does for uptime/scaling), a message from a user connected to instance A will never reach a recipient connected to instance B. Fix: publish outgoing WS events to a Redis Pub/Sub channel and have every instance subscribe and forward to its own locally-connected sockets. This is a required change before horizontal scaling works at all — not optional polish.
- [ ] **Debug endpoints exist in the route table** (`/api/debug/check-user/{username}`, `/api/debug/redis/{username}`, `/api/debug/my-chats`). They're gated by `_is_admin()`, which checks an `ADMIN_USER_IDS` env var **or** a `DEBUG=true` env var that bypasses the check entirely (`server.py` line 374-ish). Make sure `DEBUG` is never set to `true` in your production environment — one misconfigured env var re-opens these. Consider removing them from the router entirely in prod builds via a startup flag.
- [ ] **CORS is currently permissive** (`ALLOWED_ORIGIN` defaults to `*` when unset). Set `ALLOWED_ORIGIN` explicitly to your real deployed frontend domain in production.
- [ ] Cookie-based session storage (`aiohttp_session` + `EncryptedCookieStorage`) is set up alongside JWT bearer tokens — you're running two parallel session mechanisms. Confirm which one is actually authoritative; if the cookie session isn't used by the frontend at all, remove it to cut confusion and attack surface.

---

## 4. Group video calls — the architecture, not just a bug

**File:** `frontend/index.html`, lines 5579–9926 (call logic)

Your group calls use **full mesh WebRTC**: every participant opens a direct `RTCPeerConnection` to every other participant (`groupCallPeers = new Map()`). Signaling for ICE candidates is sent over plain HTTP POST/GET polling, not over your existing WebSocket connection.

Why this breaks down:
- Mesh bandwidth/CPU cost grows **O(n²)**. At 4 people each device is encoding and sending 3 separate video streams simultaneously — mobile devices and modest laptops choke well before 6–8 participants.
- HTTP-polling for ICE candidates instead of your already-open WebSocket adds latency and a real chance of races/missed signals during call setup — a classic cause of "call connects for some pairs but not others" in group calls.
- TURN relay is fetched from a free Metered.ca endpoint at runtime with no SLA — fine for a demo, not for "industry ready."

**Recommended fix — move to an SFU (Selective Forwarding Unit).** Don't build this yourself; use one of:

| Option | Notes |
|---|---|
| **LiveKit** (self-hosted or LiveKit Cloud) | Best documented, has a JS SDK that replaces your entire peer-connection logic with a handful of calls, supports simulcast, screen share, recording. Recommended first choice. |
| **mediasoup** | More control, more work — you write your own signaling server on top of it. Only worth it if LiveKit's hosted pricing doesn't fit. |
| **Jitsi Videobridge (JVB)** | Can self-host, but heavier ops burden than LiveKit. |

With an SFU, every participant sends **one** upstream stream to the server and receives one multiplexed downstream — this is the only architecture that scales past ~4 people reliably and is what every production group-calling product (Zoom, Meet, Discord) actually uses.

- [ ] Stand up a LiveKit server (Docker image `livekit/livekit-server`, or use LiveKit Cloud's free tier to prototype).
- [ ] Replace `groupCallPeers`/mesh logic with the `livekit-client` JS SDK: `Room.connect(url, token)`, `room.localParticipant.publishTrack(...)`, listen to `RoomEvent.TrackSubscribed` for remote video elements.
- [ ] Your backend's job becomes: authenticate the user, then mint a short-lived LiveKit access token (`AccessToken` from `livekit-server-sdk`) — replacing `initiate_group_call`/`join_group_call`'s current custom signaling relay.
- [ ] Keep your existing 1:1 mesh call flow if you want (mesh is fine for exactly 2 people) — just don't extend it to groups.
- [ ] Move ICE/signaling for the 1:1 path onto your existing WebSocket connection instead of HTTP polling, for lower latency and one less thing that can silently fail.

This is genuinely the single biggest lift in this whole list — budget it as its own multi-day work item, not a quick patch.

---

## 5. Cloud-native deployment — currently there is none

I checked: there is no `Dockerfile`, no `docker-compose.yml`, no `Procfile`, no CI/CD config, and no `render.yaml`/`fly.toml` anywhere in the repo. Right now this only runs by someone manually starting `python server.py` next to a manually-installed local Redis. Here's the minimum to make it actually deployable.

### 5.1 — Dockerfile

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps needed by Pillow / docx2pdf / pdf2docx / lxml, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev zlib1g-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8080
ENV ENVIRONMENT=production

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "server.py"]
```

- [ ] Add this at `backend/Dockerfile`.
- [ ] Your `/health` route already exists (`server.py` line 593) — confirm it actually checks Redis/Firestore connectivity and doesn't just return `200 OK` unconditionally; a real health check should report `503` if Redis is down so your orchestrator can restart/avoid routing to a broken instance.

### 5.2 — docker-compose.yml (local dev parity with prod)

```yaml
# docker-compose.yml
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis-data:/data"]

  backend:
    build: ./backend
    ports: ["8080:8080"]
    environment:
      - REDIS_URL=redis://redis:6379
      - ENVIRONMENT=development
    env_file: ./backend/.env
    depends_on: [redis]
    volumes:
      - ./backend/uploads:/app/uploads

volumes:
  redis-data:
```

- [ ] This makes "it works on my machine" and "it works in the cloud" use the *same* Redis dependency model, closing the exact gap that causes bug #1 above.

### 5.3 — Where to actually deploy

| Piece | Suggested home |
|---|---|
| Backend (aiohttp app) | Render / Railway / Fly.io (all support Docker + WebSockets natively) |
| Redis | Managed: Upstash (serverless, generous free tier) or your host's Redis addon — never self-managed on the same box as the app |
| File uploads (`uploads/` dir) | **Move off local disk now.** Local disk on most cloud hosts is ephemeral — it's wiped on every redeploy/restart. Use S3, Cloudflare R2, or GCS for `uploads/avatars`, `uploads/documents`, etc. |
| Frontend static file | Can stay served by the same aiohttp app for simplicity, or split to a CDN (Cloudflare Pages/Vercel) once you componentize it (see UI section) |
| Video SFU (LiveKit) | LiveKit Cloud, or self-host as a separate container/service |

- [ ] Swap local `uploads/` disk storage for S3-compatible object storage. This is required for cloud-native — right now, uploaded avatars/files/voice notes will vanish on every redeploy.
- [x] Add `GET /health` that returns `503` when Redis/Firestore are unreachable (see 5.1). (DONE: `app/static/frontend_routes.py` `health_check` now returns 503 + `status:"unhealthy"` when redis/storage are down.)
- [ ] Add structured JSON logging (swap the emoji-decorated `logger.info` calls for structured fields) so your cloud host's log aggregation (Render logs, CloudWatch, etc.) is actually queryable in production. Keep the human-friendly messages, just add `extra={...}` fields for `user_id`, `event`, etc.
- [ ] Add a minimal CI pipeline (GitHub Actions) that at least runs `python -m py_compile backend/server.py` and your existing `test_converter.py` on every push, and builds+pushes the Docker image on merge to `main`.

---

## 6. UI/UX — you already have the right design system, it's just not applied consistently

Your own `UI_REDESIGN.md` documents a genuinely good, distinctive **"Copper & Graphite"** token system (custom serif/sans pairing, warm neutral palette, defined elevation tokens) — this is not a "start over" situation. The problem is execution, not the design direction:

- The entire UI lives in **one 15,802-line HTML file** with a single 4,200-line `<style>` block.
- There are **293 inline `style="..."` attributes** scattered through the markup/JS, fighting against the centralized CSS tokens — this is almost certainly why it "feels bad" despite a decent color scheme: specificity conflicts and one-off styling drift from the token system every time a new feature was bolted on.
- 6 separate `DOMContentLoaded` listeners are scattered through the file, which is also why you're seeing flaky init-order bugs (like the auth form re-binding logic with manual "already initialized" guards at line 11996 — a workaround for a structural problem, not a fix for it).

### Recommended path (matches your own `UI_REDESIGN.md` priority order: chat list → thread → file picker → call UI)

- [ ] **Don't do a full rewrite.** Your instinct in `UI_REDESIGN.md` — "restraint and distinctiveness... faster than a full rewrite" — is correct. Keep the Copper & Graphite tokens.
- [ ] **Do componentize.** Move to Vite + vanilla JS (lowest migration cost) or Vite + a lightweight framework (Preact/React) if you want it more maintainable long-term. Break the 15,802-line file into: `auth/`, `chat-list/`, `message-thread/`, `call-ui/`, `settings/`, each with its own scoped CSS module pulling from a shared `tokens.css` (your existing `:root` variables, unchanged).
- [ ] **Eliminate the 293 inline styles.** Every `element.style.xxx = ...` in JS should become a CSS class toggle (`element.classList.add('is-active')`) driven by the token system, not ad hoc pixel/color values set from script.
- [ ] **Consolidate the 6 `DOMContentLoaded` listeners into one explicit init sequence** — this alone will fix a category of "sometimes the button doesn't respond" bugs that come from race conditions between listeners, not from the UI design itself.
- [ ] Once componentized, this also unlocks splitting frontend deployment to a CDN (Cloudflare Pages/Vercel) separate from the API — real cloud-native separation of concerns, and free global edge caching for your static assets.

I can execute this UI refactor with you screen-by-screen (starting with the chat list + message thread, per your own prioritization) once the login/session fixes above are in — no point redesigning a screen that's still fighting session bugs underneath it.

---

## Suggested order of operations

1. **Today:** Section 1 + 2 fixes (Redis-required-in-prod, refresh token storage bug, refresh token race). These are small, surgical, and fix "can't log in" + "session management" directly.
2. **This week:** Section 5 (Dockerfile, docker-compose, managed Redis, S3 for uploads, health check). Gets you to a genuinely deployable state.
3. **Next:** Section 3 (Redis Pub/Sub for WebSocket fan-out) — only urgent once you run more than one instance.
4. **Bigger lift, schedule separately:** Section 4 (SFU migration for group calls) and Section 6 (UI componentization) — both are real projects, not patches.
