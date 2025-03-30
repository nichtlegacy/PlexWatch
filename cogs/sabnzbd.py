from discord.ext import commands
import aiohttp
import logging
import os
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from urllib.parse import urljoin

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()

class SABnzbd(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("plexwatch_bot.sabnzbd")
        self.SABNZBD_URL = os.getenv("SABNZBD_URL")
        self.SABNZBD_API_KEY = os.getenv("SABNZBD_API_KEY")

        # Path to config.json
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.CONFIG_FILE = os.path.join(self.current_dir, "..", "data", "config.json")
        self.keywords = self._load_keywords()

    def _load_keywords(self) -> List[str]:
        """Load SABnzbd keywords from config.json with defaults if unavailable."""
        default_keywords = ["AC3", "DL", "German", "1080p", "2160p", "4K", "GERMAN"]
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("sabnzbd", {}).get("keywords", default_keywords)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load SABnzbd keywords: {e}. Using defaults.")
            return default_keywords

    async def get_sabnzbd_info(self) -> Dict[str, Any]:
        """Fetch download queue and disk space information from SABnzbd API."""
        url = urljoin(self.SABNZBD_URL, "api")
        params = {"apikey": self.SABNZBD_API_KEY, "output": "json", "mode": "queue"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if not response.ok:
                        error_text = await response.text()
                        self.logger.error(f"SABnzbd API error - Status {response.status}: {error_text}")
                        return {"downloads": [], "diskspace1": "Unknown", "diskspacetotal1": "Unknown"}
                    data = await response.json()

            queue = data.get("queue", {})
            slots = queue.get("slots", [])
            disk_space = queue.get("diskspace1", "Unknown")
            total_disk_space = queue.get("diskspacetotal1", "Unknown")

            if not slots:
                return {
                    "downloads": [],
                    "diskspace1": self._format_size_diskspace(disk_space),
                    "diskspacetotal1": self._format_size_diskspace(total_disk_space, "TB"),
                }

            downloads = [
                {
                    "name": item.get("filename", "Unknown"),
                    "progress": float(item.get("percentage", "0")),
                    "timeleft": item.get("timeleft", "Unknown"),
                    "speed": self._format_speed_from_kbps(queue.get("kbpersec", "0")),
                    "size": self._format_size(item.get("size", "Unknown")),
                }
                for item in slots
            ]
            return {
                "downloads": downloads,
                "diskspace1": self._format_size_diskspace(disk_space),
                "diskspacetotal1": self._format_size_diskspace(total_disk_space, "TB"),
            }
        except aiohttp.ClientError as e:
            self.logger.error(f"SABnzbd API request failed: {e}")
            return {"downloads": [], "diskspace1": "Unknown", "diskspacetotal1": "Unknown"}

    def _format_size(self, size: str) -> str:
        """Convert size to human-readable format with appropriate units."""
        try:
            size_float = float(size)
            for unit in ["B", "KB", "MB", "GB", "TB"]:
                if size_float < 1024:
                    return f"{size_float:.2f} {unit}"
                size_float /= 1024
            return f"{size_float:.2f} TB"  # Fallback for very large sizes
        except ValueError:
            return size

    def _format_speed_from_kbps(self, kbpersec: str) -> str:
        """Convert speed from KB/s to human-readable format."""
        try:
            speed_float = float(kbpersec)
            for unit in ["KB", "MB", "GB", "TB"]:
                if speed_float < 1024:
                    return f"{speed_float:.2f} {unit}/s"
                speed_float /= 1024
            return f"{speed_float:.2f} TB/s"
        except ValueError:
            return f"{kbpersec} KB/s"
    
    def _format_size_diskspace(self, size: str, unit: str = "GB") -> str:
        """Format disk space size into specified unit (GB or TB)."""
        try:
            size_float = float(size)
            if unit == "TB":
                size_float /= 1024
            return f"{size_float:.2f}{unit}"
        except ValueError:
            return size

    def format_download_info(self, download: Dict[str, Any], index: int) -> str:
        """Format download details into a Discord-friendly string with numbered emoji."""
        try:
            number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
            emoji = number_emojis[index] if index < len(number_emojis) else "➡️"
            progress_percent = float(download["progress"])
            progress_bar = f"[{'▓' * int(progress_percent / 10)}{'░' * (10 - int(progress_percent / 10))}]"
            name = download["name"]
            min_pos = min(
                [name.find(kw) for kw in self.keywords if kw in name], default=len(name)
            )
            name = name[:min_pos].strip()
            if len(name) > 40:
                name = name[:37] + "..."

            return (
                f"**```{emoji} {name}\n"
                f"└─ {progress_bar} {progress_percent:.1f}% | {download['timeleft']} remaining\n"
                f" └─ 📊 {download['speed']} | Size: {download['size']}```**"
            )
        except (ValueError, KeyError) as e:
            self.logger.error(f"Error formatting download info: {e}")
            return "```❓ Download could not be loaded```"

async def setup(bot: commands.Bot) -> None:
    """Set up the SABnzbd cog for the bot."""
    await bot.add_cog(SABnzbd(bot))