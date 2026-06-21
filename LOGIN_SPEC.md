# Login System — Specification

## Overview

The Mundial app has three types of pages that participate in authentication:

| Page | URL(s) | Auth mechanism |
|---|---|---|
| **Map page** | `localhost:4040/wc2026_map_exported.html`, `mundial.cthiebaud.com/wc2026_map_exported.html` | `localStorage` on the map origin |
| **Login popup** | `localhost:5002/login`, `ngrok/login` | Flask session cookie on the backend origin |
| **Admin page** | `localhost:5002/admin`, `ngrok/admin` | Flask session cookie on the backend origin |

All authentication flows go through the backend (`backend.py` on port 5002).

---

## Key concepts

### Flask session cookie

A server-side session identified by a cookie. Scoped to a **domain** — `localhost:5002` and `ngrok-free.dev` have separate, independent cookies. Contains `user` (email, name, picture) and `sid` (session ID).

### `ONLINE_SESSIONS` (in-memory dict)

Server-side dictionary mapping `sid → {email, user, device, time}`. Tracks all currently active sessions across all browsers and domains. **Lost on backend restart** — this is the source of "ghost sessions" (cookie exists but no tracking entry).

### `localStorage` (map page only)

The map page (`localhost:4040` or `mundial.cthiebaud.com`) cannot use the Flask session cookie because it runs on a different origin than the backend. Instead, it stores `{user, admin, sid}` in `localStorage` after receiving a `postMessage` from the login popup. This is **independent of the Flask session** — clearing the Flask session does not clear `localStorage`, and vice versa.

### Session ID (`sid`)

An 8-character UUID fragment, generated on each call to `POST /api/auth/google`. Stored in:
- `ONLINE_SESSIONS[sid]` on the server
- `session["sid"]` in the Flask session cookie
- `localStorage("mundial_sid")` on the map page

---

## Login flows

### Flow A: Admin page login (direct)

```
Admin page (localhost:5002/admin or ngrok/admin)
    │
    ├─ On load: checkSession()
    │   └─ GET /api/auth/me (with cookies)
    │       ├─ Session exists → show signed-in UI, set mySid
    │       └─ No session → show Google Sign-In button
    │
    └─ User clicks Google Sign-In
        └─ POST /api/auth/google {credential}
            ├─ Backend verifies token with Google
            ├─ Creates ONLINE_SESSIONS[sid] entry
            ├─ Sets Flask session cookie (user + sid)
            ├─ Emits WebSocket 'user_login' event
            └─ Returns {user, admin, sid}
```

**One session created.** The admin page stores `mySid` in a JS variable (not persisted).

### Flow B: Map page login (popup)

```
Map page (localhost:4040 or mundial.cthiebaud.com)
    │
    ├─ On load: restores from localStorage (if present)
    │   └─ No backend call — shows cached user immediately
    │
    └─ User clicks "sign in"
        └─ Opens popup → BACKEND/login
            │
            ├─ Popup: checkSession()
            │   ├─ Session exists + window.opener?
            │   │   └─ postMessage(mundial_auth) → close popup (NO new ONLINE_SESSIONS entry)
            │   ├─ Session exists + no opener?
            │   │   └─ Show signed-in UI
            │   └─ No session → show Google Sign-In
            │
            └─ User clicks Google Sign-In in popup
                └─ POST /api/auth/google {credential}
                    ├─ Creates ONLINE_SESSIONS[sid]
                    ├─ Sets Flask session cookie (on backend origin)
                    ├─ Emits WebSocket 'user_login'
                    └─ Popup: postMessage({type: 'mundial_auth', user, admin, sid}) → close
                        └─ Map page: stores in localStorage, shows signed-in UI
```

**One session created** (on the backend origin). The map page has no Flask cookie — it relies on `localStorage`.

---

## Logout flows

### Logout from admin page

```
Admin page: click "Sign out"
    └─ POST /api/auth/logout (with cookies)
        ├─ Backend: session.pop("user") — clears Flask cookie
        ├─ Backend: ONLINE_SESSIONS.pop(sid)
        ├─ Backend: emits WebSocket 'user_logout' {user, sid}
        └─ Admin page: showSignedOut()
```

### Logout from map page

```
Map page: click "sign out"
    └─ POST /api/auth/logout {sid, email} (body, not cookies — different origin)
        ├─ Backend: ONLINE_SESSIONS.pop(sid)
        ├─ Backend: emits WebSocket 'user_logout' {user, sid}
        └─ Map page: removes localStorage, hides signed-in UI
```

Note: the map page sends `sid` and `email` in the request body because it cannot send the Flask session cookie (different origin). The Flask session on the backend origin is NOT cleared by this — only the `ONLINE_SESSIONS` entry is removed.

---

## Session identity model

Sessions are scoped by **browser × backend domain**:

| Browser | Backend domain | Cookie jar | Result |
|---|---|---|---|
| Chrome | `localhost:5002` | Cookie A | Session 1 |
| Chrome | `ngrok-free.dev` | Cookie B | Session 2 (independent) |
| Firefox | `localhost:5002` | Cookie C | Session 3 (independent) |
| Safari | `localhost:5002` | Cookie D | Session 4 (independent) |

