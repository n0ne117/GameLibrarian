# GameLibrarian

A self-hosted, dockerized web application for organizing your PC and console game collection.

> **Written by Claude (Anthropic)** — AI-assisted software development.

---

## Features

- **Game Library** — Add, edit, and delete games from your personal inventory
- **IGDB Integration** — Search the [IGDB](https://www.igdb.com/) database to auto-fill game metadata (name, cover art, release date, summary, genres, developer, publisher)
- **Completion Tracking** — Mark games as: Unplayed, Unfinished, Completed, 100% Completed, Abandoned, Multiplayer Only, or Can't Be Completed
- **5-Star Rating** — Rate your games (abandoned games are automatically set to 0 stars)
- **Platform Support** — PC (Steam / Epic Games / EA Origin), Nintendo, Sega, Xbox — multiple platforms per game
- **Comments** — Add personal notes up to 400 characters per game
- **Box Art Storage** — Cover images are downloaded and stored locally; they survive container restarts and rebuilds
- **Grid & List Views** — Toggle between a visual card grid and a compact list table
- **Filtering** — Filter by platform, status, and rating
- **Sorting** — Sort by name, rating, status, release date, or date added (ascending/descending)
- **Statistics Dashboard** — Overview of your collection: totals, completion breakdown, rating distribution, platform breakdown
- **Persistent Storage** — All data (SQLite database + images) is stored in a Docker volume and survives restarts/rebuilds
- **Single-user** — No login or user management required

---

## Quick Start

### 1. Clone / download the project

```bash
git clone <repo-url> GameLibrarian
cd GameLibrarian
```

### 2. (Optional) Configure IGDB

IGDB integration requires free Twitch Developer credentials.

1. Register at [https://dev.twitch.tv/console](https://dev.twitch.tv/console)
2. Create an application — note your **Client ID** and **Client Secret**
3. Create a `.env` file in the project root:

```env
IGDB_CLIENT_ID=your_client_id_here
IGDB_CLIENT_SECRET=your_client_secret_here
```

Without these, the app works fully — you just fill in game details manually.

### 3. Build and run

```bash
docker compose up -d --build
```

The app will be available at **http://localhost:5000**

### 4. Stop

```bash
docker compose down
```

Data is preserved in the `gamelibrarian_data` Docker volume.

---

## Data Persistence

All persistent data lives in a named Docker volume (`gamelibrarian_data`) mounted at `/data` inside the container:

| Path | Contents |
|------|----------|
| `/data/gamelibrary.db` | SQLite database (all game records) |
| `/data/images/` | Downloaded cover art images |

This data survives `docker compose down`, container rebuilds, and image updates.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask, SQLite |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Container | Docker + Docker Compose |
| Game Data | IGDB API (via Twitch OAuth2) |

---

## Development (without Docker)

```bash
pip install -r requirements.txt
export DATA_DIR=./data
export IGDB_CLIENT_ID=...      # optional
export IGDB_CLIENT_SECRET=...  # optional
python app.py
```

---

## Platforms

| Key | Display Name |
|-----|-------------|
| `steam` | PC · Steam |
| `epic` | PC · Epic Games |
| `ea_origin` | PC · EA Origin |
| `nintendo` | Nintendo |
| `sega` | Sega |
| `xbox` | Xbox |

---

## License

MIT — do whatever you like with it.
