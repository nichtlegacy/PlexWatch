import discord
from discord.ext import commands
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
import asyncio
import platform
from typing import List

# Configure event loop policy for Windows compatibility
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN must be set in .env file")
AUTHORIZED_USERS: List[int] = [
    int(user_id) for user_id in os.getenv("DISCORD_AUTHORIZED_USERS", "").split(",") if user_id
]

# Setup logging with rotation
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
bot_logger = logging.getLogger("plexwatch_bot")
bot_logger.setLevel(logging.DEBUG)
file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "plexwatch_debug.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
bot_logger.addHandler(file_handler)

# Initialize bot with intents and command prefix
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

def is_authorized(interaction: discord.Interaction) -> bool:
    """Check if the user is authorized to execute privileged commands."""
    return interaction.user.id in AUTHORIZED_USERS

async def load_cogs() -> None:
    """Load all Python files in the 'cogs' directory as bot extensions."""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and not filename.startswith("__"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                bot_logger.info(f"Loaded cog: {filename[:-3]}")
            except commands.ExtensionError as e:
                bot_logger.error(f"Failed to load cog {filename[:-3]}: {e}")

@bot.event
async def on_ready() -> None:
    """Handle bot startup: log readiness, load cogs, and sync command tree."""
    bot_logger.info(f"Bot is online as {bot.user.name}")
    await load_cogs()
    try:
        await tree.sync()
        bot_logger.info("Command tree synced")
    except discord.HTTPException as e:
        bot_logger.error(f"Failed to sync command tree: {e}")

@tree.command(name="load", description="Load a specific cog")
async def load(interaction: discord.Interaction, cog: str) -> None:
    """Load a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return
    try:
        await bot.load_extension(f"cogs.{cog}")
        await interaction.followup.send(f"✅ Cog `{cog}` loaded successfully!")
        bot_logger.info(f"Cog {cog} loaded by {interaction.user}")
    except commands.ExtensionError as e:
        await interaction.followup.send(f"❌ Error loading cog `{cog}`: `{e}`")
        bot_logger.error(f"Error loading cog {cog}: {e}")

@tree.command(name="unload", description="Unload a specific cog")
async def unload(interaction: discord.Interaction, cog: str) -> None:
    """Unload a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return
    try:
        await bot.unload_extension(f"cogs.{cog}")
        await interaction.followup.send(f"✅ Cog `{cog}` unloaded successfully!")
        bot_logger.info(f"Cog {cog} unloaded by {interaction.user}")
    except commands.ExtensionError as e:
        await interaction.followup.send(f"❌ Error unloading cog `{cog}`: `{e}`")
        bot_logger.error(f"Error unloading cog {cog}: {e}")

@tree.command(name="reload", description="Reload a specific cog")
async def reload(interaction: discord.Interaction, cog: str) -> None:
    """Reload a specified cog if the user is authorized."""
    await interaction.response.defer(ephemeral=True)
    if not is_authorized(interaction):
        await interaction.followup.send("❌ You are not authorized to execute this command.")
        return
    try:
        await bot.reload_extension(f"cogs.{cog}")
        await interaction.followup.send(f"✅ Cog `{cog}` reloaded successfully!")
        bot_logger.info(f"Cog {cog} reloaded by {interaction.user}")
    except commands.ExtensionError as e:
        await interaction.followup.send(f"❌ Error reloading cog `{cog}`: `{e}`")
        bot_logger.error(f"Error reloading cog {cog}: {e}")

@tree.command(name="cogs", description="List all available cogs")
async def list_cogs(interaction: discord.Interaction) -> None:
    """Display a list of available and loaded cogs in an embed."""
    cogs_list = [f[:-3] for f in os.listdir("./cogs") if f.endswith(".py") and not f.startswith("__")]
    loaded_cogs = [ext.split(".")[-1] for ext in bot.extensions.keys()]

    embed = discord.Embed(title="Cog Manager - Overview", color=discord.Color.blue())
    for cog in cogs_list:
        status = "🟢 Loaded" if cog in loaded_cogs else "🔴 Not Loaded"
        embed.add_field(name=cog, value=status, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure as e:
        bot_logger.error(f"Failed to start bot: Invalid token - {e}")
    except Exception as e:
        bot_logger.error(f"Unexpected error starting bot: {e}")