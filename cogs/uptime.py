from discord.ext import commands
import logging
import os
from uptime_kuma_api import UptimeKumaApi, UptimeKumaException
from typing import Tuple, Optional
from dotenv import load_dotenv

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()

class Uptime(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("plexwatch_bot.uptime")
        self.api_url = os.getenv("UPTIME_URL")
        self.username = os.getenv("UPTIME_USERNAME")
        self.password = os.getenv("UPTIME_PASSWORD")
        self.monitor_id = int(os.getenv("UPTIME_MONITOR_ID"))

    def get_uptime_data(self) -> Tuple[
        Optional[float], Optional[float], Optional[float],
        Optional[float], Optional[float], Optional[float], Optional[str]
    ]:
        """Fetch uptime statistics from Uptime Kuma for specified monitor."""
        try:
            with UptimeKumaApi(self.api_url) as api:
                api.login(self.username, self.password)
                beats_24h = api.get_monitor_beats(self.monitor_id, 24)
                beats_7d = api.get_monitor_beats(self.monitor_id, 7 * 24)
                beats_30d = api.get_monitor_beats(self.monitor_id, 30 * 24)

                def calculate_uptime_and_online_time(beats: list, period_hours: int) -> Tuple[float, float]:
                    up_count = sum(1 for beat in beats if beat["status"].name == "UP")
                    uptime_percent = (up_count / len(beats)) * 100 if beats else 0.0
                    online_minutes = up_count * (period_hours * 60 / len(beats)) if beats else 0
                    return uptime_percent, online_minutes

                uptime_24h, online_24h = calculate_uptime_and_online_time(beats_24h, 24)
                uptime_7d, online_7d = calculate_uptime_and_online_time(beats_7d, 7 * 24)
                uptime_30d, online_30d = calculate_uptime_and_online_time(beats_30d, 30 * 24)

                last_offline = next(
                    (beat["time"] for beat in reversed(beats_30d) if beat["status"].name == "DOWN"),
                    None,
                )
                return uptime_24h, online_24h, uptime_7d, online_7d, uptime_30d, online_30d, last_offline
        except UptimeKumaException as e:
            self.logger.error(f"Uptime Kuma API error: {e}")
            return None, None, None, None, None, None, None

    def format_online_time(self, minutes: float) -> str:
        """Convert online time in minutes to a human-readable hours and minutes string."""
        hours = int(minutes // 60)
        remaining_minutes = int(minutes % 60)
        return f"{hours}h {remaining_minutes}m" if hours > 0 else f"{remaining_minutes}m"

async def setup(bot: commands.Bot) -> None:
    """Set up the Uptime cog for the bot."""
    await bot.add_cog(Uptime(bot))