"""
backend.py — Flask backend for the Mundial app.

- Two independent loops controlled by admin:
  - DISCOVER: polls API-Football for live fixtures (every 120s)
  - TRACK: fetches updates for known fixtures (every 60s)
- Pushes live fixtures (with events) to clients via WebSocket ('live_update')
- Saves each poll to polls/ directory for later inspection
- GET /api/live returns latest stored data (no API call)
- GET /api/lineups/<id> fetches directly (lineups don't change mid-match)
- Google Sign-In authentication (via auth.py)
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
    server → client: 'poll_status'   {discovering, fixtures, wc_only}
    server → client: 'user_login'    {user}
    server → client: 'user_logout'   {user}
    server → client: 'user_kicked'   {email, sid}
"""

import os, time, sys, json, logging
import requests as req
from pathlib import Path
from flask import Flask, jsonify, request, session, send_file
from flask_socketio import SocketIO
from auth import AuthManager

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
auth = AuthManager(socketio, SERVER_DIR / "users.json", GOOGLE_CLIENT_ID, ADMIN_EMAILS)
app.register_blueprint(auth.blueprint)

# ── API-Football ─────────────────────────────────────────────────────────────

class FixtureTracker:
    ACTIVE_STATUSES = {"1H", "2H", "ET", "P"}
    _CACHE_TTL = 300  # 5 minutes

    def __init__(self, socketio, server_dir):
        self.socketio = socketio
        self.polls_dir = server_dir / "polls"
        self.discover_interval = 120
        self.track_interval = 60
        self.discover_active = False
        self.track_active = True
        self.wc_only = True
        self._discover_thread = None
        self._track_thread = None
        self.known_fixtures = {}  # {fid: {"tracked": bool, "label": str, "status": str}}
        self.fixture_data = {}    # {fid: last known fixture dict from API}
        self._standings_cache = {"data": None, "ts": 0}
        self._results_cache = {"data": None, "ts": 0}
        self.latest_fixtures = self._load_latest_poll()

    # ── API ───────────────────────────────────────────────────────────────────

    def api_get(self, path, params):
        url = f"{API_BASE}{path}"
        log.info("API REQUEST %s %s", path, params)
        r = req.get(url, headers={"x-apisports-key": API_KEY}, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("response", [])

    def fetch_standings(self):
        now = time.time()
        if self._standings_cache["data"] and now - self._standings_cache["ts"] < self._CACHE_TTL:
            return self._standings_cache["data"]
        try:
            raw = self.api_get("/standings", {"league": 1, "season": 2026})
            groups = raw[0]["league"]["standings"] if raw else []
            self._standings_cache["data"] = groups
            self._standings_cache["ts"] = now
            log.info("Fetched standings: %d groups", len(groups))
        except Exception as e:
            log.warning("Failed to fetch standings: %s", e)
        return self._standings_cache["data"] or []

    def fetch_group_results(self):
        now = time.time()
        if self._results_cache["data"] and now - self._results_cache["ts"] < self._CACHE_TTL:
            return self._results_cache["data"]
        try:
            fixtures = []
            for rd in range(1, 4):
                fixtures += self.api_get("/fixtures", {"league": 1, "season": 2026, "round": f"Group Stage - {rd}"})
            finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
            self._results_cache["data"] = finished
            self._results_cache["ts"] = now
            log.info("Fetched group results: %d finished fixtures", len(finished))
        except Exception as e:
            log.warning("Failed to fetch group results: %s", e)
        return self._results_cache["data"] or []

    def _fetch_fixture_detail(self, fid, path):
        try:
            return self.api_get(path, {"fixture": fid})
        except Exception as e:
            log.error("POLL %s error fixture %d: %s", path, fid, e)
            return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _wc_filter(self, fixtures):
        if not self.wc_only:
            return fixtures
        return [f for f in fixtures if f.get("league", {}).get("name") == "World Cup"]

    def _load_latest_poll(self):
        if not self.polls_dir.exists():
            return []
        files = sorted(self.polls_dir.glob("*.json"))
        if not files:
            return []
        data = json.loads(files[-1].read_text())
        fixtures = self._wc_filter(data.get("fixtures", []))
        live = [f for f in fixtures if f["fixture"]["status"]["short"] in self.ACTIVE_STATUSES]
        log.info("Loaded latest poll from %s (%d live of %d)", files[-1].name, len(live), len(fixtures))
        return live

    def _save_poll(self, timestamp, fixtures, events_by_fixture, statistics_by_fixture):
        self.polls_dir.mkdir(exist_ok=True)
        record = {
            "timestamp": timestamp,
            "fixtures": fixtures,
            "events": {str(k): v for k, v in events_by_fixture.items()},
            "statistics": {str(k): v for k, v in statistics_by_fixture.items()},
        }
        filename = self.polls_dir / f"{timestamp.replace(':', '-')}.json"
        filename.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        log.debug("POLL saved to %s", filename.name)

    # ── Emit ──────────────────────────────────────────────────────────────────

    def emit_live_update(self):
        for f in self.latest_fixtures:
            fid = f["fixture"]["id"]
            f["_tracked"] = self.known_fixtures.get(fid, {}).get("tracked", False)
        self.socketio.emit("live_update", self.latest_fixtures)

    def emit_status(self):
        self.socketio.emit("poll_status", {
            "discovering": self.discover_active,
            "fixtures": {str(fid): info for fid, info in self.known_fixtures.items()},
            "wc_only": self.wc_only,
        })

    # ── Discover loop ─────────────────────────────────────────────────────────

    def _fixture_label(self, f):
        home = f.get("teams", {}).get("home", {}).get("name", "?")
        away = f.get("teams", {}).get("away", {}).get("name", "?")
        return f"{home} vs {away}"

    def _discover_wc_fixtures(self):
        had_tracked = any(info["tracked"] for info in self.known_fixtures.values())
        fixtures = self.api_get("/fixtures", {"live": "all"})
        matched = [f for f in fixtures if f["league"]["name"] == "World Cup"] if self.wc_only else fixtures[:2]
        new_ids = {f["fixture"]["id"] for f in matched}
        for f in matched:
            fid = f["fixture"]["id"]
            if fid not in self.known_fixtures:
                self.known_fixtures[fid] = {
                    "tracked": self.track_active,
                    "label": self._fixture_label(f),
                    "status": f["fixture"]["status"]["short"],
                }
            else:
                self.known_fixtures[fid]["label"] = self._fixture_label(f)
                self.known_fixtures[fid]["status"] = f["fixture"]["status"]["short"]
            self.fixture_data[fid] = f
        if fixtures:  # skip pruning on empty API response (transient error guard)
            for fid in list(self.known_fixtures):
                if fid not in new_ids:
                    del self.known_fixtures[fid]
                    self.fixture_data.pop(fid, None)
        label = "WC" if self.wc_only else "all"
        ids = list(new_ids)
        log.info("DISCOVER (%s) → %d live fixtures, %d matched: %s", label, len(fixtures), len(ids), ids)
        has_tracked = any(info["tracked"] for info in self.known_fixtures.values())
        if has_tracked and not had_tracked and self.track_active and self._track_thread is None:
            self._start_track_thread()
        self.emit_status()
        return ids

    def _discover_loop(self):
        log.info("DISCOVER loop started (every %ds)", self.discover_interval)
        while self.discover_active:
            try:
                self._discover_wc_fixtures()
            except Exception as e:
                log.error("DISCOVER error: %s", e)
            self.socketio.sleep(self.discover_interval)
        log.info("DISCOVER loop stopped")

    def start_discovering(self):
        if self.discover_active:
            return False
        self.discover_active = True
        self._discover_thread = self.socketio.start_background_task(self._discover_loop)
        log.info("DISCOVER toggled ON")
        self.emit_status()
        return True

    def stop_discovering(self):
        if not self.discover_active:
            return False
        self.discover_active = False
        log.info("DISCOVER toggled OFF")
        self.emit_status()
        return True

    # ── Track loop ────────────────────────────────────────────────────────────

    def _track_loop(self):
        log.info("TRACK loop started (every %ds)", self.track_interval)
        while self.track_active:
            tracked_ids = [fid for fid, info in self.known_fixtures.items() if info["tracked"]]
            if not tracked_ids:
                log.debug("TRACK tick — no tracked fixtures")
                self.socketio.sleep(self.track_interval)
                continue
            try:
                ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                events_by_fixture = {}
                statistics_by_fixture = {}
                api_calls = 0
                for fid in tracked_ids:
                    try:
                        fixture_data = self.api_get("/fixtures", {"id": fid})
                        api_calls += 1
                    except Exception as e:
                        log.error("TRACK /fixtures error fixture %d: %s", fid, e)
                        fixture_data = None
                    if fixture_data:
                        f = fixture_data[0]
                        self.fixture_data[fid] = f
                        status = f["fixture"]["status"]["short"]
                        if fid in self.known_fixtures:
                            self.known_fixtures[fid]["status"] = status
                        if status in self.ACTIVE_STATUSES:
                            events = self._fetch_fixture_detail(fid, "/fixtures/events")
                            api_calls += 1
                            if events is not None:
                                events_by_fixture[fid] = events
                            stats = self._fetch_fixture_detail(fid, "/fixtures/statistics")
                            api_calls += 1
                            if stats is not None:
                                statistics_by_fixture[fid] = stats
                        else:
                            log.info("TRACK fixture %d — skipping events/stats (status: %s)", fid, status)
                for fid, f in self.fixture_data.items():
                    if fid in events_by_fixture:
                        f["events"] = events_by_fixture[fid]
                    if fid in statistics_by_fixture:
                        f["statistics"] = statistics_by_fixture[fid]
                    f["_tracked"] = self.known_fixtures.get(fid, {}).get("tracked", False)
                all_fixtures = self._wc_filter(list(self.fixture_data.values()))
                self.latest_fixtures = all_fixtures
                tracked_fixtures = [self.fixture_data[fid] for fid in tracked_ids if fid in self.fixture_data]
                self._save_poll(ts, tracked_fixtures, events_by_fixture, statistics_by_fixture)
                log.info("TRACK → %d tracked (%d total), %d API calls, emitting live_update",
                         len(tracked_ids), len(all_fixtures), api_calls)
                self.socketio.emit("live_update", all_fixtures)
                self.emit_status()
            except Exception as e:
                log.error("TRACK error: %s", e)
            self.socketio.sleep(self.track_interval)
        self._track_thread = None
        log.info("TRACK loop stopped")

    def _start_track_thread(self):
        if self._track_thread is not None:
            return
        self._track_thread = self.socketio.start_background_task(self._track_loop)
        log.info("TRACK thread spawned")

    def set_automated_tracking(self):
        if self.track_active:
            return False
        self.track_active = True
        for info in self.known_fixtures.values():
            info["tracked"] = True
        log.info("TRACK toggled ON (%d fixtures set to tracked)", len(self.known_fixtures))
        if self.known_fixtures:
            self._start_track_thread()
        else:
            log.info("TRACK armed — will start when fixtures are discovered")
        return True

    def unset_automated_tracking(self):
        if not self.track_active:
            return False
        self.track_active = False
        log.info("TRACK toggled OFF")
        return True


tracker = FixtureTracker(socketio, SERVER_DIR)

# ── CORS ─────────────────────────────────────────────────────────────────────

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

# ── Public API ────────────────────────────────────────────────────────────────

@app.route("/api/poll/active")
def poll_active():
    return jsonify({
        "discovering": tracker.discover_active,
        "tracking": tracker.track_active,
        "fixtures": list(tracker.known_fixtures.keys()),
    })

@app.route("/api/live")
def live():
    log.info("GET /api/live → returning %d stored fixtures", len(tracker.latest_fixtures))
    return jsonify(tracker.latest_fixtures)

@app.route("/api/standings")
def standings():
    groups = tracker.fetch_standings()
    log.info("GET /api/standings → %d groups", len(groups))
    return jsonify(groups)

@app.route("/api/group-results")
def group_results():
    results = tracker.fetch_group_results()
    log.info("GET /api/group-results → %d fixtures", len(results))
    return jsonify(results)

@app.route("/api/lineups/<int:fixture_id>")
def lineups(fixture_id):
    data = tracker.api_get("/fixtures/lineups", {"fixture": fixture_id})
    log.info("GET /api/lineups/%d → %d teams", fixture_id, len(data))
    return jsonify(data)

# ── Admin API — discover ──────────────────────────────────────────────────────

@app.route("/api/admin/poll/start", methods=["POST"])
def admin_poll_start():
    _, err = auth.require_admin()
    if err: return err
    started = tracker.start_discovering()
    return jsonify({"ok": True, "started": started, "already_running": not started})

@app.route("/api/admin/poll/stop", methods=["POST"])
def admin_poll_stop():
    _, err = auth.require_admin()
    if err: return err
    stopped = tracker.stop_discovering()
    return jsonify({"ok": True, "stopped": stopped, "was_running": stopped})

@app.route("/api/admin/poll/discover", methods=["POST"])
def admin_poll_discover():
    _, err = auth.require_admin()
    if err: return err
    try:
        ids = tracker._discover_wc_fixtures()
        return jsonify({"ok": True, "fixtures": ids})
    except Exception as e:
        log.error("DISCOVERY error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/poll/wc-filter", methods=["POST"])
def admin_poll_wc_filter():
    _, err = auth.require_admin()
    if err: return err
    tracker.wc_only = not tracker.wc_only
    log.info("WC filter toggled: %s", "ON" if tracker.wc_only else "OFF")
    return jsonify({"ok": True, "wc_only": tracker.wc_only})

@app.route("/api/admin/poll/status")
def admin_poll_status():
    _, err = auth.require_admin()
    if err: return err
    poll_count = len(list(tracker.polls_dir.glob("*.json"))) if tracker.polls_dir.exists() else 0
    return jsonify({
        "discovering": tracker.discover_active,
        "tracking": tracker.track_active,
        "wc_only": tracker.wc_only,
        "fixtures": {str(fid): info for fid, info in tracker.known_fixtures.items()},
        "fixtures_count": len(tracker.latest_fixtures),
        "saved_polls": poll_count,
    })

@app.route("/api/admin/polls")
def admin_polls_list():
    _, err = auth.require_admin()
    if err: return err
    if not tracker.polls_dir.exists():
        return jsonify([])
    files = sorted(tracker.polls_dir.glob("*.json"), reverse=True)
    return jsonify([f.stem for f in files])

@app.route("/api/admin/polls/<name>")
def admin_polls_get(name):
    _, err = auth.require_admin()
    if err: return err
    path = tracker.polls_dir / f"{name}.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(path.read_text()))

# ── Admin API — track ─────────────────────────────────────────────────────────

@app.route("/api/admin/track/start", methods=["POST"])
def admin_track_start():
    _, err = auth.require_admin()
    if err: return err
    tracker.set_automated_tracking()
    return jsonify({"ok": True, "tracking": tracker.track_active})

@app.route("/api/admin/track/stop", methods=["POST"])
def admin_track_stop():
    _, err = auth.require_admin()
    if err: return err
    tracker.unset_automated_tracking()
    return jsonify({"ok": True, "tracking": tracker.track_active})

@app.route("/api/admin/track/fixture", methods=["POST"])
def admin_track_fixture():
    _, err = auth.require_admin()
    if err: return err
    fid = request.json.get("fid")
    tracked = request.json.get("tracked")
    if fid is None or tracked is None:
        return jsonify({"error": "missing fid or tracked"}), 400
    fid = int(fid)
    if fid not in tracker.known_fixtures:
        return jsonify({"error": "unknown fixture"}), 404
    tracker.known_fixtures[fid]["tracked"] = bool(tracked)
    log.info("TRACK fixture %d → %s", fid, "on" if tracked else "off")
    if tracker.track_active and tracked and tracker._track_thread is None:
        tracker._start_track_thread()
    tracker.emit_status()
    tracker.emit_live_update()
    return jsonify({"ok": True})

@app.route("/api/admin/track/all", methods=["POST"])
def admin_track_all():
    _, err = auth.require_admin()
    if err: return err
    tracked = bool(request.json.get("tracked", True))
    for info in tracker.known_fixtures.values():
        info["tracked"] = tracked
    log.info("TRACK all fixtures → %s", "on" if tracked else "off")
    if tracker.track_active and tracked and tracker.known_fixtures and tracker._track_thread is None:
        tracker._start_track_thread()
    tracker.emit_status()
    tracker.emit_live_update()
    return jsonify({"ok": True})

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin_page():
    return send_file(SERVER_DIR / "admin.html")

@app.route("/admin-auth")
def admin_auth_page():
    return send_file(SERVER_DIR / "admin_auth.html")

# ─────────────────────────────────────────────────────────────────────────────

class _WsUpgradeFilter(logging.Filter):
    def filter(self, record):
        return "write() before start_response" not in record.getMessage()

logging.getLogger("werkzeug").addFilter(_WsUpgradeFilter())

if __name__ == "__main__":
    log.info("Proxy → %s", API_BASE)
    log.info("Admin emails: %s", ADMIN_EMAILS)
    tracker.start_discovering()
    socketio.run(app, host="0.0.0.0", port=5002, allow_unsafe_werkzeug=True)
