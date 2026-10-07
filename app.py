#!/usr/bin/env python3
"""
GameLibrarian — A personal game library manager.
Flask/SQLite backend.  Written by Claude (Anthropic).
"""

import ipaddress
import json
import os
import re
import socket
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, jsonify, request, send_from_directory

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR           = os.environ.get("DATA_DIR", "/data")
DB_PATH            = os.path.join(DATA_DIR, "gamelibrary.db")
IMAGES_DIR         = os.path.join(DATA_DIR, "images")
IGDB_CLIENT_ID     = os.environ.get("IGDB_CLIENT_ID", "")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET", "")
STEAM_API_KEY      = os.environ.get("STEAM_API_KEY", "")
STEAM_WISHLIST_URL = os.environ.get("STEAM_WISHLIST_URL", "")

WISHLIST_TTL = 86400  # 24 hours

VALID_STATUSES = {
    "unplayed", "unfinished", "completed", "completed_100",
    "abandoned", "multiplayer_only", "cant_complete",
}

# Settings the UI may write; secrets are never sent back to the browser.
SETTINGS_KEYS   = {"steam_wishlist_url", "steam_api_key", "igdb_client_id", "igdb_client_secret"}
SECRET_SETTINGS = {"steam_api_key", "igdb_client_secret"}

# Cover downloads: only these image types are stored, under an extension we choose.
IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "image/webp": "webp",
    "image/gif":  "gif",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS   = 3

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="")

# ── IGDB token cache ──────────────────────────────────────────────────────────

_igdb_token:         str | None = None
_igdb_token_expires: float      = 0.0
_igdb_token_creds:   tuple      = ("", "")

# ── Steam sync state ───────────────────────────────────────────────────────────

_steam_sync_running: bool = False


def _get_steam_settings() -> tuple[str, str]:
    """Return (api_key, wishlist_url): DB settings override env vars."""
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings"
                " WHERE key IN ('steam_api_key', 'steam_wishlist_url')"
            ).fetchall()
        db = {r["key"]: r["value"] for r in rows}
    except Exception:
        db = {}
    api_key      = db.get("steam_api_key")      or STEAM_API_KEY
    wishlist_url = db.get("steam_wishlist_url") or STEAM_WISHLIST_URL
    return api_key, wishlist_url


