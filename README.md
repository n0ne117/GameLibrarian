# GameLibrarian

A self-hosted, dockerized web application for organizing your PC and console game collection.

> **Written by Claude (Anthropic)** — AI-assisted software development.

---

## Features

- **Game Library** — Add, edit, and delete games from your personal inventory
- **IGDB Integration** — Search the [IGDB](https://www.igdb.com/) database to auto-fill game metadata (name, cover art, release date, summary, genres, developer, publisher)
- **Completion Tracking** — Mark games as: Now Playing, Unplayed, Unfinished, Completed, Abandoned, Multiplayer Only, or Can't Be Completed. Games you're currently playing are pinned to the top of the library
- **5-Star Rating** — Rate your games (abandoned games are automatically set to 0 stars)
- **Platform Support** — Steam, Epic Games, EA Origin, GoG, Blizzard, Microsoft, Nintendo, Sega, Xbox, PlayStation — multiple platforms per game
- **Steam Integration** — Play time and achievement progress synced from your Steam account, with a Steam Store link on every Steam game (see [Steam Integration](#steam-integration))
- **Steam Wishlist** — Browse your Steam wishlist, see which games you already own, and add the rest to your library in one click (see [Wishlist](#wishlist))
- **Hours Played** — Tracked per game; filled automatically for Steam games, editable by hand for every platform
- **Comments** — Add personal notes up to 400 characters per game
- **Box Art Storage** — Cover images are downloaded and stored locally; they survive container restarts and rebuilds
- **Grid & List Views** — Toggle between a visual card grid and a compact list table
- **Filtering** — Filter by platform, status, and rating
- **Sorting** — Sort by name, rating, status, release date, or date added (ascending/descending)
- **Statistics Dashboard** — Overview of your collection: totals, total hours played, completion breakdown, rating distribution, platform breakdown
- **Settings Page** — Enter Steam and IGDB credentials in the browser instead of editing config files
- **Persistent Storage** — All data (SQLite database + images) lives in `./data` and survives restarts/rebuilds
- **Single-user** — No login or user management required

---

## Quick Start

### 1. Clone / download the project

```bash
git clone <repo-url> GameLibrarian
cd GameLibrarian
```

### 2. (Optional) Configure credentials

Both integrations are optional — without them the app works fully, you just fill in game details by hand. Credentials can be set either in the **Settings** page of the running app or in a `.env` file in the project root (copy `.env.example`):

```env
IGDB_CLIENT_ID=your_client_id_here
IGDB_CLIENT_SECRET=your_client_secret_here
STEAM_API_KEY=your_steam_web_api_key_here
STEAM_WISHLIST_URL=https://store.steampowered.com/wishlist/profiles/7656119XXXXXXXXXX/
```

Values saved in the Settings page take precedence over the `.env` file.

**IGDB** requires free Twitch Developer credentials:

1. Register at [https://dev.twitch.tv/console](https://dev.twitch.tv/console)
2. Create an application — note your **Client ID** and **Client Secret**

**Steam** requirements are described under [Steam Integration](#steam-integration).

### 3. Build and run

```bash
docker compose up -d --build
```

The app will be available at **http://localhost:5000**

### 4. Update

```bash
git pull && docker compose up -d --build
```

### 5. Stop

```bash
docker compose down
```

Data is preserved in the `./data` folder.

---

## Steam Integration

### Requirements

- A free **Steam Web API key** — [get one here](https://steamcommunity.com/dev/apikey)
- Your **numeric** profile URL, e.g. `https://store.steampowered.com/wishlist/profiles/7656119XXXXXXXXXX/`. Vanity URLs (`…/id/yourname/`) are not supported. Your SteamID64 is shown in the URL of your Steam profile if you have no custom URL set, or on sites like [steamid.io](https://steamid.io)
- In Steam → **Edit Profile → Privacy Settings**, set **Game details** to **Public** — otherwise play time, achievements, and the wishlist can't be read

Enter the URL and key in **Settings → Steam Integration**, then click **Save Settings**.

### Steam App IDs

Play time, achievements, and the store link are matched to your library by Steam App ID:

- When you tick the **Steam** platform on a game, the App ID is looked up automatically on the Steam Store (exact name match). You can also type it in yourself — it's the number in the store URL, e.g. `730` for `store.steampowered.com/app/730/`
- On startup, the app fills in missing App IDs for all Steam games in the background (one Steam Store lookup roughly every half second, so a large library takes a few minutes)

### Play time & achievements

- **Sync Steam Data** in Settings updates play time and achievement progress for every library game with a Steam App ID. It runs in the background; large libraries can take a few minutes
- A sync also runs automatically on startup if the last one is more than an hour old
- Synced play time overwrites the **Hours Played** field for Steam games. Achievements are shown read-only in the game's edit dialog

---

## Wishlist

The **Wishlist** tab shows your Steam wishlist in your wishlist priority order:

- Names, cover art, and release dates come from IGDB (Steam App ID → IGDB game). Without IGDB credentials, games show the Steam header image and `Steam App <id>` as the name
- **Already Own** — wishlist games that are already in your library, matched by IGDB ID or by name. Click one to open it in the library
- **Want to Play** — everything else. **+ Add to Library** opens the Add Game dialog pre-filled from IGDB
- **Search** filters the wishlist by name as you type (ignores case and accents, so `ragnarok` finds *Ragnarök*)
- The wishlist is cached for 24 hours. **Refresh** fetches it from Steam again immediately

The wishlist needs a Steam Web API key and a public profile — see [Steam Integration](#steam-integration).

---

## Data Persistence

All persistent data lives in the `./data` folder next to `docker-compose.yml`, mounted at `/data` inside the container:

| Path | Contents |
|------|----------|
| `data/gamelibrary.db` | SQLite database (games, settings, wishlist cache) |
| `data/images/` | Downloaded cover art images |

This data survives `docker compose down`, container rebuilds, and image updates. Back up the `data` folder to back up everything, including credentials saved in Settings.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask, SQLite |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Container | Docker + Docker Compose |
| Game Data | IGDB API (via Twitch OAuth2) |
| Steam Data | Steam Web API, Steam Store search |

---

## Development (without Docker)

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
export DATA_DIR=./data
export IGDB_CLIENT_ID=...      # optional
export IGDB_CLIENT_SECRET=...  # optional
export STEAM_API_KEY=...       # optional
export STEAM_WISHLIST_URL=...  # optional
python app.py
```

---

## Platforms

| Key | Display Name |
|-----|-------------|
| `steam` | Steam |
| `epic` | Epic Games |
| `ea_origin` | EA Origin |
| `gog` | GoG |
| `blizzard` | Blizzard |
| `microsoft` | Microsoft |
| `nintendo` | Nintendo |
| `sega` | Sega |
| `xbox` | Xbox |
| `playstation` | PlayStation |

---

## License

MIT — do whatever you like with it.
