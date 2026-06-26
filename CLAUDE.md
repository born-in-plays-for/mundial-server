# CLAUDE.md — mundial-server

This file provides guidance to Claude Code when working in this repository. For setup, endpoints, WebSocket events, and architecture, see **`README.md`** — it is the primary reference. This file covers non-obvious decisions, gotchas, and workflow rules.

The frontend repo lives at `../mundial` (sibling directory). The frontend's CLAUDE.md documents how it consumes this backend.

---

## Git / deployment

**NEVER commit or push unless the user explicitly asks.** Wait for the user to test first.

This repo is **never deployed** — it runs locally and is exposed via ngrok. `start.sh` handles everything (kills stale process, starts backend + ngrok, publishes ngrok URL to `../mundial/backend_config.json` and pushes that repo). See README for details.

---

## Running locally

```bash
# Auth only, no API calls:
API_FOOTBALL_KEY=mock python3 backend.py

# With mock API-Football (two terminals):
python3 mock_api_football.py          # terminal 1 — port 5003
API_FOOTBALL_KEY=mock API_FOOTBALL_URL=http://localhost:5003 python3 backend.py  # terminal 2
```

Backend runs on port **5002**. The frontend dev server runs on port **4040** (nginx, separate process).

---

## Key design decisions

### `tracking` is intentionally absent from `poll_status`

`poll_status` broadcasts `{ discovering, fixtures, wc_only }` — **no `tracking` field**. Auto-track (on/off) is an internal server automation detail; clients never need to know whether the auto-track loop is armed. Do not add `tracking` back to the broadcast — it was deliberately removed to simplify the client state model.

Clients observe auto-track only indirectly: if `live_update` events arrive every 60s, auto-track is on. The `_tracked` flag on each fixture in `live_update` tells clients which fixtures are being actively fetched.

### Three-state discovery model

| discovering | fixtures found | Meaning |
|---|---|---|
| `false` | — | Not polling — deaf and mute |
| `true` | 0 | Polling, nothing found yet — listening |
| `true` | >0 | Active — fixtures discovered |

The frontend badge reflects these three states. Do not collapse them into a simple on/off.

### `_tracked` flag on fixtures

Each fixture in `live_update` carries `_tracked: bool`. This lets the frontend dim untracked fixtures without knowing anything about global auto-track state. The flag is set server-side in the poll loop based on `tracker.known_fixtures[fid]['tracked']`.

### Per-fixture tracking vs. global auto-track

Two orthogonal concepts:
- **Global auto-track** (`/api/admin/track/start|stop`): arms/disarms the 60s loop that fetches data for tracked fixtures. Internal only.
- **Per-fixture `tracked` flag** (`/api/admin/track/fixture`): marks which fixtures the loop should fetch. Visible to clients via `_tracked` in `live_update`.

### Auto-track defaults to on at startup

`FixtureTracker` initialises with `track_active = True`. No fixtures exist yet so no thread is spawned — it is just armed. When discovery finds fixtures, they are immediately set to `tracked=True` and the track thread starts. Do not change this default; it is intentional so the admin does not need to manually arm tracking after each restart.

### Startup poll loading

On startup, only fixtures with an in-progress status (`1H`, `2H`, `ET`, `P`) are loaded from the latest saved poll. Finished matches (`FT`, `AET`, `PEN`) are discarded — they are stale and would clutter the discovery state with games no one needs to track.

### WebSocket transport

Always use `{transports: ['websocket']}` on the client side (already done in `auth-bar.js`). The polling fallback causes CORS issues through ngrok.

---

## Admin pages

Plain HTML + vanilla JS + Bootstrap 5. No build step, no framework. Two pages, each focused on one concern:

| File | Route | Concern |
|---|---|---|
| `admin.html` | `/admin` | Discover / auto-track / per-fixture tracking |
| `admin_auth.html` | `/admin-auth` | Registered users / active sessions / kick / delete |

Each page has its own WebSocket connection and only handles the events it needs. They link to each other via a nav link in the header.

`admin_auth.html` is reusable — it belongs logically to `auth.py` and can be copied to other projects alongside it.

**Layout conventions for `admin.html` (as of 2026-06-26):**
- Status badge (on/off) appears **before** the label: `[on] Discover`, `[on] Track`
- Action buttons are **right-aligned** in a flex container: `[WC only] [Once] [Stop]`
- Per-fixture rows: status badge → tracked badge → team label, with Stop button right-aligned (not full-width)
- `Start all` / `Stop all` buttons set the column width; individual Stop buttons use `<div class="text-end">` wrapper so they don't stretch

---

## API contract consumed by the frontend

The frontend (`wc2026_live_game.html`) calls these endpoints directly:

| Endpoint | Used for |
|---|---|
| `/api/standings` | Group standings (fetched once on load) |
| `/api/group-results` | Finished group match results (fetched once on load) |
| `/api/live` | Current live fixtures (fetched on load and on reconnect) |
| `/api/lineups/<id>` | Starting XI + subs (fetched per fixture, cached client-side) |

Socket events consumed by the frontend: `poll_status`, `live_update`. See README for full payload shapes.

---

## Terminology

Always use **"country"** in user-facing text. See `../mundial/CLAUDE.md` for full terminology guidance.
