"""
backend.py — Flask backend for the Mundial app.

- Polls API-Football every 60s when polling is enabled (admin toggle)
- Also fetches events per live WC fixture each tick
- Pushes live fixtures (with events) to clients via WebSocket ('live_update')
- Saves each poll to polls/ directory for later inspection
- GET /api/live returns latest stored data (no API call)
- GET /api/lineups/<id> fetches directly (lineups don't change mid-match)
- Google Sign-In authentication
- Admin page with live WebSocket updates on login/logout

Usage:
    export API_FOOTBALL_KEY="your-key"
    python3 backend.py

    # Against local mock server:
    export API_FOOTBALL_KEY="mock"
    export API_FOOTBALL_URL="http://localhost:5003"
    python3 backend.py

WebSocket events:
    server → client: 'live_update'   [fixtures]       — every 60s when polling is on
    server → client: 'poll_status'   {active: bool}   — when admin toggles polling
    server → client: 'user_login'    {user}
    server → client: 'user_logout'   {user}
    server → client: 'user_kicked'   {email, sid}
"""

import os, time, sys, json, uuid, re, logging
from pathlib import Path
from flask import Flask, jsonify, request, session, send_file
from flask_socketio import SocketIO

log = logging.getLogger("mundial")
log.setLevel(logging.DEBUG)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
log.addHandler(_sh)
_fh = logging.FileHandler(Path(__file__).parent / "backend.log")
_fh.setFormatter(_fmt)
log.addHandler(_fh)

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
if not API_KEY:
    print("Set API_FOOTBALL_KEY environment variable first.")
    sys.exit(1)

API_BASE = os.environ.get("API_FOOTBALL_URL", "https://v3.football.api-sports.io")
GOOGLE_CLIENT_ID = "657438044008-qddq7m5mgk59k8qnhjpd6dalndqqb50e.apps.googleusercontent.com"
ADMIN_EMAILS = {"christophe.t60@gmail.com"}

import requests as req

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(32))
socketio = SocketIO(app, cors_allowed_origins="*")

SERVER_DIR = Path(__file__).parent
USERS_FILE = SERVER_DIR / "users.json"
ONLINE_SESSIONS = {}  # session_id → {email, user, device, time}

def _parse_device(ua):
    ua = ua or ""
    browser = "Unknown"
    ver = ""
    m = None
    if "Edg/" in ua:
        browser = "Edge"
        m = re.search(r"Edg/(\d+)", ua)
    elif "Chrome/" in ua:
        browser = "Chrome"
        m = re.search(r"Chrome/(\d+)", ua)
    elif "Safari/" in ua and "Chrome" not in ua:
        browser = "Safari"
        m = re.search(r"Version/(\d+)", ua)
    elif "Firefox/" in ua:
        browser = "Firefox"
        m = re.search(r"Firefox/(\d+)", ua)
    if m:
        ver = " " + m.group(1)
    os_name = "Unknown"
    if "Macintosh" in ua: os_name = "macOS"
    elif "Windows" in ua: os_name = "Windows"
    elif "iPhone" in ua: os_name = "iPhone"
    elif "iPad" in ua: os_name = "iPad"
    elif "Android" in ua: os_name = "Android"
    elif "Linux" in ua: os_name = "Linux"
    return f"{browser}{ver} / {os_name}"

def _load_users():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}

def _save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False))

# ── API-Football ─────────────────────────────────────────────────────────────

POLL_INTERVAL = 60  # seconds
POLL_ACTIVE = False
WC_ONLY = True
_poll_thread = None
POLLS_DIR = SERVER_DIR / "polls"
KNOWN_FIXTURE_IDS = []

def _load_latest_poll():
    if not POLLS_DIR.exists():
        return []
    files = sorted(POLLS_DIR.glob("*.json"))
    if not files:
        return []
    data = json.loads(files[-1].read_text())
    log.info("Loaded latest poll from %s", files[-1].name)
    return data.get("fixtures", [])

LATEST_FIXTURES = _load_latest_poll()

