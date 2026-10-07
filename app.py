#!/usr/bin/env python3
"""
GameLibrarian — A personal game library manager.
Flask/SQLite backend.  Written by Claude (Anthropic).
"""

import ipaddress
import json
import os
import socket
import sqlite3
import time
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

VALID_STATUSES = {
    "unplayed", "unfinished", "completed", "completed_100",
    "abandoned", "multiplayer_only", "cant_complete",
}

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


def _get_igdb_token() -> str | None:
    global _igdb_token, _igdb_token_expires
    if _igdb_token and time.time() < _igdb_token_expires:
        return _igdb_token
    if not (IGDB_CLIENT_ID and IGDB_CLIENT_SECRET):
        return None
    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id":     IGDB_CLIENT_ID,
                "client_secret": IGDB_CLIENT_SECRET,
                "grant_type":    "client_credentials",
            },
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        _igdb_token         = d["access_token"]
        _igdb_token_expires = time.time() + d.get("expires_in", 3600) - 120
        return _igdb_token
    except Exception as exc:
        print(f"[IGDB] token error: {exc}")
        return None


def _igdb_query(endpoint: str, body: str):
    token = _get_igdb_token()
    if token is None:
        return None
    try:
        r = requests.post(
            f"https://api.igdb.com/v4/{endpoint}",
            headers={
                "Client-ID":     IGDB_CLIENT_ID,
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
        """)


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
    return jsonify({"igdb_configured": bool(IGDB_CLIENT_ID and IGDB_CLIENT_SECRET)})


# ── IGDB search ───────────────────────────────────────────────────────────────

@app.route("/api/igdb/search")
def igdb_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    if not (IGDB_CLIENT_ID and IGDB_CLIENT_SECRET):
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
    rating  = 0 if status == "abandoned" else max(0, min(5, int(data.get("rating") or 0)))
    comment = (data.get("comment") or "")[:400]

    with _get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO games
                (igdb_id, name, release_date, summary, cover_image_path, cover_url,
                 status, rating, comment, platforms, genres, developer, publisher, igdb_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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

    rating  = (
        0 if status == "abandoned"
        else max(0, min(5, int(data.get("rating", existing["rating"]) or 0)))
    )
    comment = (data.get("comment") or "")[:400]

    with _get_db() as conn:
        conn.execute(
            """
            UPDATE games SET
                igdb_id=?, name=?, release_date=?, summary=?,
                cover_image_path=?, cover_url=?, status=?, rating=?,
                comment=?, platforms=?, genres=?, developer=?, publisher=?,
                igdb_data=?, updated_at=datetime('now')
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
            "status_counts":   status_counts,
            "rating_counts":   rating_counts,
            "platform_counts": platform_counts,
        }
    )


# ── Boot ──────────────────────────────────────────────────────────────────────

_init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
