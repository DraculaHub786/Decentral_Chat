# DecentralChat — Target Project Structure & Migration Plan

This maps every function currently in your 7,311-line `server.py` and 15,802-line `index.html` to a specific new file, plus a safe, incremental order to do the split in (you should never have a moment where the app doesn't run).

---

## Backend target structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                      # creates the aiohttp app, runs it — replaces bottom of current server.py
│   │
│   ├── core/
│   │   ├── config.py                # env var loading: REDIS_URL, SECRET_KEY, PORT, etc. (currently top of server.py)
│   │   ├── security.py              # _ensure_secret_key, _ensure_fernet_key, _validate_password,
│   │   │                            #   _validate_file_magic, _resolve_safe_path, _log_safe, _is_admin,
│   │   │                            #   _validate_cors_origin  (lines 203–396)
│   │   ├── rate_limiter.py          # class RateLimiter (line 428)
│   │   ├── redis_client.py          # init_redis(), MockRedis, MockPipeline (lines 507–525, 7091–7235)
│   │   ├── firebase_client.py       # init_firebase() (line 529)
│   │   └── middleware.py            # csrf_middleware, security_headers_middleware (lines 469–500)
│   │
│   ├── ws/
│   │   ├── connection_manager.py    # active_connections registry, broadcast_to_users,
│   │   │                            #   broadcast_user_status, broadcast_typing (lines 6366–6432)
│   │   └── handler.py               # websocket_handler, handle_ws_message, handle_read_receipt (lines 5877–6365)
│   │
│   ├── auth/
│   │   ├── routes.py                # route registration only
│   │   ├── handlers.py              # handle_register, handle_login, handle_logout, refresh_token
│   │   │                            #   (lines 704–1250)
│   │   ├── tokens.py                # generate_token, _generate_refresh_token, _store_refresh_token,
│   │   │                            #   get_user_from_token (lines 1251–1310)
│   │   ├── google.py                # handle_google_auth (line 6490)
│   │   └── phone_verification.py    # send_verification_code, verify_phone_code, Twilio client (line 6631)
│   │
│   ├── users/
│   │   ├── routes.py
│   │   └── handlers.py              # get_current_user, update_profile, get_user_public_key, upload_avatar,
│   │                                #   update_email, update_phone, search_users, search_all_users,
│   │                                #   get_user_by_id, get_user_settings, update_user_settings,
│   │                                #   update_user_profile (lines 1625–2101, 6776–6868, 7065)
│   │
│   ├── contacts/
│   │   ├── routes.py
│   │   └── handlers.py              # get_contacts, add_contact, remove_contact, block_user,
│   │                                #   unblock_user, check_blocked_status, get_blocked_users
│   │                                #   (lines 2102–2420)
│   │
│   ├── chats/
│   │   ├── routes.py
│   │   └── handlers.py              # get_chats, create_chat, get_chat, delete_chat, add_chat_member,
│   │                                #   remove_chat_member, update_group_chat (lines 2042, 3383–3874)
│   │
│   ├── messages/
│   │   ├── routes.py
│   │   ├── handlers.py              # get_messages, search_messages_in_chat, send_message_http,
│   │   │                            #   delete_message, edit_message, delete_message_for_all,
│   │   │                            #   delete_message_for_me, forward_message (lines 3875–4533, 6869–7019)
│   │   └── service.py               # create_message, broadcast_message (lines 4263–4479) — shared by
│   │                                #   both the HTTP handler and the WS handler, so it's its own module
│   │
│   ├── files/
│   │   ├── routes.py
│   │   ├── handlers.py              # upload_file, upload_voice, get_file, get_thumbnail, serve_upload,
│   │   │                            #   generate_thumbnail, get_file_type, _check_upload_rate_limit,
│   │   │                            #   migrate_existing_files (lines 4534–5231, 7020)
│   │   └── converters/
│   │       ├── service.py           # perform_file_conversion, get_supported_conversions,
│   │       │                        #   convert_uploaded_file, progress tracking (lines 2421–2475,
│   │       │                        #   3305–3332, 4812–5100)
│   │       ├── images.py            # convert_image_format (line 2476)
│   │       ├── documents.py         # convert_document_format (line 2593 — this one alone is ~580 lines,
│   │       │                        #   worth its own file regardless of the rest of the split)
│   │       ├── audio.py             # convert_audio_format (line 3171)
│   │       └── video.py             # convert_video_format (line 3216)
│   │
│   ├── calls/
│   │   ├── routes.py                # 1:1 call REST endpoints
│   │   ├── handlers.py              # initiate_call, handle_call_signal, get_call_signals, end_call,
│   │   │                            #   get_call_history (lines 5232–5588)
│   │   ├── ws_signal.py             # handle_ws_call_signal (line 6023)
│   │   └── group/
│   │       ├── routes.py            # group call REST endpoints
│   │       ├── handlers.py          # initiate_group_call, join_group_call, leave_group_call,
│   │       │                        #   get_group_call_participants (lines 5589–5876)
│   │       └── ws_signal.py         # handle_group_call_start/signal/ice/leave_ws (lines 6072–6269)
│   │                                #   — this whole folder gets replaced by a LiveKit token-minting
│   │                                #   endpoint once you do the SFU migration from the previous doc
│   │
│   ├── admin/
│   │   └── debug_routes.py          # debug_check_user, debug_redis_state, debug_user_chats
│   │                                #   (lines 890, 1124, 1166) — isolated here on purpose, so it's
│   │                                #   trivial to exclude this whole module from prod builds
│   │
│   ├── static/
│   │   └── frontend_routes.py       # serve_frontend, serve_favicon, index, health_check
│   │                                #   (lines 1312–1346, 6433–6489)
│   │
│   └── sync/
│       └── firestore_sync.py        # preload_critical_data_from_firestore,
│                                     #   sync_redis_to_firestore_periodically (lines 1347, 3332)
│
├── tests/
│   ├── test_auth.py
│   ├── test_messages.py
│   └── ...                          # one test file per module above, finally possible once handlers
│                                     #   aren't 7,000 lines deep in one class
│
├── requirements.txt
├── Dockerfile
└── .env.example                     # committed placeholder — never the real .env
```

### Why this split (not just "smaller files for its own sake")

- Every `routes.py` only calls `app.router.add_*` — no logic. You can see your entire API surface by skimming 12 small files instead of scrolling one 7,000-line file.
- `messages/service.py` is separated from `messages/handlers.py` because `create_message`/`broadcast_message` are called from **both** the HTTP handler and the WebSocket handler — pulling shared logic into a service module is what makes that reuse obvious instead of hidden.
- `admin/debug_routes.py` being its own module means "exclude debug routes from the prod image" becomes a one-line conditional import in `main.py`, instead of trusting an env var check buried inside each handler.
- `calls/group/` is isolated specifically so the SFU migration (LiveKit) from the previous doc is a **folder replacement**, not a search-and-destroy across a monolith.

### Backend migration order (do this without breaking the running app)

1. Create `app/core/` first (config, security, rate_limiter, redis_client, firebase_client, middleware) — these have no dependencies on route handlers, so extracting them is zero-risk. Update `server.py`'s imports to pull from these new modules instead of defining them inline. Run the app, confirm nothing changed.
2. Extract `ws/connection_manager.py` next — it's used by almost every other module (`broadcast_to_users` etc.), so get it out of the monolith early so everything else can import from its final location instead of a temporary one.
3. Extract one feature module at a time, in this order: `auth` → `users` → `contacts` → `chats` → `messages` → `files` (+ `converters`) → `calls` → `calls/group` → `admin` → `static`. After each extraction: run the app, hit the affected endpoints, confirm identical behavior, commit. Don't extract two modules in the same commit — if something breaks, you want a one-module diff to bisect.
4. Once every handler is moved, `main.py` becomes just: create the app, call each module's `setup_routes(app)`, apply middleware, start the server. `server.py` itself is deleted.

---

## Frontend target structure

Right now everything — HTML, 4,200 lines of CSS, and ~11,000 lines of JS — lives in one `index.html`. The lowest-risk way to fix this without a framework rewrite is **Vite** in vanilla-JS mode: it gives you ES module imports, dev server with hot reload, and a production build step, without forcing you onto React/Vue.

```
frontend/
├── index.html                       # now just a thin shell: <div id="app"></div> +
│                                     #   <script type="module" src="/src/main.js">
├── vite.config.js
├── package.json
│
├── src/
│   ├── main.js                      # single entry point — replaces the 6 separate
│   │                                #   DOMContentLoaded listeners with one explicit init sequence
│   │
│   ├── config/
│   │   └── api.js                   # detectAPIURL, apiFetch, _doRefreshToken, the fetch monkey-patch
│   │                                #   (lines 5308–5420) — this is the file where you apply the
│   │                                #   refresh-token storage fix from the previous doc
│   │
│   ├── state/
│   │   └── store.js                 # currentUser, authToken, activeChat and friends — currently
│   │                                #   scattered global `let` variables; centralize as one module
│   │                                #   with getters/setters so every feature module imports state
│   │                                #   from one place instead of relying on globals
│   │
│   ├── auth/
│   │   ├── login-form.js            # initializeAuthForm, form submit handler (lines 11996–12130)
│   │   └── google-auth.js           # loadGoogleAPI + Google sign-in callback handling
│   │
│   ├── chat/
│   │   ├── chat-list.js             # sidebar / conversation list rendering
│   │   ├── message-thread.js        # message rendering, scroll behavior
│   │   ├── message-input.js         # composer, send logic
│   │   └── typing-indicator.js
│   │
│   ├── calls/
│   │   ├── call-1to1.js             # createPeerConnectionWithTrickleICE and the 1:1 flow
│   │   │                            #   (lines 9099–9420) — keep mesh here, it's fine for 2 people
│   │   ├── group-call.js            # current mesh group-call logic (lines 5579–9926) — this file
│   │   │                            #   is the one that gets replaced wholesale when you migrate
│   │   │                            #   to LiveKit per the previous doc, so isolating it now means
│   │   │                            #   that migration touches exactly one file
│   │   └── call-ui.js               # call modal, controls, mute/camera toggle UI
│   │
│   ├── contacts/
│   │   └── contacts.js
│   │
│   ├── settings/
│   │   └── settings.js
│   │
│   ├── files/
│   │   ├── file-upload.js           # triggerFileUpload/triggerImageUpload + preview handling
│   │   │                            #   (per your MOBILE_FIXES_SUMMARY.md — keep the mobile fixes,
│   │   │                            #   just move them into this file)
│   │   └── file-converter.js
│   │
│   ├── e2e/
│   │   └── crypto-engine.js         # CryptoEngine.init(), key generation/storage
│   │                                #   (this is also where TODO.md Phase 5, the key-durability
│   │                                #   bug, gets fixed — one file, one place to reason about it)
│   │
│   ├── ui/
│   │   ├── modals.js                # generic modal open/close/cleanup (currently the big switch
│   │   │                            #   statement around line 11960)
│   │   ├── toast.js                 # showSuccess/showError/showCustomAlert
│   │   └── emoji-picker.js
│   │
│   └── utils/
│       └── format.js                # escapeHtml, formatFileSize, and other small pure helpers —
│                                     #   extract these FIRST, see migration order below
│
└── styles/
    ├── tokens.css                    # your existing :root variables verbatim — Copper & Graphite,
    │                                 #   Fraunces/Inter — untouched, just moved out of the <style> tag
    ├── base.css                      # resets, typography, .glass / .glass-strong surfaces
    └── components/
        ├── auth.css
        ├── chat-list.css
        ├── message-thread.css
        ├── call-ui.css
        ├── modals.css
        └── forms.css
```

### `vite.config.js` (minimal, no framework)

```javascript
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'frontend',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080', // dev-time proxy to your aiohttp backend
    },
  },
});
```

Your backend's `serve_frontend` handler then just serves `dist/index.html` and the built assets in production, instead of the current raw `frontend/index.html`.

### Frontend migration order (also incremental — this file is too large to split in one sitting safely)

1. **Pull out pure utilities first** — `escapeHtml`, `formatFileSize`, and similar dependency-free functions into `src/utils/format.js`. Zero behavior risk, and it proves the module-import pattern works before you touch anything stateful.
2. **Move CSS out of the `<style>` tag into `styles/tokens.css` + `styles/base.css`** verbatim — no changes to the actual rules yet, just relocating them. Confirm the page still looks identical.
3. **Extract `config/api.js`** (the fetch wrapper + refresh interceptor) — this is where you apply the refresh-token bug fix from the previous doc. Getting this into its own module first means every other feature module can `import { apiFetch } from '../config/api.js'` instead of relying on the global `fetch` monkey-patch, which removes one of the sources of the current init-order fragility.
4. **Extract `state/store.js`** next — centralize `authToken`, `currentUser`, `activeChat` here. Every module you extract after this imports state from here rather than declaring its own globals.
5. **One feature folder at a time**: `auth/` → `chat/` → `contacts/` → `settings/` → `files/` → `ui/` → `calls/`. Save `calls/group-call.js` for last, or better, skip extracting its *internals* entirely and just move the file wholesale — you're about to replace its contents with the LiveKit SDK anyway, per the previous doc, so there's no point cleaning up code you're going to delete.
6. **Consolidate the 6 `DOMContentLoaded` listeners into `main.js`'s single init sequence** as the final step, once every feature module exists and can be explicitly called in the right order (auth form → then chat list → then WS connection → etc.). This is what actually fixes the race-condition-flavored bugs, not just the code organization.
7. Once everything is extracted, delete the giant inline `<script>` block from `index.html` — it should be down to a `<script type="module" src="/src/main.js">` and nothing else.

---

## Suggested sequencing against the previous doc

1. Apply the login/session bug fixes from the engineering audit **first**, while the code is still in the monolith — small, surgical, low-risk, and you want those fixed before you start moving code around so you're not chasing the same bug through two different file locations.
2. Do the backend split (it's mechanical — moving functions into files, no new logic).
3. Do steps 1–4 of the frontend split (utils, CSS, api.js, store.js) — these directly support fixing session bugs cleanly.
4. Do the Dockerfile/docker-compose/deployment work from the audit doc against the now-modular backend — it's much easier to containerize `app/main.py` cleanly than the current single `server.py`.
5. Then tackle the two bigger projects from the audit doc: the LiveKit group-call migration (now isolated to `calls/group/` and `group-call.js`) and the remaining UI componentization/redesign pass.

Tell me which piece you want to start with and I'll write the actual extracted files against your real code, not just the plan.