def _get_igdb_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret): DB settings override env vars."""
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings"
                " WHERE key IN ('igdb_client_id', 'igdb_client_secret')"
            ).fetchall()
        db = {r["key"]: r["value"] for r in rows}
    except Exception:
        db = {}
    client_id     = db.get("igdb_client_id")     or IGDB_CLIENT_ID
    client_secret = db.get("igdb_client_secret") or IGDB_CLIENT_SECRET
    return client_id, client_secret


def _get_igdb_token() -> str | None:
    global _igdb_token, _igdb_token_expires, _igdb_token_creds
    client_id, client_secret = _get_igdb_credentials()
    if not (client_id and client_secret):
        return None
    if (
        _igdb_token
        and time.time() < _igdb_token_expires
        and _igdb_token_creds == (client_id, client_secret)
    ):
        return _igdb_token
    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "client_credentials",
            },
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        _igdb_token         = d["access_token"]
        _igdb_token_expires = time.time() + d.get("expires_in", 3600) - 120
        _igdb_token_creds   = (client_id, client_secret)
        return _igdb_token
    except Exception as exc:
        print(f"[IGDB] token error: {exc}")
        return None


def _igdb_query(endpoint: str, body: str):
    token = _get_igdb_token()
    if token is None:
        return None
    client_id, _ = _get_igdb_credentials()
    try:
        r = requests.post(
            f"https://api.igdb.com/v4/{endpoint}",
            headers={
                "Client-ID":     client_id,
                "Authorization": f"Bearer {token}",
                "Content-Type":  "text/plain",
            },
            data=body,
            timeout=12,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"[IGDB] query error: {exc}")
        return None


# ── Database ──────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                igdb_id          INTEGER,
                name             TEXT    NOT NULL,
                release_date     TEXT    DEFAULT '',
                summary          TEXT    DEFAULT '',
                cover_image_path TEXT,
                cover_url        TEXT    DEFAULT '',
                status           TEXT    NOT NULL DEFAULT 'unplayed',
                rating           INTEGER NOT NULL DEFAULT 0,
                comment          TEXT    DEFAULT '',
                platforms        TEXT    NOT NULL DEFAULT '[]',
                genres           TEXT    DEFAULT '[]',
                developer        TEXT    DEFAULT '',
                publisher        TEXT    DEFAULT '',
                igdb_data        TEXT    DEFAULT '{}',
                created_at       TEXT    DEFAULT (datetime('now')),
                updated_at       TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS wishlist_cache (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                data       TEXT    NOT NULL DEFAULT '[]',
                fetched_at TEXT
            );
        """)
        # Migrations (safe no-op if columns already exist)
        for ddl in [
            "ALTER TABLE games ADD COLUMN steam_app_id        TEXT    DEFAULT ''",
            "ALTER TABLE games ADD COLUMN hours_played        REAL    DEFAULT 0",
            "ALTER TABLE games ADD COLUMN achievements_total  INTEGER DEFAULT 0",
            "ALTER TABLE games ADD COLUMN achievements_unlocked INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(ddl)
                conn.commit()
            except Exception:
                pass


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("platforms", "genres", "igdb_data"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = [] if key != "igdb_data" else {}
    d["cover_local_url"] = (
        f"/api/images/{d['cover_image_path']}" if d.get("cover_image_path") else None
    )
    return d


def _is_public_url(url: str) -> bool:
    """True if url is http(s) and every address its host resolves to is public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
    except socket.gaierror:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def _download_image(url: str, stem: str) -> str | None:
    """Download an image to IMAGES_DIR as <stem>.<ext>; return the filename or None."""
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not _is_public_url(url):
                print(f"[IMG] refusing non-public URL: {url}")
                return None
            r = requests.get(url, timeout=20, stream=True, allow_redirects=False)
            if r.is_redirect:
                url = urljoin(url, r.headers.get("Location", ""))
                r.close()
                continue
            break
        else:
            print(f"[IMG] too many redirects: {url}")
            return None

        with r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = IMAGE_TYPES.get(content_type)
            if ext is None:
                print(f"[IMG] unsupported content type {content_type!r}: {url}")
                return None

            filename = f"{stem}.{ext}"
            dest     = os.path.join(IMAGES_DIR, filename)
            size     = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(8192):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        break
                    fh.write(chunk)
            if size > MAX_IMAGE_BYTES:
                os.remove(dest)
                print(f"[IMG] image larger than {MAX_IMAGE_BYTES} bytes: {url}")
                return None
            return filename
    except Exception as exc:
        print(f"[IMG] download error {url}: {exc}")
        return None


def _cover_stem(igdb_id, fallback_id) -> str:
    return f"cover_{int(igdb_id) if str(igdb_id or '').isdigit() else fallback_id}_{int(time.time())}"


def _save_cover(data: dict, fallback_id) -> tuple[str | None, str]:
    """Return (cover_image_path, cover_url)."""
    cover_url = (data.get("cover_url") or "").strip()
    if cover_url:
        path = _download_image(cover_url, _cover_stem(data.get("igdb_id"), fallback_id))
        return path, cover_url
    return None, cover_url


def _remove_image(filename: str | None) -> None:
    if filename:
        try:
            os.remove(os.path.join(IMAGES_DIR, filename))
        except OSError:
            pass


# ── Steam / wishlist helpers ──────────────────────────────────────────────────

def _parse_steam_url(url: str) -> tuple[str, str] | tuple[None, None]:
    url = url.strip().rstrip("/")
    m = re.search(r"/(profiles)/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"/(id)/([^/?#]+)", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _fetch_wishlist_from_steam(steam_url: str, api_key: str = "") -> tuple[list, str]:
    kind, sid = _parse_steam_url(steam_url)
    if not sid:
        return [], "Invalid Steam wishlist URL"
    if kind != "profiles":
        return [], "Please use the numeric profile URL (…/profiles/STEAMID64/…) — vanity URLs are not supported"

    params: dict = {"steamid": sid}
    if api_key:
        params["key"] = api_key

    try:
        r = requests.get(
            "https://api.steampowered.com/IWishlistService/GetWishlist/v1/",
            params=params,
            timeout=20,
        )
        if r.status_code == 401:
            return [], "Steam API key is missing or invalid — add your key in Settings"
        if r.status_code == 403:
            return [], "Access denied — the wishlist may be private, or the API key is invalid"
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return [], f"Steam API request failed: {exc}"

    items = (data.get("response") or {}).get("items") or []
    games = []
    for item in items:
        appid = str(item.get("appid") or "")
        if not appid or appid == "0":
            continue
        games.append({
            "appid":        appid,
            "name":         "",
            "capsule":      f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
            "release_date": "",
            "price":        None,
            "priority":     item.get("priority", 9999),
            "igdb_id":      None,
            "library_match": None,
        })
    games.sort(key=lambda x: x["priority"])
    return games, ""


def _get_igdb_game_details(igdb_ids: list[int]) -> dict[int, dict]:
    if not igdb_ids or not all(_get_igdb_credentials()):
        return {}
    id_list = ", ".join(str(i) for i in igdb_ids[:500])
    raw = _igdb_query(
        "games",
        f"fields name, cover.image_id, first_release_date; where id = ({id_list}); limit 500;",
    )
    if not raw:
        return {}
    result: dict[int, dict] = {}
    for g in raw:
        cover_url = None
        if g.get("cover") and g["cover"].get("image_id"):
            cover_url = (
                f"https://images.igdb.com/igdb/image/upload"
                f"/t_cover_big/{g['cover']['image_id']}.jpg"
            )
        release_date = ""
        if g.get("first_release_date"):
            try:
                release_date = datetime.utcfromtimestamp(
                    g["first_release_date"]
                ).strftime("%Y-%m-%d")
            except Exception:
                pass
        result[g["id"]] = {
            "name":         g.get("name", ""),
            "cover_url":    cover_url,
            "release_date": release_date,
        }
    return result


def _get_igdb_ids_for_steam_apps(appids: list[str]) -> dict[str, int]:
    if not appids or not all(_get_igdb_credentials()):
        return {}
    uid_list = ", ".join(f'"{a}"' for a in appids[:500])
    raw = _igdb_query(
        "external_games",
        f'fields uid, game; where category = 1 & uid = ({uid_list}); limit 500;',
    )
    if not raw:
        return {}
    return {
        str(item.get("uid")): item["game"]
        for item in raw
        if item.get("uid") and item.get("game")
    }


def _normalize_name(name: str) -> str:
    """Lowercase ASCII, strip everything except a-z0-9 — used for name matching."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _search_steam_appid(name: str) -> str | None:
    """Search the Steam store for a game by name and return its AppID on an exact match."""
    norm = _normalize_name(name)
    if not norm:
        return None
    try:
        r = requests.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": name, "l": "english", "cc": "US"},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json().get("items") or []
    except Exception as exc:
        print(f"[Steam] Search failed for '{name}': {exc}")
        return None
    for item in items:
        if _normalize_name(item.get("name", "")) == norm:
            return str(item["id"])
    return None


def _sync_steam_data() -> dict:
    """Fetch play time (batch) and achievements (per game) from Steam and write to DB."""
    api_key, steam_url = _get_steam_settings()
    api_key   = (api_key   or "").strip()
    steam_url = (steam_url or "").strip()

    if not steam_url or not api_key:
        return {"error": "Steam wishlist URL and API key are required"}
    _, steamid = _parse_steam_url(steam_url)
    if not steamid:
        return {"error": "Could not parse SteamID from wishlist URL"}

    # Batch: fetch all owned games with playtime
    try:
        r = requests.get(
            "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
            params={"key": api_key, "steamid": steamid,
                    "include_appinfo": 1, "include_played_free_games": 1},
            timeout=20,
        )
        if r.status_code == 403:
            return {"error": "Steam API key invalid or profile is private"}
        r.raise_for_status()
        steam_games = r.json().get("response", {}).get("games") or []
    except Exception as exc:
        return {"error": f"GetOwnedGames failed: {exc}"}

    appid_to_minutes: dict[str, int] = {
        str(g["appid"]): g.get("playtime_forever", 0) for g in steam_games
    }

    with _get_db() as conn:
        lib_rows = conn.execute(
            "SELECT id, steam_app_id FROM games"
            " WHERE steam_app_id IS NOT NULL AND steam_app_id != ''"
        ).fetchall()

    if not lib_rows:
        return {"synced": 0, "hours_updated": 0, "achievements_updated": 0}

    hours_updated = ach_updated = 0
    for row in lib_rows:
        appid = row["steam_app_id"]
        updates: dict = {}

        minutes = appid_to_minutes.get(appid)
        if minutes is not None:
            updates["hours_played"] = round(minutes / 60, 1)
            hours_updated += 1

        # Per-game: achievements
        try:
            ra = requests.get(
                "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/",
                params={"appid": appid, "steamid": steamid, "key": api_key},
                timeout=10,
            )
            ra.raise_for_status()
            ps = ra.json().get("playerstats", {})
            if ps.get("success"):
                ach = ps.get("achievements") or []
                updates["achievements_total"]    = len(ach)
                updates["achievements_unlocked"] = sum(1 for a in ach if a.get("achieved") == 1)
                ach_updated += 1
        except Exception:
            pass

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            with _get_db() as conn:
                conn.execute(
                    f"UPDATE games SET {set_clause} WHERE id=?",
                    (*updates.values(), row["id"]),
                )
                conn.commit()

        time.sleep(0.15)  # be polite between per-game achievement calls

    with _get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('steam_last_sync', ?)",
            (datetime.utcnow().isoformat(),),
        )
        conn.commit()

    return {
        "synced":               len(lib_rows),
        "hours_updated":        hours_updated,
        "achievements_updated": ach_updated,
    }


def _startup_background() -> None:
    _backfill_steam_appids()
    # Auto-sync Steam data if not done recently (TTL: 1 h)
    try:
        with _get_db() as conn:
            ts_row = conn.execute(
                "SELECT value FROM settings WHERE key='steam_last_sync'"
            ).fetchone()
        if ts_row:
            age = (datetime.utcnow() - datetime.fromisoformat(ts_row["value"])).total_seconds()
            if age < 3600:
                return
    except Exception:
        pass
    result = _sync_steam_data()
    if "error" not in result:
        print(f"[Steam] Sync complete: {result}")


def _backfill_steam_appids() -> None:
    """Startup background task: fill steam_app_id for Steam-platform games via store search."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM games"
            " WHERE (steam_app_id IS NULL OR steam_app_id = '')"
            "   AND platforms LIKE '%\"steam\"%'"
        ).fetchall()
    if not rows:
        return
    print(f"[Backfill] Looking up Steam App IDs for {len(rows)} game(s)…")
    updated = 0
    for row in rows:
        appid = _search_steam_appid(row["name"])
        if appid:
            with _get_db() as conn:
                conn.execute(
                    "UPDATE games SET steam_app_id = ? WHERE id = ?",
                    (appid, row["id"]),
                )
                conn.commit()
            updated += 1
        time.sleep(0.5)  # stay well within Steam's rate limits
    print(f"[Backfill] Steam App IDs: {updated}/{len(rows)} games updated")


def _cross_reference_wishlist(base_games: list) -> list:
    with _get_db() as conn:
        lib_rows = conn.execute(
            "SELECT id, igdb_id, name, platforms, status FROM games"
        ).fetchall()

    igdb_to_lib: dict = {}
    name_to_lib: dict = {}
    for row in lib_rows:
        g = dict(row)
        if g["igdb_id"]:
            igdb_to_lib[g["igdb_id"]] = g
        norm = re.sub(r"[^a-z0-9]", "", g["name"].lower())
        name_to_lib[norm] = g

    games = []
    for base in base_games:
        game = dict(base)
        game["library_match"] = None
        match = igdb_to_lib.get(game.get("igdb_id")) if game.get("igdb_id") else None
        if not match:
            norm = re.sub(r"[^a-z0-9]", "", game["name"].lower())
            match = name_to_lib.get(norm)
        if match:
            try:
                platforms = (
                    json.loads(match["platforms"])
                    if isinstance(match["platforms"], str)
                    else (match["platforms"] or [])
                )
            except Exception:
                platforms = []
            game["library_match"] = {
                "id":        match["id"],
                "status":    match["status"],
                "platforms": platforms,
            }
        games.append(game)
    return games


# ── Static ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/images/<path:filename>")
def serve_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


# ── Config ────────────────────────────────────────────────────────────────────

@app.route("/api/config")
def api_config():
    cid, csec = _get_igdb_credentials()
    return jsonify({"igdb_configured": bool(cid and csec)})


# ── IGDB search ───────────────────────────────────────────────────────────────

@app.route("/api/igdb/search")
def igdb_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    if not all(_get_igdb_credentials()):
        return jsonify({"error": "IGDB credentials not configured"}), 503

    raw = _igdb_query(
        "games",
        f'search "{q}"; fields name,cover.image_id,first_release_date,summary,platforms.name,genres.name,involved_companies.company.name,involved_companies.developer,involved_companies.publisher; limit 10;',
    )
    if raw is None:
        return jsonify({"error": "IGDB query failed"}), 503

    results = []
    for g in raw:
        cover_url = None
        if g.get("cover") and g["cover"].get("image_id"):
            cover_url = (
                "https://images.igdb.com/igdb/image/upload"
                f"/t_cover_big/{g['cover']['image_id']}.jpg"
            )

        release_date = ""
        if g.get("first_release_date"):
            try:
                release_date = datetime.utcfromtimestamp(
                    g["first_release_date"]
                ).strftime("%Y-%m-%d")
            except Exception:
                pass

        developer = publisher = ""
        for ic in g.get("involved_companies") or []:
            co = (ic.get("company") or {}).get("name", "")
            if ic.get("developer") and not developer:
                developer = co
            if ic.get("publisher") and not publisher:
                publisher = co

        results.append(
            {
                "igdb_id":        g["id"],
                "name":           g.get("name", ""),
                "cover_url":      cover_url,
                "release_date":   release_date,
                "summary":        g.get("summary", ""),
                "platforms_igdb": [p["name"] for p in (g.get("platforms") or [])],
                "genres":         [gn["name"] for gn in (g.get("genres") or [])],
                "developer":      developer,
                "publisher":      publisher,
            }
        )
    return jsonify(results)


# ── Games CRUD ────────────────────────────────────────────────────────────────

@app.route("/api/games", methods=["GET"])
def list_games():
    platform   = request.args.get("platform", "")
    status     = request.args.get("status", "")
    rating     = request.args.get("rating", "")
    search     = request.args.get("search", "")
    sort_field = request.args.get("sort", "name")
    sort_dir   = request.args.get("dir", "asc").upper()

    _VALID_SORT = {"name", "rating", "status", "created_at", "release_date", "updated_at"}
    if sort_field not in _VALID_SORT:
        sort_field = "name"
    if sort_dir not in ("ASC", "DESC"):
        sort_dir = "ASC"

    sql    = "SELECT * FROM games WHERE 1=1"
    params: list = []

    if search:
        sql += " AND name LIKE ?"
        params.append(f"%{search}%")
    if status:
        sql += " AND status = ?"
        params.append(status)
    if rating:
        try:
            sql += " AND rating = ?"
            params.append(int(rating))
        except ValueError:
            pass

    sql += f" ORDER BY {sort_field} COLLATE NOCASE {sort_dir}"

    with _get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    games = [_row_to_dict(r) for r in rows]
    if platform:
        games = [g for g in games if platform in (g.get("platforms") or [])]
    return jsonify(games)


@app.route("/api/games", methods=["POST"])
def add_game():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    status = data.get("status", "unplayed")
    if status not in VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    cover_image_path, cover_url = _save_cover(data, "new")
    rating      = 0 if status == "abandoned" else max(0, min(5, int(data.get("rating") or 0)))
    comment     = (data.get("comment") or "")[:400]
    steam_app_id = (data.get("steam_app_id") or "").strip()
    hours_played = max(0.0, float(data.get("hours_played") or 0))

    with _get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO games
                (igdb_id, name, release_date, summary, cover_image_path, cover_url,
                 status, rating, comment, platforms, genres, developer, publisher,
                 igdb_data, steam_app_id, hours_played)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data.get("igdb_id"),
                name,
                data.get("release_date", ""),
                data.get("summary", ""),
                cover_image_path,
                cover_url,
                status,
                rating,
                comment,
                json.dumps(data.get("platforms") or []),
                json.dumps(data.get("genres") or []),
                data.get("developer", ""),
                data.get("publisher", ""),
                json.dumps(data.get("igdb_data") or {}),
                steam_app_id,
                hours_played,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM games WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(_row_to_dict(row)), 201


@app.route("/api/games/<int:gid>", methods=["GET"])
def get_game(gid):
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_row_to_dict(row))


@app.route("/api/games/<int:gid>", methods=["PUT"])
def update_game(gid):
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        existing = _row_to_dict(row)

    data   = request.get_json(force=True, silent=True) or {}
    status = data.get("status", existing["status"])
    if status not in VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    old_cover_url    = existing.get("cover_url") or ""
    new_cover_url    = (data.get("cover_url", old_cover_url) or "").strip()
    cover_image_path = existing.get("cover_image_path")

    if not new_cover_url:
        _remove_image(cover_image_path)
        cover_image_path = None
    elif new_cover_url != old_cover_url:
        dl = _download_image(new_cover_url, _cover_stem(data.get("igdb_id"), gid))
        if dl:
            _remove_image(cover_image_path)
            cover_image_path = dl

    rating       = (
        0 if status == "abandoned"
        else max(0, min(5, int(data.get("rating", existing["rating"]) or 0)))
    )
    comment      = (data.get("comment") or "")[:400]
    steam_app_id = (data.get("steam_app_id", existing.get("steam_app_id") or "")).strip()
    hours_played = max(0.0, float(data.get("hours_played", existing.get("hours_played") or 0) or 0))

    with _get_db() as conn:
        conn.execute(
            """
            UPDATE games SET
                igdb_id=?, name=?, release_date=?, summary=?,
                cover_image_path=?, cover_url=?, status=?, rating=?,
                comment=?, platforms=?, genres=?, developer=?, publisher=?,
                igdb_data=?, steam_app_id=?, hours_played=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (
                data.get("igdb_id", existing.get("igdb_id")),
                (data.get("name") or existing["name"]).strip(),
                data.get("release_date", existing.get("release_date", "")),
                data.get("summary",      existing.get("summary", "")),
                cover_image_path,
                new_cover_url,
                status,
                rating,
                comment,
                json.dumps(data.get("platforms", existing.get("platforms") or [])),
                json.dumps(data.get("genres",    existing.get("genres") or [])),
                data.get("developer", existing.get("developer", "")),
                data.get("publisher", existing.get("publisher", "")),
                json.dumps(data.get("igdb_data", existing.get("igdb_data") or {})),
                steam_app_id,
                hours_played,
                gid,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    return jsonify(_row_to_dict(row))


@app.route("/api/games/<int:gid>", methods=["DELETE"])
def delete_game(gid):
    with _get_db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        _remove_image(row["cover_image_path"])
        conn.execute("DELETE FROM games WHERE id=?", (gid,))
        conn.commit()
    return jsonify({"ok": True})


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def get_stats():
    with _get_db() as conn:
        total       = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM games GROUP BY status"
        ).fetchall()
        rating_rows = conn.execute(
            "SELECT rating, COUNT(*) FROM games WHERE status != 'abandoned' GROUP BY rating ORDER BY rating"
        ).fetchall()
        rated       = conn.execute(
            "SELECT COUNT(*) FROM games WHERE rating > 0"
        ).fetchone()[0]
        total_hours = conn.execute(
            "SELECT COALESCE(SUM(hours_played), 0) FROM games"
        ).fetchone()[0]
        platform_games = conn.execute("SELECT platforms FROM games").fetchall()

    status_counts  = {r[0]: r[1] for r in status_rows}
    rating_counts  = {str(r[0]): r[1] for r in rating_rows}

    platform_counts: dict[str, int] = {}
    for row in platform_games:
        try:
            platforms = json.loads(row[0] or "[]")
        except (json.JSONDecodeError, TypeError):
            platforms = []
        for p in platforms:
            platform_counts[p] = platform_counts.get(p, 0) + 1

    return jsonify(
        {
            "total":           total,
            "rated":           rated,
            "total_hours":     round(total_hours, 1),
            "status_counts":   status_counts,
            "rating_counts":   rating_counts,
            "platform_counts": platform_counts,
        }
    )


# ── Settings ─────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def get_settings():
    with _get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    # Surface env-var fallbacks so the UI shows them even before first save
    cid, csec = _get_igdb_credentials()
    settings.setdefault("igdb_client_id",     cid)
    settings.setdefault("igdb_client_secret", csec)
    api_key, wishlist_url = _get_steam_settings()
    settings.setdefault("steam_api_key",      api_key)
    settings.setdefault("steam_wishlist_url", wishlist_url)
    # Only report whether a secret is set; the value never leaves the server
    for key in SECRET_SETTINGS:
        settings[f"{key}_set"] = bool(settings.pop(key, ""))
    return jsonify(settings)


@app.route("/api/settings", methods=["PUT"])
def save_settings():
    global _igdb_token, _igdb_token_expires, _igdb_token_creds
    data = request.get_json(force=True, silent=True) or {}
    data = {
        k: str(v).strip() for k, v in data.items()
        if k in SETTINGS_KEYS and not (k in SECRET_SETTINGS and not str(v).strip())
    }
    igdb_changed = "igdb_client_id" in data or "igdb_client_secret" in data
    with _get_db() as conn:
        for key, value in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (str(key), str(value)),
            )
        if igdb_changed:
            # Flush wishlist cache so next load re-enriches with new credentials
            conn.execute("DELETE FROM wishlist_cache WHERE id = 1")
        conn.commit()
    if igdb_changed:
        # Reset in-memory token so it is re-fetched with new credentials
        _igdb_token        = None
        _igdb_token_expires = 0.0
        _igdb_token_creds  = ("", "")
    return jsonify({"ok": True})