def api_get(path, params):
    url = f"{API_BASE}{path}"
    log.info("API REQUEST %s %s", path, params)
    r = req.get(url, headers={"x-apisports-key": API_KEY}, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("response", [])

def _save_poll(timestamp, fixtures, events_by_fixture, statistics_by_fixture):
    POLLS_DIR.mkdir(exist_ok=True)
    record = {
        "timestamp": timestamp,
        "fixtures": fixtures,
        "events": {str(k): v for k, v in events_by_fixture.items()},
        "statistics": {str(k): v for k, v in statistics_by_fixture.items()},
    }
    filename = POLLS_DIR / f"{timestamp.replace(':', '-')}.json"
    filename.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    log.debug("POLL saved to %s", filename.name)

def _fetch_fixture_detail(fid, path):
    try:
        return api_get(path, {"fixture": fid})
    except Exception as e:
        log.error("POLL %s error fixture %d: %s", path, fid, e)
        return None

def _discover_wc_fixtures():
    global KNOWN_FIXTURE_IDS
    fixtures = api_get("/fixtures", {"live": "all"})
    if WC_ONLY:
        matched = [f for f in fixtures if f["league"]["name"] == "World Cup"]
    else:
        matched = fixtures[:2]
    ids = [f["fixture"]["id"] for f in matched]
    KNOWN_FIXTURE_IDS = ids
    label = "WC" if WC_ONLY else "all"
    log.info("DISCOVERY (%s) → %d live fixtures, %d matched: %s", label, len(fixtures), len(ids), ids)
    socketio.emit("poll_status", {"active": POLL_ACTIVE, "fixtures": KNOWN_FIXTURE_IDS, "wc_only": WC_ONLY})
    return ids

def _poll_loop():
    global LATEST_FIXTURES, POLL_ACTIVE
    log.info("POLL started (every %ds)", POLL_INTERVAL)
    try:
        _discover_wc_fixtures()
    except Exception as e:
        log.error("POLL discovery error: %s", e)
    if not KNOWN_FIXTURE_IDS:
        log.warning("POLL no WC fixtures found, stopping")
        POLL_ACTIVE = False
        socketio.emit("poll_status", {"active": False, "fixtures": []})
        return
    while POLL_ACTIVE:
        try:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            wc = []
            events_by_fixture = {}
            statistics_by_fixture = {}
            for fid in KNOWN_FIXTURE_IDS:
                fixture_data = _fetch_fixture_detail(fid, "/fixtures")
                if fixture_data and len(fixture_data) > 0:
                    wc.append(fixture_data[0])
                events = _fetch_fixture_detail(fid, "/fixtures/events")
                if events is not None:
                    events_by_fixture[fid] = events
                stats = _fetch_fixture_detail(fid, "/fixtures/statistics")
                if stats is not None:
                    statistics_by_fixture[fid] = stats
            for f in wc:
                fid = f["fixture"]["id"]
                if fid in events_by_fixture:
                    f["events"] = events_by_fixture[fid]
                if fid in statistics_by_fixture:
                    f["statistics"] = statistics_by_fixture[fid]
            LATEST_FIXTURES = wc
            _save_poll(ts, wc, events_by_fixture, statistics_by_fixture)
            log.info("POLL → %d WC fixtures, %d API calls, emitting live_update",
                     len(wc), len(KNOWN_FIXTURE_IDS) * 3)
            socketio.emit("live_update", wc)
        except Exception as e:
            log.error("POLL error: %s", e)
        socketio.sleep(POLL_INTERVAL)
    log.info("POLL stopped")

def start_polling():
    global POLL_ACTIVE, _poll_thread
    if POLL_ACTIVE:
        return False
    POLL_ACTIVE = True
    _poll_thread = socketio.start_background_task(_poll_loop)
    log.info("POLL toggled ON")
    return True

def stop_polling():
    global POLL_ACTIVE
    if not POLL_ACTIVE:
        return False
    POLL_ACTIVE = False
    log.info("POLL toggled OFF")
    socketio.emit("poll_status", {"active": False, "fixtures": []})
    return True

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        origin = request.headers.get("Origin", "*")
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

@app.after_request
def cors(response):
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/api/poll/active")
def poll_active():
    return jsonify({"active": POLL_ACTIVE, "fixtures": KNOWN_FIXTURE_IDS})

@app.route("/api/live")
def live():
    log.info("GET /api/live → returning %d stored fixtures", len(LATEST_FIXTURES))
    return jsonify(LATEST_FIXTURES)

@app.route("/api/lineups/<int:fixture_id>")
def lineups(fixture_id):
    data = api_get("/fixtures/lineups", {"fixture": fixture_id})
    log.info("GET /api/lineups/%d → %d teams", fixture_id, len(data))
    return jsonify(data)

@app.route("/api/admin/poll/start", methods=["POST"])
def admin_poll_start():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    started = start_polling()
    return jsonify({"ok": True, "started": started, "already_running": not started})

@app.route("/api/admin/poll/stop", methods=["POST"])
def admin_poll_stop():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    stopped = stop_polling()
    return jsonify({"ok": True, "stopped": stopped, "was_running": stopped})

@app.route("/api/admin/poll/status")
def admin_poll_status():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    poll_count = len(list(POLLS_DIR.glob("*.json"))) if POLLS_DIR.exists() else 0
    return jsonify({
        "active": POLL_ACTIVE,
        "wc_only": WC_ONLY,
        "fixtures": KNOWN_FIXTURE_IDS,
        "fixtures_count": len(LATEST_FIXTURES),
        "saved_polls": poll_count,
    })

@app.route("/api/admin/poll/wc-filter", methods=["POST"])
def admin_poll_wc_filter():
    global WC_ONLY
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    WC_ONLY = not WC_ONLY
    log.info("WC filter toggled: %s", "ON" if WC_ONLY else "OFF")
    return jsonify({"ok": True, "wc_only": WC_ONLY})

@app.route("/api/admin/poll/discover", methods=["POST"])
def admin_poll_discover():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    try:
        ids = _discover_wc_fixtures()
        return jsonify({"ok": True, "fixtures": ids})
    except Exception as e:
        log.error("DISCOVERY error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/polls")
def admin_polls_list():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    if not POLLS_DIR.exists():
        return jsonify([])
    files = sorted(POLLS_DIR.glob("*.json"), reverse=True)
    return jsonify([f.stem for f in files])

@app.route("/api/admin/polls/<name>")
def admin_polls_get(name):
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    path = POLLS_DIR / f"{name}.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(path.read_text()))

# ── Auth ─────────────────────────────────────────────────────────────────────

@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    token = request.json.get("credential")
    if not token:
        return jsonify({"error": "missing credential"}), 400

    r = req.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": token}, timeout=5)
    if r.status_code != 200:
        return jsonify({"error": "invalid token"}), 401

    info = r.json()
    if info.get("aud") != GOOGLE_CLIENT_ID:
        return jsonify({"error": "wrong audience"}), 401

    user = {
        "email": info["email"],
        "name": info.get("name", ""),
        "picture": info.get("picture", ""),
        "last_login": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    users = _load_users()
    users[user["email"]] = user
    _save_users(users)

    sid = str(uuid.uuid4())[:8]
    session["user"] = user
    session["sid"] = sid
    device = _parse_device(request.headers.get("User-Agent"))
    ONLINE_SESSIONS[sid] = {
        "email": user["email"], "user": user, "device": device,
        "time": user["last_login"], "sid": sid,
    }
    log.info("LOGIN  %s [%s] sid=%s", user["email"], device, sid)
    socketio.emit("user_login", {**user, "device": device, "sid": sid})

    return jsonify({"user": user, "admin": user["email"] in ADMIN_EMAILS, "sid": sid})

@app.route("/api/auth/me")
def auth_me():
    user = session.get("user")
    sid = session.get("sid")
    if not user:
        log.debug("GET /api/auth/me → no session")
        return jsonify({"user": None}), 200
    tracked = sid in ONLINE_SESSIONS if sid else False
    log.debug("GET /api/auth/me → %s sid=%s tracked=%s", user["email"], sid, tracked)
    return jsonify({"user": user, "admin": user["email"] in ADMIN_EMAILS, "sid": sid})

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    user = session.pop("user", None)
    data = request.json or {}
    sid = data.get("sid")
    email = data.get("email")
    logged_out_sid = None
    if sid and sid in ONLINE_SESSIONS:
        entry = ONLINE_SESSIONS.pop(sid)
        user = entry["user"]
        logged_out_sid = sid
    elif email:
        for k, v in list(ONLINE_SESSIONS.items()):
            if v["email"] == email:
                ONLINE_SESSIONS.pop(k)
                user = v["user"]
                logged_out_sid = k
                break
    if user:
        log.info("LOGOUT %s sid=%s (online: %d remaining)", user.get("email", "?"), logged_out_sid, len(ONLINE_SESSIONS))
        socketio.emit("user_logout", {**user, "sid": logged_out_sid})
    else:
        log.warning("LOGOUT with no matching session (sid=%s email=%s)", sid, email)
    return jsonify({"ok": True})

# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/login")
def login_page():
    return send_file(SERVER_DIR / "login.html")

@app.route("/admin")
def admin_page():
    return send_file(SERVER_DIR / "admin.html")

@app.route("/api/admin/users")
def admin_users():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_load_users())

@app.route("/api/admin/online")
def admin_online():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(list(ONLINE_SESSIONS.values()))

@app.route("/api/admin/kick", methods=["POST"])
def admin_kick():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    sid = request.json.get("sid")
    email = request.json.get("email")
    if sid and sid in ONLINE_SESSIONS:
        entry = ONLINE_SESSIONS.pop(sid)
        log.info("KICK   %s sid=%s (online: %d remaining)", entry["email"], sid, len(ONLINE_SESSIONS))
        socketio.emit("user_kicked", {"email": entry["email"], "sid": sid})
    elif email:
        count = sum(1 for v in ONLINE_SESSIONS.values() if v["email"] == email)
        for k, v in list(ONLINE_SESSIONS.items()):
            if v["email"] == email:
                ONLINE_SESSIONS.pop(k)
        log.info("KICK   %s (all %d sessions, online: %d remaining)", email, count, len(ONLINE_SESSIONS))
        socketio.emit("user_kicked", {"email": email})
    else:
        return jsonify({"error": "missing sid or email"}), 400
    return jsonify({"ok": True})

@app.route("/api/admin/delete", methods=["POST"])
def admin_delete():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    email = request.json.get("email")
    if not email:
        return jsonify({"error": "missing email"}), 400
    for k, v in list(ONLINE_SESSIONS.items()):
        if v["email"] == email:
            ONLINE_SESSIONS.pop(k)
    socketio.emit("user_kicked", {"email": email})
    users = _load_users()
    if email in users:
        del users[email]
        _save_users(users)
    log.info("DELETE %s (removed from users.json + all sessions)", email)
    socketio.emit("user_deleted", {"email": email})
    return jsonify({"ok": True})

if __name__ == "__main__":
    log.info("Proxy → %s", API_BASE)
    log.info("Admin emails: %s", ADMIN_EMAILS)
    socketio.run(app, host="0.0.0.0", port=5002, allow_unsafe_werkzeug=True)
