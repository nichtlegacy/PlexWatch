# PlexWatch - Your Plex Dashboard in Discord

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Version](https://img.shields.io/badge/version-1.0.0-green.svg)
![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)
![Discord.py](https://img.shields.io/badge/discord.py-2.0+-blueviolet.svg)
![Plex](https://img.shields.io/badge/plex-compatible-orange.svg)

PlexWatch is a Discord bot that brings your Plex media server to life with a real-time dashboard. Monitor active streams, track SABnzbd downloads, and check server uptime—all directly in your Discord server. Designed for Plex enthusiasts, PlexWatch delivers a sleek, embed-based interface to keep you informed about your media ecosystem.


## Features

- **Plex Monitoring**: Displays active streams with details like title, user, progress, quality, and player info (up to 8 streams).
- **SABnzbd Integration**: Tracks ongoing downloads with progress, speed, and size.
- **Uptime Tracking**: Shows server uptime over 24h, 7d, and 30d with percentage and duration.
- **Customizable Dashboard**: Updates every minute with a clean Discord embed, fully configurable via JSON.
- **Bot Presence**: Reflects Plex status and stream count in the bot's Discord status.
- **Logging**: Detailed logs for debugging and tracking bot activity.


## Screenshots

Here’s how PlexWatch looks in action:

- **Dashboard Example**:  
  ![PlexWatch Dashboard](https://i.imgur.com/vAVrjvh.png)

- **Server Offline Status**:  
  ![PlexWatch Dashboard](https://i.imgur.com/QSiFpWP.png)


## Project Structure

```
📦 PlexWatch
├─ /cogs                # Bot extensions (cogs) for modular functionality
│  ├─ plex_core.py     # Core Plex monitoring and dashboard logic
│  ├─ sabnzbd.py       # SABnzbd download tracking
│  └─ uptime.py        # Server uptime monitoring
├─ /data               # Configuration and state files
│  ├─ config.json      # Bot settings (e.g., dashboard config, Plex sections)
│  ├─ dashboard_message_id.json  # Stores the ID of the dashboard message
│  └─ user_mapping.json  # Maps Plex usernames to display names
├─ /logs               # Log files for debugging
│  └─ plexwatch_debug.log  # Rotated debug logs (updated daily, 7-day backup)
├─ .env                # Environment variables (private, not tracked)
├─ .env.example        # Template for .env configuration
├─ .gitignore          # Git ignore rules (e.g., logs, .env)
├─ main.py             # Entry point for the bot
├─ README.md           # This file
└─ requirements.txt    # Python dependencies
```


## Setup

### Prerequisites
- Python 3.8+
- A Plex Media Server with API access
- SABnzbd (optional, for download tracking)
- Uptime Kuma (optional, for uptime monitoring)
- A Discord bot token

### Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/nichtlegacy/PlexWatch.git
   cd PlexWatch
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` with your details (see below).

4. **Run the Bot**:
   ```bash
   python main.py
   ```

### Environment Variables (`.env`)
The `.env` file stores sensitive configuration. Use the following format:

```
DISCORD_TOKEN=your_discord_bot_token
DISCORD_AUTHORIZED_USERS=123456789012345678,987654321098765432  # Comma-separated user IDs
PLEX_URL=https://your-plex-server:32400
PLEX_TOKEN=your_plex_token
CHANNEL_ID=your_discord_channel_id
SABNZBD_URL=http://your-sabnzbd-server:8080
SABNZBD_API_KEY=your_sabnzbd_api_key
UPTIME_URL=https://your-uptime-kuma-server:3001
UPTIME_USERNAME=your_uptime_kuma_username
UPTIME_PASSWORD=your_uptime_kuma_password
UPTIME_MONITOR_ID=your_monitor_id
```

- `DISCORD_TOKEN`: Your Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications).
- `DISCORD_AUTHORIZED_USERS`: List of user IDs allowed to manage cogs (e.g., `!load`, `!unload`).
- `PLEX_URL`: URL to your Plex server (include protocol and port).
- `PLEX_TOKEN`: Your Plex API token (see [Plex Support](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
- `CHANNEL_ID`: Discord channel ID where the dashboard embed appears.
- `SABNZBD_URL` & `SABNZBD_API_KEY`: Optional, for SABnzbd integration (get API key from SABnzbd settings).
- `UPTIME_URL`: Optional, URL to your Uptime Kuma server (e.g., https://uptime.example.com:3001)
- `UPTIME_USERNAME`: Optional, Username for your Uptime Kuma instance
- `UPTIME_PASSWORD`: Optional, Password for your Uptime Kuma instance
- `UPTIME_MONITOR_ID`: Optional, The specific monitor ID from Uptime Kuma to track server uptime


## Configuration

PlexWatch is customized via `/data/config.json`. Below is the structure with example values based on your setup:

```json
{
    "dashboard": {
        "name": "Your Plex Dashboard",
        "icon_url": "https://example.com/icon.png",
        "footer_icon_url": "https://example.com/icon.png"
    },
    "plex_sections": {
        "show_all": false,
        "sections": {
            "Movies": {
                "display_name": "Movies",
                "emoji": "🎥",
                "show_episodes": false
            },
            "Shows": {
                "display_name": "Shows",
                "emoji": "📺",
                "show_episodes": true
            },
            "Documentaries": {
                "display_name": "Documentaries",
                "emoji": "📚",
                "show_episodes": false
            }
        }
    },
    "presence": {
        "sections": [
            {
                "section_title": "Movies",
                "display_name": "Movies",
                "emoji": "🎥"
            },
            {
                "section_title": "Shows",
                "display_name": "Shows",
                "emoji": "📺"
            }
        ],
        "offline_text": "🔴 Server Offline!",
        "stream_text": "{count} active Stream{s} 🟢"
    },
    "cache": {
        "library_update_interval": 900
    },
    "sabnzbd": {
        "keywords": ["AC3", "DL", "German", "1080p", "2160p", "4K", "GERMAN", "English"]
    }
}
```

### Configuration Details
- **`dashboard`**:
  - `name`: Title of the Discord embed (e.g., "LEGACYVault Dashboard").
  - `icon_url`: URL to the dashboard icon (displayed in author and thumbnail).
  - `footer_icon_url`: URL to the footer icon.

- **`plex_sections`**:
  - `show_all`: If `true`, all Plex library sections are shown; if `false`, only listed sections are included.
  - `sections`: Defines displayed Plex libraries.
    - Keys match your Plex library titles (e.g., "Movies", "Shows").
    - `display_name`: Name shown in the dashboard.
    - `emoji`: Emoji for visual flair (e.g., "🎥" for movies).
    - `show_episodes`: If `true`, episode counts are shown (useful for series).

- **`presence`**:
  - `sections`: Libraries shown in the bot’s Discord status when idle.
    - `section_title`: Matches `plex_sections` keys.
    - `display_name`: Name in the status.
    - `emoji`: Emoji in the status.
  - `offline_text`: Bot status when Plex is offline.
  - `stream_text`: Bot status with active streams (e.g., "3 active Streams 🟢").

- **`cache`**:
  - `library_update_interval`: Time (in seconds) between Plex library cache updates (default: 900 = 15 minutes).

- **`sabnzbd`**:
  - `keywords`: List of keywords used to trim download names. The bot cuts off the name at the first occurrence of any keyword (e.g., "Movie.Name.German.1080p" becomes "Movie Name"), then limits it to 40 characters (truncating with "..." if longer). This ensures clean, readable names in the dashboard.

## User Mapping

The `/data/user_mapping.json` file allows you to personalize Plex usernames by mapping them to custom display names shown in the dashboard. This keeps the interface clean and user-friendly.

**Example `user_mapping.json`**:
```json
{
    "nichtlegacy": "LEGACY",
    "plexfan99": "Fan",
    "moviebuff": "Buff"
}
```

- **Key**: The exact Plex username (case-sensitive).
- **Value**: The custom name displayed in the dashboard.

If a username is listed, its mapped name is used (e.g., "Alex" instead of "user123"); otherwise, the original Plex username is shown.

## Logging
Logs are stored in `/logs/plexwatch_debug.log`:
- **Format**: `timestamp - logger_name - level - message` (e.g., `2025-03-12 20:37:34,092 - plexwatch_bot - INFO - Bot is online`).
- **Rotation**: Daily, with a 7-day backup (older logs are overwritten).
- **Levels**: DEBUG, INFO, WARNING, ERROR – useful for troubleshooting.

Example log entries:
```
2025-03-12 20:37:34,509 - plexwatch_bot - INFO - Loaded cog: plex_core
2025-03-12 20:37:35,050 - plexwatch_bot - ERROR - Failed to connect to Plex server: Timeout
```

## Commands
PlexWatch uses Discord slash commands (synced on startup):
- `/load <cog>`: Load a cog (e.g., `plex_core`).
- `/unload <cog>`: Unload a cog.
- `/reload <cog>`: Reload a cog.
- `/cogs`: List all available cogs with their status.

*Note*: Only users listed in `DISCORD_AUTHORIZED_USERS` can use these commands.

## Acknowledgements
- [Plex](https://www.plex.tv) - For providing an excellent media server platform that powers the core monitoring capabilities of PlexWatch.
- [PlexAPI](https://github.com/pkkid/python-plexapi) - A Python library for interacting with Plex servers, essential for stream and library tracking.
- [discord.py](https://github.com/Rapptz/discord.py) - The backbone of the Discord bot functionality, making embeds and real-time updates possible.
- [SABnzbd](https://sabnzbd.org) - A powerful download manager integrated to monitor ongoing downloads within the dashboard.
- [Uptime Kuma](https://uptime.kuma.pet) - A lightweight tool for monitoring server uptime, integrated for availability tracking over 24h, 7d, and 30d.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.