# ── Wishlist ──────────────────────────────────────────────────────────────────

@app.route("/api/wishlist")
def get_wishlist():
    force = request.args.get("refresh") == "1"

    with _get_db() as conn:
        cache_row = conn.execute(
            "SELECT data, fetched_at FROM wishlist_cache WHERE id=1"
        ).fetchone()

    steam_key, steam_url = _get_steam_settings()
    steam_url = (steam_url or "").strip()
    steam_key = (steam_key or "").strip()
    if not steam_url:
        return jsonify({"games": [], "fetched_at": None, "error": "no_url"})

    base_games = None
    fetched_at = None
    from_cache = False

    if not force and cache_row and cache_row["fetched_at"]:
        try:
            age = (
                datetime.utcnow() - datetime.fromisoformat(cache_row["fetched_at"])
            ).total_seconds()
            if age < WISHLIST_TTL:
                cached = json.loads(cache_row["data"])
                # Treat cache as stale if every entry is unenriched (IGDB failed last time)
                has_names = any(
                    g.get("name") and not g["name"].startswith("Steam App ")
                    for g in cached
                )
                if cached and not has_names:
                    print("[Wishlist] cache has no IGDB names — forcing re-enrichment")
                else:
                    base_games = cached
                    fetched_at = cache_row["fetched_at"]
                    from_cache = True
        except Exception:
            pass

    if base_games is None:
        games, err = _fetch_wishlist_from_steam(steam_url, steam_key)
        if err:
            return jsonify({"games": [], "fetched_at": None, "error": err}), 502

        # Enrich with IGDB: AppID → igdb_id, then batch-fetch name/cover
        appids        = [g["appid"] for g in games]
        steam_to_igdb = _get_igdb_ids_for_steam_apps(appids)
        for game in games:
            igdb_id = steam_to_igdb.get(game["appid"])
            if igdb_id:
                game["igdb_id"] = igdb_id

        igdb_ids    = [g["igdb_id"] for g in games if g["igdb_id"]]
        igdb_detail = _get_igdb_game_details(igdb_ids)
        for game in games:
            d = igdb_detail.get(game["igdb_id"]) if game["igdb_id"] else None
            if d:
                if d["name"]:         game["name"]         = d["name"]
                if d["cover_url"]:    game["capsule"]      = d["cover_url"]
                if d["release_date"]: game["release_date"] = d["release_date"]
            if not game["name"]:
                game["name"] = f"Steam App {game['appid']}"

        base_games = games
        fetched_at = datetime.utcnow().isoformat()
        with _get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO wishlist_cache (id, data, fetched_at) VALUES (1, ?, ?)",
                (json.dumps(base_games), fetched_at),
            )
            conn.commit()

    games = _cross_reference_wishlist(base_games)
    enriched = sum(1 for g in games if g.get("igdb_id"))
    return jsonify({
        "games":     games,
        "fetched_at": fetched_at,
        "cached":    from_cache,
        "igdb_enriched": enriched,
        "igdb_total":    len(games),
    })


