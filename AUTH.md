# AUTH.md — AuthManager

`auth.py` is a self-contained Google Sign-In + session management module for Flask/SocketIO apps. It has no dependency on the rest of `mundial-server` and can be dropped into any project.

## Usage

```python
from auth import AuthManager

auth = AuthManager(socketio, SERVER_DIR / "users.json", GOOGLE_CLIENT_ID, ADMIN_EMAILS)
app.register_blueprint(auth.blueprint)
```

Guard admin routes anywhere in the app:

```python
_, err = auth.require_admin()
if err: return err
```

Access active sessions:

```python
auth.online_sessions  # dict: sid → {email, user, device, time, sid}
```

## Constructor

```python
AuthManager(socketio, users_file, google_client_id, admin_emails)
```

| Parameter | Type | Description |
|---|---|---|
| `socketio` | `SocketIO` | Flask-SocketIO instance — used to emit login/logout/kick events |
| `users_file` | `str` or `Path` | Path to `users.json` (auto-created). `login.html` is expected in the same directory |
| `google_client_id` | `str` | Google OAuth 2.0 client ID |
| `admin_emails` | `set[str]` | Emails granted admin access |

## Endpoints registered

### Auth

| Route | Method | Description |
|---|---|---|
| `/login` | GET | Serve `login.html` from the same directory as `users_file` |
| `/api/auth/google` | POST | Verify Google ID token, create session — body: `{credential}` |
| `/api/auth/me` | GET | Return current user from session |
| `/api/auth/logout` | POST | End session — body: `{sid}` or `{email}` |

### Admin (require admin email)

| Route | Method | Description |
|---|---|---|
| `/api/admin/users` | GET | All registered users from `users.json` |
| `/api/admin/online` | GET | Currently active sessions with device info |
| `/api/admin/kick` | POST | Force-logout by `{sid}` (one session) or `{email}` (all sessions) |
| `/api/admin/delete` | POST | Delete user from `users.json` + kick all their sessions — body: `{email}` |

## WebSocket events emitted

| Event | Payload | When |
|---|---|---|
| `user_login` | `{email, name, picture, last_login, device, sid}` | Successful sign-in |
| `user_logout` | `{email, name, picture, sid}` | Logout |
| `user_kicked` | `{email, sid?}` | Kick — `sid` present means single session; absent means all sessions for that email |
| `user_deleted` | `{email}` | User deleted from `users.json` |

## Sign-in flow (popup)

The main map page uses a **popup** to sign in — the Google button renders on the backend origin (port 5002 or ngrok), avoiding origin mismatch issues.

1. User clicks "sign in" on the map page
2. A popup opens to `BACKEND/login`
3. User signs in with Google in the popup
4. Popup sends `postMessage({type: 'mundial_auth', user, admin, sid})` to the parent
5. Popup closes; parent stores `{user, admin, sid}` in `localStorage`
6. Admin page receives a `user_login` WebSocket event in real time

## Cross-origin auth (localStorage)

The map page and backend run on different origins. Since cross-origin cookies don't travel, the frontend stores `{user, admin, sid}` in `localStorage` after sign-in. The session ID is also stored separately as `mundial_sid` for logout/kick matching.

## Session persistence

Sessions use Flask's signed-cookie mechanism. The signing key is stable across restarts: if `FLASK_SECRET` env var is set it is used; otherwise a random key is auto-generated and saved to `.flask_secret` on first run. Authenticated users stay logged in after a server restart — no Redis or database needed.

## Admin pages

`auth.py` ships with a ready-made admin UI in `admin_auth.html`, served at `/admin-auth`:

- Activity feed — real-time login/logout toasts via WebSocket
- Users table — one row per registered user, sorted online-first
- Per-session kick button; per-user "kick all" and "delete" buttons
- Self-protection: kick/delete buttons are disabled for your own session

To reuse in another project: copy `admin_auth.html` alongside `auth.py` and add the route:

```python
@app.route("/admin-auth")
def admin_auth_page():
    return send_file(SERVER_DIR / "admin_auth.html")
```

The page navigates to `/admin` (fixtures admin). Remove or update that link if the host app has a different admin URL.

## Per-device session tracking

Each login creates a unique 8-character session ID and records the browser/OS parsed from the `User-Agent` header (e.g. "Chrome 124 / macOS"). `admin_auth.html` shows one row per active session with individual kick buttons.

- Kick by `sid` → logs out that one browser tab
- Kick by `email` → logs out all sessions for that user

## Google Cloud Console setup

Create a project at [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials) and add **Authorized JavaScript origins**:

| Origin | Purpose |
|---|---|
| `http://localhost:5002` | Local dev (backend-served login/admin pages) |
| `https://xxx.ngrok-free.dev` | ngrok tunnel |
| `https://your-production-domain.com` | Production (if applicable) |

`http://localhost:4040` is **not** needed — the popup runs on the backend origin, not the frontend origin.

**Client ID (mundial project):** `657438044008-qddq7m5mgk59k8qnhjpd6dalndqqb50e.apps.googleusercontent.com`

## Admin access

Controlled by the `admin_emails` set passed to the constructor. In `backend.py`: `ADMIN_EMAILS = {"christophe.t60@gmail.com"}`.

## Auth bar auto-hide

The map page hides the auth bar by default. On load it pings the backend (3-second timeout). If the backend is unreachable, the auth bar stays hidden and the page works exactly as before — no broken UI.
