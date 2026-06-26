"""
auth.py — reusable Google Sign-In + session management for Flask/SocketIO apps.

Usage:
    from auth import AuthManager
    auth = AuthManager(socketio, SERVER_DIR / "users.json", GOOGLE_CLIENT_ID, ADMIN_EMAILS)
    app.register_blueprint(auth.blueprint)

    # Guard admin routes:
    _, err = auth.require_admin()
    if err: return err

Registers:
    POST /api/auth/google    — verify Google ID token, create session
    GET  /api/auth/me        — return current session user
    POST /api/auth/logout    — end session
    GET  /api/admin/users    — all registered users (admin only)
    GET  /api/admin/online   — currently online sessions (admin only)
    POST /api/admin/kick     — remove a session (admin only)
    POST /api/admin/delete   — remove user + all sessions (admin only)
    GET  /login              — serve login.html

WebSocket events emitted:
    user_login    {email, name, picture, device, sid}
    user_logout   {email, name, picture, sid}
    user_kicked   {email, sid?}
    user_deleted  {email}
"""

import json, uuid, re, time, logging
import requests as req
from pathlib import Path
from flask import Blueprint, jsonify, request, session, send_file

log = logging.getLogger("mundial")


class AuthManager:
    def __init__(self, socketio, users_file, google_client_id, admin_emails):
        self.socketio = socketio
        self.users_file = Path(users_file)
        self.google_client_id = google_client_id
        self.admin_emails = admin_emails
        self.online_sessions = {}  # sid → {email, user, device, time, sid}
        self.blueprint = self._create_blueprint()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def require_admin(self):
        user = session.get("user")
        if not user or user["email"] not in self.admin_emails:
            return None, (jsonify({"error": "forbidden"}), 403)
        return user, None

    def _load_users(self):
        if self.users_file.exists():
            return json.loads(self.users_file.read_text())
        return {}

    def _save_users(self, users):
        self.users_file.write_text(json.dumps(users, indent=2, ensure_ascii=False))

    def _parse_device(self, ua):
        ua = ua or ""
        browser, ver, m = "Unknown", "", None
        if "Edg/" in ua:
            browser, m = "Edge", re.search(r"Edg/(\d+)", ua)
        elif "Chrome/" in ua:
            browser, m = "Chrome", re.search(r"Chrome/(\d+)", ua)
        elif "Safari/" in ua and "Chrome" not in ua:
            browser, m = "Safari", re.search(r"Version/(\d+)", ua)
        elif "Firefox/" in ua:
            browser, m = "Firefox", re.search(r"Firefox/(\d+)", ua)
        if m:
            ver = " " + m.group(1)
        os_name = "Unknown"
        if "Macintosh" in ua:   os_name = "macOS"
        elif "Windows" in ua:   os_name = "Windows"
        elif "iPhone" in ua:    os_name = "iPhone"
        elif "iPad" in ua:      os_name = "iPad"
        elif "Android" in ua:   os_name = "Android"
        elif "Linux" in ua:     os_name = "Linux"
        return f"{browser}{ver} / {os_name}"

    # ── Blueprint ─────────────────────────────────────────────────────────────

    def _create_blueprint(self):
        bp = Blueprint("auth", __name__)

        @bp.route("/login")
        def login_page():
            return send_file(self.users_file.parent / "login.html")

        @bp.route("/api/auth/google", methods=["POST"])
        def auth_google():
            token = request.json.get("credential")
            if not token:
                return jsonify({"error": "missing credential"}), 400
            r = req.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": token}, timeout=5)
            if r.status_code != 200:
                return jsonify({"error": "invalid token"}), 401
            info = r.json()
            if info.get("aud") != self.google_client_id:
                return jsonify({"error": "wrong audience"}), 401
            user = {
                "email": info["email"],
                "name": info.get("name", ""),
                "picture": info.get("picture", ""),
                "last_login": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            users = self._load_users()
            users[user["email"]] = user
            self._save_users(users)
            sid = str(uuid.uuid4())[:8]
            session["user"] = user
            session["sid"] = sid
            device = self._parse_device(request.headers.get("User-Agent"))
            self.online_sessions[sid] = {
                "email": user["email"], "user": user, "device": device,
                "time": user["last_login"], "sid": sid,
            }
            log.info("LOGIN  %s [%s] sid=%s", user["email"], device, sid)
            self.socketio.emit("user_login", {**user, "device": device, "sid": sid})
            return jsonify({"user": user, "admin": user["email"] in self.admin_emails, "sid": sid})

        @bp.route("/api/auth/me")
        def auth_me():
            user = session.get("user")
            sid = session.get("sid")
            if not user:
                log.debug("GET /api/auth/me → no session")
                return jsonify({"user": None}), 200
            log.debug("GET /api/auth/me → %s sid=%s online=%s", user["email"], sid, sid in self.online_sessions)
            return jsonify({"user": user, "admin": user["email"] in self.admin_emails, "sid": sid})

        @bp.route("/api/auth/logout", methods=["POST"])
        def auth_logout():
            user = session.pop("user", None)
            data = request.json or {}
            sid = data.get("sid")
            email = data.get("email")
            logged_out_sid = None
            if sid and sid in self.online_sessions:
                entry = self.online_sessions.pop(sid)
                user = entry["user"]
                logged_out_sid = sid
            elif email:
                for k, v in list(self.online_sessions.items()):
                    if v["email"] == email:
                        self.online_sessions.pop(k)
                        user = v["user"]
                        logged_out_sid = k
                        break
            if user:
                log.info("LOGOUT %s sid=%s (online: %d remaining)", user.get("email", "?"), logged_out_sid, len(self.online_sessions))
                self.socketio.emit("user_logout", {**user, "sid": logged_out_sid})
            else:
                log.warning("LOGOUT with no matching session (sid=%s email=%s)", sid, email)
            return jsonify({"ok": True})

        @bp.route("/api/admin/users")
        def admin_users():
            _, err = self.require_admin()
            if err: return err
            return jsonify(self._load_users())

        @bp.route("/api/admin/online")
        def admin_online():
            _, err = self.require_admin()
            if err: return err
            return jsonify(list(self.online_sessions.values()))

        @bp.route("/api/admin/kick", methods=["POST"])
        def admin_kick():
            _, err = self.require_admin()
            if err: return err
            sid = request.json.get("sid")
            email = request.json.get("email")
            if sid and sid in self.online_sessions:
                entry = self.online_sessions.pop(sid)
                log.info("KICK   %s sid=%s (online: %d remaining)", entry["email"], sid, len(self.online_sessions))
                self.socketio.emit("user_kicked", {"email": entry["email"], "sid": sid})
            elif email:
                count = sum(1 for v in self.online_sessions.values() if v["email"] == email)
                for k, v in list(self.online_sessions.items()):
                    if v["email"] == email:
                        self.online_sessions.pop(k)
                log.info("KICK   %s (all %d sessions, online: %d remaining)", email, count, len(self.online_sessions))
                self.socketio.emit("user_kicked", {"email": email})
            else:
                return jsonify({"error": "missing sid or email"}), 400
            return jsonify({"ok": True})

        @bp.route("/api/admin/delete", methods=["POST"])
        def admin_delete():
            _, err = self.require_admin()
            if err: return err
            email = request.json.get("email")
            if not email:
                return jsonify({"error": "missing email"}), 400
            for k, v in list(self.online_sessions.items()):
                if v["email"] == email:
                    self.online_sessions.pop(k)
            self.socketio.emit("user_kicked", {"email": email})
            users = self._load_users()
            if email in users:
                del users[email]
                self._save_users(users)
            log.info("DELETE %s (removed from users.json + all sessions)", email)
            self.socketio.emit("user_deleted", {"email": email})
            return jsonify({"ok": True})

        return bp