@app.route("/api/steam/sync", methods=["POST"])
def steam_sync():
    global _steam_sync_running
    if _steam_sync_running:
        return jsonify({"error": "Sync already in progress"}), 409

    def _run():
        global _steam_sync_running
        try:
            result = _sync_steam_data()
            if "error" not in result:
                print(f"[Steam] Manual sync complete: {result}")
            else:
                print(f"[Steam] Manual sync error: {result['error']}")
        finally:
            _steam_sync_running = False

    _steam_sync_running = True
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True})


@app.route("/api/steam/find-appid")
def steam_find_appid():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify({"appid": _search_steam_appid(name)})


@app.route("/api/igdb/status")
def igdb_status():
    cid, csec = _get_igdb_credentials()
    if not (cid and csec):
        return jsonify({"configured": False, "connected": False,
                        "message": "No credentials — add Client ID and Secret in Settings"})
    token = _get_igdb_token()
    if not token:
        return jsonify({"configured": True, "connected": False,
                        "message": "Token request failed — credentials may be wrong or expired"})
    raw = _igdb_query("games", "fields id; where id = 1942; limit 1;")
    if raw is None:
        return jsonify({"configured": True, "connected": False,
                        "message": "IGDB query failed — check network or credentials"})
    return jsonify({"configured": True, "connected": True, "message": "Connected"})