Within the same browser and domain:
- **Admin page + login popup** share the same Flask cookie → same session
- **Multiple admin tabs** share the same Flask cookie → same session (one `ONLINE_SESSIONS` entry)
- **Map page** uses `localStorage`, not the Flask cookie, but the login popup runs on the backend origin, so signing in from the map page creates/reuses the Flask session on the backend origin

### What counts as "one session"

Each call to `POST /api/auth/google` creates exactly one `ONLINE_SESSIONS` entry. In the same browser on the same backend domain, this happens once — subsequent pages detect the existing Flask session via `GET /api/auth/me` and reuse it.

---

## WebSocket events

All events are broadcast to every connected WebSocket client.

| Event | When | Payload | Admin page reaction |
|---|---|---|---|
| `user_login` | `POST /api/auth/google` succeeds | `{email, name, picture, last_login, device, sid}` | Add to `allUsers` + `onlineSessions`, re-render table |
| `user_logout` | `POST /api/auth/logout` succeeds | `{email, name, picture, sid}` | Remove session from `onlineSessions`, re-render. If `sid === mySid` → switch to signed-out UI |
| `user_kicked` | Admin clicks "kick" or "kick all" | `{email, sid?}` | Remove session(s), re-render. If own session → sign out |
| `user_deleted` | Admin clicks "delete" | `{email}` | Remove from `allUsers` + `onlineSessions`, re-render. If own email → sign out |

---

## Known issues and edge cases

### Ghost sessions (after backend restart)

**Cause:** `ONLINE_SESSIONS` is in-memory and lost on restart. Flask session cookies (signed, stored client-side) survive the restart if `FLASK_SECRET` is stable (currently `os.urandom(32)` by default — changes on every restart).

**Symptom:** The map page shows "signed in" (from `localStorage`) but the backend has no `ONLINE_SESSIONS` entry. The admin page may show "signed in" (from a still-valid Flask cookie) but the user doesn't appear in the users table.

**Current behavior:** Logout from a ghost session logs a `WARNING: LOGOUT with no matching session`. The user must sign out and sign back in to create a fresh `ONLINE_SESSIONS` entry.

**Possible fix:** When `/api/auth/me` detects a valid Flask session with an `sid` not in `ONLINE_SESSIONS`, re-register the session automatically.

### Map page stale localStorage

**Cause:** The map page restores auth from `localStorage` on load without verifying with the backend. If the session was logged out elsewhere or the backend restarted, the map page still shows "signed in".

**Current behavior:** The user appears signed in but any backend call requiring auth will fail. Clicking "sign out" clears `localStorage`.

**Possible fix:** On load, if `localStorage` has auth data, ping `GET /api/auth/me` to verify the session is still valid. If not, clear `localStorage` and show "sign in".

### Popup auto-close reuses session without re-registering

**Cause:** When the login popup detects an existing Flask session (`checkSession` + `window.opener`), it sends `postMessage` and closes without calling `POST /api/auth/google`. No new `ONLINE_SESSIONS` entry is created.

**Impact:** If `ONLINE_SESSIONS` was cleared (backend restart) but the Flask cookie survived, the popup auto-closes and the map page shows "signed in", but the session is not tracked.

**Possible fix:** When `checkSession` finds a session with `tracked=False` (sid not in `ONLINE_SESSIONS`), re-register it by calling a new endpoint or re-POSTing to `/api/auth/google`.

### Flask cookie not cleared on map page logout

**Cause:** The map page sends `{sid, email}` in the POST body (different origin, no cookies). The backend removes the `ONLINE_SESSIONS` entry but `session.pop("user")` pops from the *request's* Flask session — which belongs to whichever cookie was sent. Since the map page can't send the backend's cookie, the Flask session on the backend origin is not cleared.

**Impact:** After logging out from the map page, opening `localhost:5002/login` directly still shows "signed in" (Flask cookie intact). The `ONLINE_SESSIONS` entry is gone, but the cookie persists.

---

## Admin page actions

| Button | Scope | Effect |
|---|---|---|
| **kick** (per device) | One `ONLINE_SESSIONS` entry | Removes that session, emits `user_kicked {email, sid}` |
| **kick all** (per user) | All `ONLINE_SESSIONS` entries for that email | Removes all, emits `user_kicked {email}` |
| **delete** (per user) | All sessions + `users.json` entry | Kicks all sessions, removes from persistent user list, emits `user_kicked` + `user_deleted` |

Self-protection:
- **kick** is disabled on the admin's own session (`sid === mySid`)
- **kick all** is disabled if the admin has no other sessions to kick
- **delete** is disabled on the admin's own user

---

## Persistence summary

| Data | Storage | Survives restart? | Survives browser close? |
|---|---|---|---|
| `ONLINE_SESSIONS` | Python dict (RAM) | No | N/A (server-side) |
| Flask session cookie | Signed cookie (browser) | Only if `FLASK_SECRET` is stable | Yes (session cookie) |
| `localStorage` (map) | Browser storage | N/A (client-side) | Yes |
| `users.json` | File on disk | Yes | N/A (server-side) |
