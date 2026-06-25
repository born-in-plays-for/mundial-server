"""
backend.py — Flask backend for the Mundial app.

- Two independent loops controlled by admin:
  - DISCOVER: polls API-Football for live fixtures (every 120s)
  - TRACK: fetches updates for known fixtures (every 60s)
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
    server → client: 'live_update'   [fixtures]       — every 60s when tracking is on
    server → client: 'poll_status'   {discovering, tracking, fixtures, wc_only}
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

def _stable_secret_key():
    env = os.environ.get("FLASK_SECRET")
    if env:
        return env
    key_file = Path(__file__).parent / ".flask_secret"
    if key_file.exists():
        return key_file.read_bytes()
    key = os.urandom(32)
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    return key

app.secret_key = _stable_secret_key()
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

DISCOVER_INTERVAL = 120  # seconds
TRACK_INTERVAL = 60     # seconds
DISCOVER_ACTIVE = False
TRACK_ACTIVE = False
WC_ONLY = True
_discover_thread = None
_track_thread = None
POLLS_DIR = SERVER_DIR / "polls"
KNOWN_FIXTURES = {}  # {fid: {"tracked": bool, "label": str, "status": str}}
FIXTURE_DATA = {}    # {fid: last known fixture dict from API}
ACTIVE_STATUSES = {"1H", "2H", "ET", "P"}

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

import time as _time
_STANDINGS_CACHE = {"data": None, "ts": 0}
_STANDINGS_TTL = 300  # 5 minutes

def _fetch_standings():
    now = _time.time()
    if _STANDINGS_CACHE["data"] and now - _STANDINGS_CACHE["ts"] < _STANDINGS_TTL:
        return _STANDINGS_CACHE["data"]
    try:
        raw = api_get("/standings", {"league": 1, "season": 2026})
        groups = raw[0]["league"]["standings"] if raw else []
        _STANDINGS_CACHE["data"] = groups
        _STANDINGS_CACHE["ts"] = now
        log.info("Fetched standings: %d groups", len(groups))
    except Exception as e:
        log.warning("Failed to fetch standings: %s", e)
    return _STANDINGS_CACHE["data"] or []

_RESULTS_CACHE = {"data": None, "ts": 0}

def _fetch_group_results():
    now = _time.time()
    if _RESULTS_CACHE["data"] and now - _RESULTS_CACHE["ts"] < _STANDINGS_TTL:
        return _RESULTS_CACHE["data"]
    try:
        fixtures = []
        for rd in range(1, 4):
            fixtures += api_get("/fixtures", {"league": 1, "season": 2026, "round": f"Group Stage - {rd}"})
        finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
        _RESULTS_CACHE["data"] = finished
        _RESULTS_CACHE["ts"] = now
        log.info("Fetched group results: %d finished fixtures", len(finished))
    except Exception as e:
        log.warning("Failed to fetch group results: %s", e)
    return _RESULTS_CACHE["data"] or []

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

def _emit_status():
    socketio.emit("poll_status", {
        "discovering": DISCOVER_ACTIVE,
        "tracking": TRACK_ACTIVE,
        "fixtures": {
            str(fid): info for fid, info in KNOWN_FIXTURES.items()
        },
        "wc_only": WC_ONLY,
    })

def _fixture_label(f):
    home = f.get("teams", {}).get("home", {}).get("name", "?")
    away = f.get("teams", {}).get("away", {}).get("name", "?")
    return f"{home} vs {away}"

def _discover_wc_fixtures():
    global KNOWN_FIXTURES
    had_tracked = any(info["tracked"] for info in KNOWN_FIXTURES.values())
    fixtures = api_get("/fixtures", {"live": "all"})
    if WC_ONLY:
        matched = [f for f in fixtures if f["league"]["name"] == "World Cup"]
    else:
        matched = fixtures[:2]
    new_ids = {f["fixture"]["id"] for f in matched}
    for f in matched:
        fid = f["fixture"]["id"]
        if fid not in KNOWN_FIXTURES:
            KNOWN_FIXTURES[fid] = {
                "tracked": TRACK_ACTIVE,
                "label": _fixture_label(f),
                "status": f["fixture"]["status"]["short"],
            }
        else:
            KNOWN_FIXTURES[fid]["label"] = _fixture_label(f)
            KNOWN_FIXTURES[fid]["status"] = f["fixture"]["status"]["short"]
        FIXTURE_DATA[fid] = f
    for fid in list(KNOWN_FIXTURES):
        if fid not in new_ids:
            del KNOWN_FIXTURES[fid]
            FIXTURE_DATA.pop(fid, None)
    label = "WC" if WC_ONLY else "all"
    ids = list(new_ids)
    log.info("DISCOVER (%s) → %d live fixtures, %d matched: %s", label, len(fixtures), len(ids), ids)
    has_tracked = any(info["tracked"] for info in KNOWN_FIXTURES.values())
    if has_tracked and not had_tracked and TRACK_ACTIVE and _track_thread is None:
        _start_track_thread()
    elif not has_tracked and had_tracked and _track_thread is not None:
        _stop_track_thread()
    _emit_status()
    return ids

def _discover_loop():
    global DISCOVER_ACTIVE
    log.info("DISCOVER loop started (every %ds)", DISCOVER_INTERVAL)
    while DISCOVER_ACTIVE:
        try:
            _discover_wc_fixtures()
        except Exception as e:
            log.error("DISCOVER error: %s", e)
        socketio.sleep(DISCOVER_INTERVAL)
    log.info("DISCOVER loop stopped")

def _track_loop():
    global LATEST_FIXTURES, _track_thread
    log.info("TRACK loop started (every %ds)", TRACK_INTERVAL)
    while TRACK_ACTIVE:
        tracked_ids = [fid for fid, info in KNOWN_FIXTURES.items() if info["tracked"]]
        if not tracked_ids:
            log.debug("TRACK tick — no tracked fixtures")
            socketio.sleep(TRACK_INTERVAL)
            continue
        try:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            events_by_fixture = {}
            statistics_by_fixture = {}
            api_calls = 0
            for fid in tracked_ids:
                try:
                    fixture_data = api_get("/fixtures", {"id": fid})
                    api_calls += 1
                except Exception as e:
                    log.error("TRACK /fixtures error fixture %d: %s", fid, e)
                    fixture_data = None
                if fixture_data and len(fixture_data) > 0:
                    f = fixture_data[0]
                    FIXTURE_DATA[fid] = f
                    status = f["fixture"]["status"]["short"]
                    if fid in KNOWN_FIXTURES:
                        KNOWN_FIXTURES[fid]["status"] = status
                    if status in ACTIVE_STATUSES:
                        events = _fetch_fixture_detail(fid, "/fixtures/events")
                        api_calls += 1
                        if events is not None:
                            events_by_fixture[fid] = events
                        stats = _fetch_fixture_detail(fid, "/fixtures/statistics")
                        api_calls += 1
                        if stats is not None:
                            statistics_by_fixture[fid] = stats
                    else:
                        log.info("TRACK fixture %d — skipping events/stats (status: %s)", fid, status)
            for fid, f in FIXTURE_DATA.items():
                if fid in events_by_fixture:
                    f["events"] = events_by_fixture[fid]
                if fid in statistics_by_fixture:
                    f["statistics"] = statistics_by_fixture[fid]
                f["_tracked"] = KNOWN_FIXTURES.get(fid, {}).get("tracked", False)
            all_fixtures = list(FIXTURE_DATA.values())
            LATEST_FIXTURES = all_fixtures
            tracked_fixtures = [FIXTURE_DATA[fid] for fid in tracked_ids if fid in FIXTURE_DATA]
            _save_poll(ts, tracked_fixtures, events_by_fixture, statistics_by_fixture)
            log.info("TRACK → %d tracked (%d total), %d API calls, emitting live_update",
                     len(tracked_ids), len(all_fixtures), api_calls)
            socketio.emit("live_update", all_fixtures)
            _emit_status()
        except Exception as e:
            log.error("TRACK error: %s", e)
        socketio.sleep(TRACK_INTERVAL)
    _track_thread = None
    log.info("TRACK loop stopped")

def _start_track_thread():
    global _track_thread
    if _track_thread is not None:
        return
    _track_thread = socketio.start_background_task(_track_loop)
    log.info("TRACK thread spawned")

def _stop_track_thread():
    global _track_thread
    _track_thread = None

def start_discovering():
    global DISCOVER_ACTIVE, _discover_thread
    if DISCOVER_ACTIVE:
        return False
    DISCOVER_ACTIVE = True
    _discover_thread = socketio.start_background_task(_discover_loop)
    log.info("DISCOVER toggled ON")
    _emit_status()
    return True

def stop_discovering():
    global DISCOVER_ACTIVE
    if not DISCOVER_ACTIVE:
        return False
    DISCOVER_ACTIVE = False
    log.info("DISCOVER toggled OFF")
    _emit_status()
    return True

def start_tracking():
    global TRACK_ACTIVE
    if TRACK_ACTIVE:
        return False
    TRACK_ACTIVE = True
    for info in KNOWN_FIXTURES.values():
        info["tracked"] = True
    log.info("TRACK toggled ON (%d fixtures set to tracked)", len(KNOWN_FIXTURES))
    if KNOWN_FIXTURES:
        _start_track_thread()
    else:
        log.info("TRACK armed — will start when fixtures are discovered")
    _emit_status()
    return True

def stop_tracking():
    global TRACK_ACTIVE
    if not TRACK_ACTIVE:
        return False
    TRACK_ACTIVE = False
    log.info("TRACK toggled OFF")
    _emit_status()
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
    return jsonify({"discovering": DISCOVER_ACTIVE, "tracking": TRACK_ACTIVE, "fixtures": list(KNOWN_FIXTURES.keys())})

@app.route("/api/live")
def live():
    log.info("GET /api/live → returning %d stored fixtures", len(LATEST_FIXTURES))
    return jsonify(LATEST_FIXTURES)

@app.route("/api/standings")
def standings():
    groups = _fetch_standings()
    log.info("GET /api/standings → %d groups", len(groups))
    return jsonify(groups)

@app.route("/api/group-results")
def group_results():
    results = _fetch_group_results()
    log.info("GET /api/group-results → %d fixtures", len(results))
    return jsonify(results)

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
    started = start_discovering()
    return jsonify({"ok": True, "started": started, "already_running": not started})

@app.route("/api/admin/poll/stop", methods=["POST"])
def admin_poll_stop():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    stopped = stop_discovering()
    return jsonify({"ok": True, "stopped": stopped, "was_running": stopped})

@app.route("/api/admin/track/start", methods=["POST"])
def admin_track_start():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    started = start_tracking()
    return jsonify({"ok": True, "started": started, "already_running": not started})

@app.route("/api/admin/track/stop", methods=["POST"])
def admin_track_stop():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    stopped = stop_tracking()
    return jsonify({"ok": True, "stopped": stopped, "was_running": stopped})

@app.route("/api/admin/track/fixture", methods=["POST"])
def admin_track_fixture():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    fid = request.json.get("fid")
    tracked = request.json.get("tracked")
    if fid is None or tracked is None:
        return jsonify({"error": "missing fid or tracked"}), 400
    fid = int(fid)
    if fid not in KNOWN_FIXTURES:
        return jsonify({"error": "unknown fixture"}), 404
    KNOWN_FIXTURES[fid]["tracked"] = bool(tracked)
    log.info("TRACK fixture %d → %s", fid, "on" if tracked else "off")
    if TRACK_ACTIVE and tracked and _track_thread is None:
        _start_track_thread()
    _emit_status()
    return jsonify({"ok": True})

@app.route("/api/admin/track/all", methods=["POST"])
def admin_track_all():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    tracked = bool(request.json.get("tracked", True))
    for info in KNOWN_FIXTURES.values():
        info["tracked"] = tracked
    log.info("TRACK all fixtures → %s", "on" if tracked else "off")
    if TRACK_ACTIVE and tracked and KNOWN_FIXTURES and _track_thread is None:
        _start_track_thread()
    _emit_status()
    return jsonify({"ok": True})

@app.route("/api/admin/poll/status")
def admin_poll_status():
    user = session.get("user")
    if not user or user["email"] not in ADMIN_EMAILS:
        return jsonify({"error": "forbidden"}), 403
    poll_count = len(list(POLLS_DIR.glob("*.json"))) if POLLS_DIR.exists() else 0
    return jsonify({
        "discovering": DISCOVER_ACTIVE,
        "tracking": TRACK_ACTIVE,
        "wc_only": WC_ONLY,
        "fixtures": {
            str(fid): info for fid, info in KNOWN_FIXTURES.items()
        },
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

class _WsUpgradeFilter(logging.Filter):
    def filter(self, record):
        return "write() before start_response" not in record.getMessage()

logging.getLogger("werkzeug").addFilter(_WsUpgradeFilter())

if __name__ == "__main__":
    log.info("Proxy → %s", API_BASE)
    log.info("Admin emails: %s", ADMIN_EMAILS)
    socketio.run(app, host="0.0.0.0", port=5002, allow_unsafe_werkzeug=True)