@app.route("/api/igdb/game")
def igdb_game_by_id():
    igdb_id = request.args.get("id", "").strip()
    if not igdb_id:
        return jsonify({"error": "id required"}), 400
    if not all(_get_igdb_credentials()):
        return jsonify({"error": "IGDB not configured"}), 503
    raw = _igdb_query(
        "games",
        f"fields name,cover.image_id,first_release_date,summary,"
        f"involved_companies.company.name,involved_companies.developer,"
        f"involved_companies.publisher; where id = {igdb_id}; limit 1;",
    )
    if not raw:
        return jsonify({"error": "not found"}), 404
    g = raw[0]
    cover_url = None
    if g.get("cover") and g["cover"].get("image_id"):
        cover_url = (
            f"https://images.igdb.com/igdb/image/upload"
            f"/t_cover_big/{g['cover']['image_id']}.jpg"
        )
    release_date = ""
    if g.get("first_release_date"):
        try:
            release_date = datetime.utcfromtimestamp(
                g["first_release_date"]
            ).strftime("%Y-%m-%d")
        except Exception:
            pass
    developer = publisher = ""
    for ic in g.get("involved_companies") or []:
        co = (ic.get("company") or {}).get("name", "")
        if ic.get("developer") and not developer:
            developer = co
        if ic.get("publisher") and not publisher:
            publisher = co
    return jsonify({
        "igdb_id":      g["id"],
        "name":         g.get("name", ""),
        "cover_url":    cover_url,
        "release_date": release_date,
        "summary":      g.get("summary", ""),
        "developer":    developer,
        "publisher":    publisher,
    })


# ── Boot ──────────────────────────────────────────────────────────────────────

_init_db()
threading.Thread(target=_startup_background, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
