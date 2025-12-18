import discord
from discord.ext import commands, tasks
from plexapi.server import PlexServer
import time
import json
import yaml
import os
import shutil
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import io
import aiohttp

from dotenv import load_dotenv

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not RUNNING_IN_DOCKER:
    load_dotenv()


class StreamDetailsView(discord.ui.View):
    """Persistent view for stream detail buttons."""
    
    def __init__(self, plex_core_instance):
        super().__init__(timeout=None)  # Persistent view
        self.plex_core = plex_core_instance
        self.logger = logging.getLogger("plexwatch_bot.plex.view")
    
    async def create_buttons(self, sessions: List[Any]) -> None:
        """Create/update buttons for active streams. Only works with Tautulli configured."""
        self.clear_items()
        
        # Clear old sessions before adding new ones
        self.plex_core.active_sessions.clear()
        
        # Only show buttons if Tautulli is configured
        if not self.plex_core.TAUTULLI_URL or not self.plex_core.TAUTULLI_API_KEY:
            return
        
        # Limit to 8 streams (dashboard shows max 8)
        for idx, session in enumerate(sessions[:8], start=1):
            try:
                # Validate session has required attributes
                if not hasattr(session, 'sessionKey'):
                    self.logger.warning(f"Session {idx} missing sessionKey attribute")
                    continue
                
                # Create a unique session key
                session_key = f"{session.sessionKey}_{idx}"
                
                # Store session in plex_core for later retrieval
                self.plex_core.active_sessions[session_key] = session
                
                # Get user for button label
                user = session.usernames[0] if hasattr(session, 'usernames') and session.usernames else "Unknown"
                displayed_user = self.plex_core.user_mapping.get(user, user)
                
                # Truncate long usernames for button label
                if len(displayed_user) > 15:
                    displayed_user = displayed_user[:12] + "..."
                
                # Get emoji based on media type (same logic as dashboard)
                section_title = getattr(session, "librarySectionTitle", "Unknown")
                stats = self.plex_core.get_library_stats()
                content_emoji = stats.get(section_title, {}).get("emoji") or (
                    "🎵" if getattr(session, "type", "") == "track" else
                    "🎥" if getattr(session, "type", "") in ["movie", None] else "📺"
                )
                
                # Create button
                button = discord.ui.Button(
                    label=f"Stream {idx} - {displayed_user}",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"stream_details:{session_key}",
                    emoji=content_emoji
                )
                button.callback = self._create_callback(session_key)
                self.add_item(button)
            except Exception as e:
                self.logger.error(f"Error creating button for stream {idx}: {e}", exc_info=True)
    
    def _create_callback(self, session_key: str):
        """Create a callback function for a specific session."""
        async def callback(interaction: discord.Interaction):
            await self.show_stream_details(interaction, session_key)
        return callback
    
    async def show_stream_details(self, interaction: discord.Interaction, session_key: str) -> None:
        """Show detailed information about a specific stream."""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Check if Plex is connected
            if not self.plex_core.plex:
                await interaction.followup.send(
                    "❌ Plex server is not connected. Please try again later.",
                    ephemeral=True
                )
                return
            
            # Retrieve session from stored sessions
            session = self.plex_core.active_sessions.get(session_key)
            
            if not session:
                await interaction.followup.send(
                    "❌ This stream is no longer active or could not be found.",
                    ephemeral=True
                )
                return
            
            # Verify session is still valid by checking if it has required attributes
            if not hasattr(session, 'sessionKey'):
                self.logger.warning(f"Session {session_key} missing required attributes")
                await interaction.followup.send(
                    "❌ This stream session is invalid.",
                    ephemeral=True
                )
                return
            
            # Create detailed embed and file
            embed, file = await self._create_detailed_embed(session)
            
            # Check if embed creation failed
            if embed.title == "❌ Error":
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create view with Kill Stream button if user is authorized
            view = discord.ui.View(timeout=300)  # 5 minute timeout for kill button
            
            if interaction.user.id in self.plex_core.AUTHORIZED_USERS:
                kill_button = discord.ui.Button(
                    label="Kill Stream",
                    style=discord.ButtonStyle.danger,
                    emoji="⛔"
                )
                kill_button.callback = self._create_kill_callback(session_key)
                view.add_item(kill_button)
            
            # Send message with embed and optional file
            if file:
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except discord.errors.NotFound:
            self.logger.error(f"Interaction not found for session {session_key}")
        except discord.errors.HTTPException as e:
            self.logger.error(f"Discord HTTP error showing stream details: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Failed to send stream details due to a Discord error.",
                    ephemeral=True
                )
            except Exception:
                pass
        except Exception as e:
            self.logger.error(f"Unexpected error showing stream details: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An unexpected error occurred while retrieving stream details.",
                    ephemeral=True
                )
            except Exception:
                pass
    
    def _create_kill_callback(self, session_key: str):
        """Create a callback function for opening kill stream modal."""
        async def callback(interaction: discord.Interaction):
            # Check authorization first
            if interaction.user.id not in self.plex_core.AUTHORIZED_USERS:
                await interaction.response.send_message(
                    "❌ You are not authorized to kill streams.",
                    ephemeral=True
                )
                return
            
            # Create and show modal
            modal = KillStreamModal(self.plex_core, session_key)
            await interaction.response.send_modal(modal)
        return callback
    
    async def _create_detailed_embed(self, session) -> tuple[discord.Embed, Optional[discord.File]]:
        """Create a detailed embed with stream information from Tautulli. Returns (embed, file)."""
        file = None
        try:
            # Validate session object
            if not session or not hasattr(session, 'sessionKey'):
                raise ValueError("Session object is invalid")
            
            # Fetch Tautulli data (required)
            tautulli_data = await self.plex_core.fetch_tautulli_session(session.sessionKey)
            if not tautulli_data:
                raise ValueError("Could not fetch data from Tautulli")
            
            # Get user from Plex session (same as dashboard/button for consistency)
            user = session.usernames[0] if hasattr(session, 'usernames') and session.usernames else "Unknown"
            displayed_user = self.plex_core.user_mapping.get(user, user)
            
            # Build title from Tautulli
            media_type = tautulli_data.get("media_type", "movie")
            year = tautulli_data.get("year", "")
            
            if media_type == "episode":
                # For TV shows: "Show Name - S01E02 - Episode Title"
                show_name = tautulli_data.get("grandparent_title", "")
                season = int(tautulli_data.get("parent_media_index") or 0)
                episode = int(tautulli_data.get("media_index") or 0)
                episode_title = tautulli_data.get("title", "")
                title = f"{show_name} - S{season:02d}E{episode:02d} - {episode_title}"
                emoji = "📺"
            elif media_type == "track":
                # For music: "Artist - Track"
                artist = tautulli_data.get("grandparent_title", "")
                track = tautulli_data.get("title", "")
                title = f"{artist} - {track}"
                emoji = "🎵"
            else:
                # For movies: "Title (Year)"
                movie_title = tautulli_data.get("title", "Unknown")
                title = f"{movie_title} ({year})" if year else movie_title
                emoji = "🎥"
            
            section_title = tautulli_data.get("library_name", "Unknown")
            
            # Create embed
            embed = discord.Embed(
                title=f"{emoji} {title}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Get poster image from Tautulli
            file = await self.plex_core.get_tautulli_thumbnail(tautulli_data)
            if file:
                embed.set_thumbnail(url="attachment://poster.jpg")
            
            # Description (summary) from Tautulli
            summary = tautulli_data.get("summary", "")
            if summary and media_type != "track":
                if len(summary) > 300:
                    summary = summary[:297] + "..."
                embed.add_field(name="📝 Description", value=summary, inline=False)
            
            # Rating & Directors/Writers from Tautulli
            if media_type != "track":
                rating = tautulli_data.get("rating")
                has_rating = False
                if rating:
                    try:
                        embed.add_field(name="⭐ Rating", value=f"`{float(rating):.1f}/10`", inline=True)
                        has_rating = True
                    except (ValueError, TypeError):
                        pass
                
                # Directors (for movies) or Writers (for episodes)
                has_creator = False
                if media_type == "movie":
                    directors = tautulli_data.get("directors", [])
                    if directors:
                        director = directors[0] if isinstance(directors, list) else directors.split(",")[0].strip()
                        embed.add_field(name="🎬 Director", value=f"`{director}`", inline=True)
                        has_creator = True
                elif media_type == "episode":
                    writers = tautulli_data.get("writers", [])
                    if writers:
                        writer = writers[0] if isinstance(writers, list) else writers.split(",")[0].strip()
                        embed.add_field(name="✍️ Writer", value=f"`{writer}`", inline=True)
                        has_creator = True
                
                if has_rating and has_creator:
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            # User and Player info from Tautulli
            product_name = tautulli_data.get("player", "Unknown")
                
            embed.add_field(name="👤 User", value=f"`{displayed_user}`", inline=True)
            embed.add_field(name="📱 Player", value=f"`{product_name}`", inline=True)
            embed.add_field(name="📚 Library", value=f"`{section_title}`", inline=True)
            
            # Progress, Status & Connection Info (in one row)
            view_offset = int(tautulli_data.get("view_offset", 0) or 0)
            duration = int(tautulli_data.get("duration", 0) or 0)
            
            # Stream Status & Connection Info
            location = tautulli_data.get("location", "")
            secure = tautulli_data.get("secure", 0)
            relay = tautulli_data.get("relay", 0)
            state = tautulli_data.get("state", "playing")
            
            # Stream status
            state_emoji = "▶️" if state == "playing" else ("⏸️" if state == "paused" else "⏳")
            state_text = state.capitalize()
            status_info = f"`{state_emoji} {state_text}`"
            
            # Connection status
            location_emoji = "🏠" if location == "lan" else "🌐"
            location_text = "LAN" if location == "lan" else "WAN"
            secure_emoji = "🔒" if secure else "🔓"
            relay_text = " 🔀" if relay else ""
            connection_info = f"`{location_emoji} {location_text} {secure_emoji}{relay_text}`"
            
            # Progress information
            if duration > 0:
                # Tautulli provides these in milliseconds
                progress_percent = (view_offset / duration * 100)
                
                # Progress bar
                progress_bar = f"[{'▓' * int(progress_percent / 10)}{'░' * (10 - int(progress_percent / 10))}]"
                
                # Time formatting (Tautulli gives ms)
                current_time = str(timedelta(milliseconds=view_offset)).split(".")[0]
                total_time = str(timedelta(milliseconds=duration)).split(".")[0]
                
                # Remove leading zeros for hours if < 1 hour
                if current_time.startswith("0:"):
                    current_time = current_time[2:]
                if total_time.startswith("0:"):
                    total_time = total_time[2:]
                
                progress_value = f"`{progress_bar} {progress_percent:.1f}%`\n`{current_time} / {total_time}`"
            else:
                progress_value = "`N/A`"
            
            # Add all three in one row: Progress (left), Status (middle), Connection (right)
            embed.add_field(name="📊 Progress", value=progress_value, inline=True)
            embed.add_field(name="⏯️ Status", value=status_info, inline=True)
            embed.add_field(name="🌍 Connection", value=connection_info, inline=True)
            
            # --- File & Quality Info ---
            # Resolution
            resolution = tautulli_data.get("video_resolution", "Unknown")
            
            # Format resolution text
            def format_resolution(res):
                if not res or res == "Unknown":
                    return "Unknown"
                res_str = str(res).lower()
                if res_str == "4k" or res_str == "2160":
                    return "4K"
                elif res_str.isdigit():
                    return f"{res_str}p"
                else:
                    return res_str.upper()
            
            resolution = format_resolution(resolution)
            
            # Bitrate
            bitrate_val = int(tautulli_data.get('bitrate', 0) or 0)
            bitrate = f"{bitrate_val / 1000:.1f} Mbps" if bitrate_val > 0 else "Unknown"
            
            # File Size & Container
            file_size = tautulli_data.get("file_size", 0)
            container = tautulli_data.get("container", "Unknown").upper()
            
            # Display File Info Fields
            if media_type == "track":
                # For music
                audio_bitrate = tautulli_data.get("audio_bitrate", "Unknown")
                embed.add_field(name="🎵 Audio Quality", value=f"`{audio_bitrate} kbps`", inline=True)
                embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)
            else:
                # For video (movies/TV)
                embed.add_field(name="📺 Resolution", value=f"`{resolution}`", inline=True)
                embed.add_field(name="📊 Bitrate", value=f"`{bitrate}`", inline=True)
                if file_size:
                    try:
                        size_gb = int(file_size) / (1024**3)
                        embed.add_field(name="📁 File", value=f"`{size_gb:.2f} GB • {container}`", inline=True)
                    except (ValueError, TypeError):
                        embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)
                else:
                    embed.add_field(name="📁 Container", value=f"`{container}`", inline=True)
            
            # --- Transcoding Info from Tautulli ---
            transcode_text = []
            is_transcoding = tautulli_data.get("transcode_decision") == "transcode"
            
            # Check for throttled status
            is_throttled = tautulli_data.get("transcode_throttled", 0)
            throttled_text = " (Throttled)" if is_throttled else ""
            
            if is_transcoding:
                # Hardware Transcoding flags
                hw_decode = tautulli_data.get("transcode_hw_decoding", 0)
                hw_encode = tautulli_data.get("transcode_hw_encoding", 0)
                hw_text = " (HW)" if (hw_decode or hw_encode) else ""
                
                # Stream status
                transcode_text.append(f"**Stream:** Transcode{throttled_text}")
                
                # Container
                stream_container = tautulli_data.get("stream_container", "Unknown").upper()
                container_decision = tautulli_data.get("stream_container_decision", "copy")
                
                if container_decision == "transcode":
                    transcode_text.append(f"**Container:** Converting (`{container}` → `{stream_container}`)")
                else:
                    transcode_text.append(f"**Container:** `{container}` (Direct Stream)")
                
                # Video
                video_codec = tautulli_data.get("video_codec", "Unknown").upper()
                stream_video_codec = tautulli_data.get("stream_video_codec", "Unknown").upper()
                video_resolution = tautulli_data.get("video_resolution", "")
                stream_video_resolution = tautulli_data.get("stream_video_resolution", "")
                video_decision = tautulli_data.get("stream_video_decision", "copy")
                
                # Format video resolution (use same function as above)
                video_resolution = format_resolution(video_resolution)
                stream_video_resolution = format_resolution(stream_video_resolution)
                
                if video_decision == "transcode":
                    video_from = f"{video_codec}{hw_text} {video_resolution}".strip()
                    video_to = f"{stream_video_codec}{hw_text} {stream_video_resolution}".strip()
                    transcode_text.append(f"**Video:** Transcode (`{video_from}` → `{video_to}`)")
                else:
                    video_info = f"{video_codec} {video_resolution}".strip()
                    transcode_text.append(f"**Video:** Direct Stream (`{video_info}`)")
                
                # Audio
                audio_codec = tautulli_data.get("audio_codec", "Unknown").upper()
                stream_audio_codec = tautulli_data.get("stream_audio_codec", "Unknown").upper()
                audio_language = tautulli_data.get("audio_language", "")
                audio_channels = tautulli_data.get("audio_channels", "")
                stream_audio_channels = tautulli_data.get("stream_audio_channels", "")
                audio_decision = tautulli_data.get("stream_audio_decision", "copy")
                
                # Format audio channels (6 = 5.1, 2 = 2.0, 8 = 7.1)
                def format_channels(ch):
                    if not ch:
                        return ""
                    ch = str(ch)
                    if ch == "6":
                        return "5.1"
                    elif ch == "2":
                        return "2.0"
                    elif ch == "8":
                        return "7.1"
                    return ch
                
                audio_ch = format_channels(audio_channels)
                stream_audio_ch = format_channels(stream_audio_channels)
                
                if audio_decision == "transcode":
                    audio_from_parts = []
                    if audio_language:
                        audio_from_parts.append(audio_language)
                    audio_from_parts.append("-")
                    audio_from_parts.append(audio_codec)
                    if audio_ch:
                        audio_from_parts.append(audio_ch)
                    audio_from = " ".join(audio_from_parts)
                    
                    audio_to_parts = [stream_audio_codec]
                    if stream_audio_ch:
                        audio_to_parts.append(stream_audio_ch)
                    audio_to = " ".join(audio_to_parts)
                    
                    transcode_text.append(f"**Audio:** Transcode (`{audio_from}` → `{audio_to}`)")
                else:
                    transcode_text.append("**Audio:** Direct Stream")
                
                # Speed (nur anzeigen wenn > 0.0)
                speed = tautulli_data.get("transcode_speed")
                if speed:
                    try:
                        speed_float = float(speed)
                        if speed_float > 0.0:
                            transcode_text.append(f"**Speed:** `{speed_float:.1f}x`")
                    except (ValueError, TypeError):
                        pass
            
            # Subtitles (always show, even if None)
            sub_decision = tautulli_data.get("stream_subtitle_decision")
            subtitle_text = None
            
            if sub_decision and sub_decision not in ["none", ""]:
                sub_lang = tautulli_data.get("subtitle_language", "Unknown")
                sub_codec = tautulli_data.get("subtitle_codec", "Unknown").upper()
                forced = " (Forced)" if tautulli_data.get("subtitle_forced") else ""
                
                if sub_decision == "burn":
                    subtitle_text = f"Burn ({sub_lang} - {sub_codec}){forced}"
                elif sub_decision == "transcode":
                    subtitle_text = f"Converting ({sub_lang} - {sub_codec}){forced}"
                else:
                    subtitle_text = f"{sub_lang} ({sub_codec}){forced}"
                
                if is_transcoding:
                    transcode_text.append(f"**Subtitle:** {subtitle_text}")
            else:
                # Show "None" if no subtitles
                if is_transcoding:
                    transcode_text.append("**Subtitle:** None")

            # Display Transcoding / Playback Mode
            if is_transcoding:
                embed.add_field(
                    name="🔄 Transcoding",
                    value="\n".join(transcode_text) if transcode_text else "`Active`",
                    inline=False
                )
            else:
                # Direct Play
                direct_play_text = ["`Direct Play`"]
                
                # Subtitles for direct play
                if subtitle_text:
                    direct_play_text.append(f"**Subtitle:** {subtitle_text}")
                else:
                    direct_play_text.append("**Subtitle:** None")

                embed.add_field(
                    name="⏯️ Playback Mode",
                    value="\n".join(direct_play_text),
                    inline=False
                )
            
            # Footer: Title + Year
            dashboard_config = self.plex_core.config.get("dashboard", {})
            footer_icon = dashboard_config.get("footer_icon_url", "")
            
            # Build footer with title and year
            if media_type == "episode":
                footer_title = tautulli_data.get("grandparent_title", title)
            else:
                footer_title = tautulli_data.get("title", title)
            
            footer_text = f"{footer_title} ({year})" if year else footer_title
            embed.set_footer(text=footer_text, icon_url=footer_icon)
            
            # Set author with dashboard icon
            dashboard_name = dashboard_config.get("name", "Plex Dashboard")
            icon_url = dashboard_config.get("icon_url", "")
            if icon_url:
                embed.set_author(name=dashboard_name, icon_url=icon_url)
            
            return embed, file
            
        except Exception as e:
            self.logger.error(f"Error creating detailed embed: {e}", exc_info=True)
            # Return a basic error embed
            embed = discord.Embed(
                title="❌ Error",
                description="Failed to load stream details from Tautulli",
                color=discord.Color.red()
            )
            return embed, None


class KillStreamModal(discord.ui.Modal, title="Kill Stream"):
    """Modal for confirming and customizing kill stream message."""
    
    def __init__(self, plex_core_instance, session_key: str):
        super().__init__()
        self.plex_core = plex_core_instance
        self.session_key = session_key
        self.logger = logging.getLogger("plexwatch_bot.plex.modal")
        
        # Create text input for custom message
        self.reason_input = discord.ui.TextInput(
            label="Reason Message",
            placeholder="Stopped by administrator",
            default="Stopped by administrator",
            required=True,
            max_length=200,
            style=discord.TextStyle.short
        )
        self.add_item(self.reason_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission - kill the stream."""
        await interaction.response.defer(ephemeral=True)
        await self.kill_stream(interaction, self.reason_input.value)
    
    async def kill_stream(self, interaction: discord.Interaction, reason: str) -> None:
        """Kill a stream (authorized users only)."""
        try:
            # Double-check authorization
            if interaction.user.id not in self.plex_core.AUTHORIZED_USERS:
                self.logger.warning(
                    f"Unauthorized kill stream attempt by {interaction.user.name} (ID: {interaction.user.id})"
                )
                await interaction.followup.send(
                    "❌ You are not authorized to kill streams.",
                    ephemeral=True
                )
                return
            
            # Check if Plex is connected
            if not self.plex_core.plex:
                await interaction.followup.send(
                    "❌ Plex server is not connected. Cannot kill stream.",
                    ephemeral=True
                )
                return
            
            # Retrieve session
            session = self.plex_core.active_sessions.get(self.session_key)
            
            if not session:
                await interaction.followup.send(
                    "❌ This stream is no longer active.",
                    ephemeral=True
                )
                return
            
            # Get stream info for logging and embed (before killing)
            try:
                user = session.usernames[0] if hasattr(session, 'usernames') and session.usernames else "Unknown"
                title = self.plex_core._get_formatted_title(session)
                session_id = getattr(session, 'sessionKey', 'Unknown')
            except Exception as e:
                self.logger.error(f"Error extracting session info before kill: {e}")
                user = "Unknown"
                title = "Unknown"
                session_id = "Unknown"
            
            # Fetch Tautulli data for embed details (before killing)
            tautulli_data = None
            try:
                tautulli_data = await self.plex_core.fetch_tautulli_session(session.sessionKey)
            except Exception as e:
                self.logger.warning(f"Could not fetch Tautulli data for kill embed: {e}")
            
            # Kill the stream with custom reason
            try:
                session.stop(reason=reason)
            except AttributeError as e:
                self.logger.error(f"Session object missing stop method: {e}")
                await interaction.followup.send(
                    "❌ Failed to kill stream: Invalid session object.",
                    ephemeral=True
                )
                return
            except Exception as e:
                self.logger.error(f"Plex API error killing stream: {e}", exc_info=True)
                await interaction.followup.send(
                    f"❌ Failed to kill stream: Plex API error - {str(e)}",
                    ephemeral=True
                )
                return
            
            # Log the action
            self.logger.info(
                f"Stream killed by {interaction.user.name} (ID: {interaction.user.id}) - "
                f"User: {user}, Title: {title}, Session: {session_id}, Reason: {reason}"
            )
            
            # Remove from active sessions
            self.plex_core.active_sessions.pop(self.session_key, None)
            
            # Create embed for success message
            embed = discord.Embed(
                title="✅ Stream Killed Successfully",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            
            # Get media type and format title
            if tautulli_data:
                media_type = tautulli_data.get("media_type", "movie")
                year = tautulli_data.get("year", "")
                
                if media_type == "episode":
                    # For episodes: Show Name (Year) + Season/Episode field
                    show_name = tautulli_data.get("grandparent_title", title)
                    season = int(tautulli_data.get("parent_media_index") or 0)
                    episode = int(tautulli_data.get("media_index") or 0)
                    episode_title = tautulli_data.get("title", "")
                    
                    footer_title = f"{show_name} ({year})" if year else show_name
                    embed.add_field(name="📺 Series", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                    embed.add_field(name="📋 Episode", value=f"`S{season:02d}E{episode:02d} - {episode_title}`", inline=False)
                elif media_type == "track":
                    # For music: Artist - Track
                    artist = tautulli_data.get("grandparent_title", "")
                    track = tautulli_data.get("title", "")
                    footer_title = f"{artist} - {track}"
                    embed.add_field(name="🎵 Track", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
                else:
                    # For movies: Title (Year)
                    movie_title = tautulli_data.get("title", title)
                    footer_title = f"{movie_title} ({year})" if year else movie_title
                    embed.add_field(name="🎥 Movie", value=f"`{footer_title}`", inline=True)
                    embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                    embed.add_field(name="\u200b", value="\u200b", inline=True)
            else:
                # Fallback if no Tautulli data
                embed.add_field(name="📺 Title", value=f"`{title}`", inline=True)
                embed.add_field(name="🔑 Session", value=f"`{session_id}`", inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            embed.add_field(name="👤 User", value=f"`{user}`", inline=True)
            embed.add_field(name="💬 Reason", value=f"`{reason}`", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            # Footer and Author (like dashboard)
            dashboard_config = self.plex_core.config.get("dashboard", {})
            footer_icon = dashboard_config.get("footer_icon_url", "")
            icon_url = dashboard_config.get("icon_url", "")
            
            # Set thumbnail with dashboard icon
            if icon_url:
                embed.set_thumbnail(url=icon_url)
            
            if tautulli_data:
                media_type = tautulli_data.get("media_type", "movie")
                year = tautulli_data.get("year", "")
                
                if media_type == "episode":
                    footer_title = tautulli_data.get("grandparent_title", title)
                else:
                    footer_title = tautulli_data.get("title", title)
                
                footer_text = f"{footer_title} ({year})" if year else footer_title
            else:
                footer_text = title
            
            embed.set_footer(text=footer_text, icon_url=footer_icon)
            
            # Set author with dashboard icon
            dashboard_name = dashboard_config.get("name", "Plex Dashboard")
            if icon_url:
                embed.set_author(name=dashboard_name, icon_url=icon_url)
            
            # Send embed
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.errors.NotFound:
            self.logger.error(f"Interaction not found for kill stream {self.session_key}")
        except discord.errors.HTTPException as e:
            self.logger.error(f"Discord HTTP error killing stream: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Failed to kill stream due to a Discord error.",
                    ephemeral=True
                )
            except Exception:
                pass
        except Exception as e:
            self.logger.error(f"Unexpected error killing stream: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An unexpected error occurred while killing the stream.",
                    ephemeral=True
                )
            except Exception:
                pass


class PlexCore(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("plexwatch_bot.plex")

        # Load environment variables
        self.PLEX_URL = os.getenv("PLEX_URL")
        self.PLEX_TOKEN = os.getenv("PLEX_TOKEN")
        self.TAUTULLI_URL = os.getenv("TAUTULLI_URL")
        self.TAUTULLI_API_KEY = os.getenv("TAUTULLI_API_KEY")
        
        channel_id = os.getenv("CHANNEL_ID")
        if channel_id is None:
            self.logger.error("CHANNEL_ID not set in .env file")
            raise ValueError("CHANNEL_ID must be set in .env")
        self.CHANNEL_ID = int(channel_id)

        # File paths
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.MESSAGE_ID_FILE = os.path.join(self.current_dir, "..", "data", "dashboard_message_id.json")
        self.CONFIG_FILE = os.path.join(self.current_dir, "..", "data", "config.yaml")
        self.CONFIG_FILE_JSON = os.path.join(self.current_dir, "..", "data", "config.json")  # For backward compatibility
        self.USER_MAPPING_FILE_JSON = os.path.join(self.current_dir, "..", "data", "user_mapping.json")  # For backward compatibility

        # Auto-migrate from JSON to YAML if needed
        self._auto_migrate_config()

        # Initialize state
        self.config = self._load_config()
        self.plex: Optional[PlexServer] = None
        self.plex_start_time: Optional[float] = None
        self.dashboard_message_id = self._load_message_id()
        self.last_scan = datetime.now()
        self.offline_since: Optional[datetime] = None
        self.stream_debug = False

        # Cache settings
        self.library_cache: Dict[str, Dict[str, Any]] = {}
        self.last_library_update: Optional[datetime] = None
        self.library_update_interval = self.config.get("cache", {}).get("library_update_interval", 900)

        # Session tracking for stream details buttons
        self.active_sessions: Dict[str, Any] = {}  # Maps session_key to Plex session object
        
        # Load authorized users for Kill Stream functionality
        authorized_users_str = os.getenv("DISCORD_AUTHORIZED_USERS", "")
        self.AUTHORIZED_USERS: List[int] = [
            int(user_id) for user_id in authorized_users_str.split(",") if user_id
        ]

        # Initialize stream details view
        self.stream_view = StreamDetailsView(self)

        self.user_mapping = self._load_user_mapping()
        self.update_status.start()
        self.update_dashboard.start()

    def _auto_migrate_config(self) -> None:
        """Automatically migrate from JSON to YAML format if JSON files exist and YAML doesn't."""
        data_dir = os.path.join(self.current_dir, "..", "data")
        config_yaml_exists = os.path.exists(self.CONFIG_FILE)
        config_json_exists = os.path.exists(self.CONFIG_FILE_JSON)
        user_mapping_json_exists = os.path.exists(self.USER_MAPPING_FILE_JSON)
        
        # Only migrate if YAML doesn't exist but JSON does
        if not config_yaml_exists and (config_json_exists or user_mapping_json_exists):
            self.logger.warning("=" * 60)
            self.logger.warning("AUTO-MIGRATION: Converting JSON config to YAML format")
            self.logger.warning("=" * 60)
            
            try:
                # Load existing JSON config
                config_data = {}
                if config_json_exists:
                    self.logger.info(f"Loading config from {self.CONFIG_FILE_JSON}")
                    with open(self.CONFIG_FILE_JSON, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                    
                    # Create backup
                    backup_path = f"{self.CONFIG_FILE_JSON}.bak"
                    shutil.copy2(self.CONFIG_FILE_JSON, backup_path)
                    self.logger.info(f"Backup created: {backup_path}")
                
                # Load user_mapping if it exists
                user_mapping_data = {}
                if user_mapping_json_exists:
                    self.logger.info(f"Loading user_mapping from {self.USER_MAPPING_FILE_JSON}")
                    with open(self.USER_MAPPING_FILE_JSON, "r", encoding="utf-8") as f:
                        user_mapping_data = json.load(f)
                    
                    # Create backup
                    backup_path = f"{self.USER_MAPPING_FILE_JSON}.bak"
                    shutil.copy2(self.USER_MAPPING_FILE_JSON, backup_path)
                    self.logger.info(f"Backup created: {backup_path}")
                
                # Merge user_mapping into config_data
                if user_mapping_data:
                    config_data["user_mapping"] = user_mapping_data
                
                # Write to YAML
                self.logger.info(f"Writing merged config to {self.CONFIG_FILE}")
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
                self.logger.warning("✓ Migration completed successfully!")
                self.logger.warning(f"✓ Old JSON files backed up with .bak extension")
                self.logger.warning(f"✓ New config.yaml created at {self.CONFIG_FILE}")
                self.logger.warning("=" * 60)
                
            except Exception as e:
                self.logger.error(f"Auto-migration failed: {e}")
                self.logger.error("Bot will continue with JSON fallback. Please migrate manually.")
                import traceback
                self.logger.error(traceback.format_exc())
        elif config_json_exists or user_mapping_json_exists:
            # YAML exists but JSON also exists - warn but don't migrate
            self.logger.warning("Both YAML and JSON config files exist. Using YAML. Consider removing JSON files.")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from config.yaml (or config.json for backward compatibility) with defaults if unavailable."""
        default_config = {
            "dashboard": {"name": "Plex Dashboard", "icon_url": "", "footer_icon_url": ""},
            "plex_sections": {"show_all": True, "sections": {}},
            "presence": {
                "sections": [],
                "offline_text": "🔴 Server Offline!",
                "stream_text": "{count} active Stream{s} 🟢",
            },
            "cache": {"library_update_interval": 900},
        }
        
        # Try loading YAML first (new format)
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    yaml_config = yaml.safe_load(f)
                    # Remove user_mapping from config if present (it's loaded separately)
                    config = {k: v for k, v in yaml_config.items() if k != "user_mapping"}
                    return {**default_config, **config}  # Merge with defaults
            except (yaml.YAMLError, Exception) as e:
                self.logger.error(f"Failed to load YAML config: {e}. Trying JSON fallback.")
        
        # Fallback to JSON for backward compatibility
        if os.path.exists(self.CONFIG_FILE_JSON):
            self.logger.warning("Using legacy config.json. Please migrate to config.yaml.")
            try:
                with open(self.CONFIG_FILE_JSON, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return {**default_config, **config}  # Merge with defaults
            except (FileNotFoundError, json.JSONDecodeError) as e:
                self.logger.error(f"Failed to load JSON config: {e}. Using defaults.")
                return default_config
        
        self.logger.warning("No config file found. Using defaults.")
        return default_config

    def _load_message_id(self) -> Optional[int]:
        """Load the dashboard message ID from file."""
        if not os.path.exists(self.MESSAGE_ID_FILE):
            return None
        try:
            with open(self.MESSAGE_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("message_id"))
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Failed to load message ID: {e}")
            return None

    def _save_message_id(self, message_id: int) -> None:
        """Save the dashboard message ID to file."""
        try:
            with open(self.MESSAGE_ID_FILE, "w", encoding="utf-8") as f:
                json.dump({"message_id": message_id}, f)
        except OSError as e:
            self.logger.error(f"Failed to save message ID: {e}")

    def _load_user_mapping(self) -> Dict[str, str]:
        """Load user mapping from config.yaml (or user_mapping.json for backward compatibility)."""
        # Try loading from YAML first (new format)
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    yaml_config = yaml.safe_load(f)
                    user_mapping = yaml_config.get("user_mapping", {})
                    if user_mapping:
                        return user_mapping
            except (yaml.YAMLError, Exception) as e:
                self.logger.error(f"Failed to load user mapping from YAML: {e}. Trying JSON fallback.")
        
        # Fallback to JSON for backward compatibility
        user_mapping_file_json = os.path.join(self.current_dir, "..", "data", "user_mapping.json")
        if os.path.exists(user_mapping_file_json):
            self.logger.warning("Using legacy user_mapping.json. Please migrate to config.yaml.")
            try:
                with open(user_mapping_file_json, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                self.logger.error(f"Failed to load user mapping from JSON: {e}")
                return {}
        
        return {}

    def connect_to_plex(self) -> Optional[PlexServer]:
        """Attempt to establish a connection to the Plex server."""
        try:
            plex = PlexServer(self.PLEX_URL, self.PLEX_TOKEN)
            if self.plex_start_time is None:
                self.plex_start_time = time.time()
            return plex
        except Exception as e:  # Using generic Exception as plexapi doesn't expose a single base exception
            self.logger.error(f"Failed to connect to Plex server: {e}")
            self.plex_start_time = None
            return None

    async def fetch_tautulli_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Async fetch of Tautulli session data."""
        if not self.TAUTULLI_URL or not self.TAUTULLI_API_KEY:
            return None
            
        try:
            base_url = self.TAUTULLI_URL.rstrip("/")
            url = f"{base_url}/api/v2"
            params = {
                "apikey": self.TAUTULLI_API_KEY,
                "cmd": "get_activity"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("response", {}).get("result") == "success":
                            # Find our session in the sessions list
                            sessions = data["response"]["data"]["sessions"]
                            # Tautulli session_key matches Plex session_key
                            for s in sessions:
                                if str(s.get("session_key")) == str(session_key):
                                    return s
            return None
        except Exception as e:
            self.logger.error(f"Error fetching from Tautulli: {e}")
            return None

    async def get_tautulli_thumbnail(self, tautulli_data: Dict[str, Any]) -> Optional[discord.File]:
        """Fetch thumbnail image from Tautulli's image proxy."""
        if not self.TAUTULLI_URL or not self.TAUTULLI_API_KEY:
            return None

        try:
            # Get thumb path from Tautulli data
            media_type = tautulli_data.get("media_type", "")
            
            # For episodes, prefer series poster (grandparent_thumb)
            if media_type == "episode":
                thumb = tautulli_data.get("grandparent_thumb", "")
                if not thumb:
                    thumb = tautulli_data.get("thumb", "")
            else:
                # For movies/music, use item thumb
                thumb = tautulli_data.get("thumb", "")
                if not thumb:
                    thumb = tautulli_data.get("art", "")
            
            if not thumb:
                return None
            
            # Build Tautulli image proxy URL
            base_url = self.TAUTULLI_URL.rstrip("/")
            url = f"{base_url}/pms_image_proxy"
            params = {
                "img": thumb,
                "width": 300,
                "height": 450,
                "fallback": "poster",
                "apikey": self.TAUTULLI_API_KEY
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.read()
                        if data:
                            return discord.File(io.BytesIO(data), filename="poster.jpg")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching thumbnail from Tautulli: {e}")
            return None

    def get_server_info(self) -> Dict[str, Any]:
        """Retrieve current Plex server status and statistics."""
        self.plex = self.connect_to_plex()
        if not self.plex:
            return self.get_offline_info()
        try:
            self.offline_since = None
            return {
                "status": "🟢 Online",
                "uptime": self.calculate_uptime(),
                "library_stats": self.get_library_stats(),
                "active_users": self.get_active_streams(),
                "current_streams": self.plex.sessions(),
            }
        except Exception as e:
            self.logger.error(f"Error retrieving server info: {e}")
            return self.get_offline_info()

    def calculate_uptime(self) -> str:
        """Calculate Plex server uptime as a formatted string."""
        if not self.plex_start_time:
            return "Offline"
        total_minutes = int((time.time() - self.plex_start_time) / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return "99+ Hours" if hours > 99 else f"{hours:02d}:{minutes:02d}"

    def get_library_stats(self) -> Dict[str, Dict[str, Any]]:
        """Fetch and cache Plex library statistics, preserving config order."""
        current_time = datetime.now()
        if (
            self.last_library_update
            and (current_time - self.last_library_update).total_seconds() <= self.library_update_interval
        ):
            return self.library_cache

        # Ensure Plex connection is established
        if not self.plex:
            self.plex = self.connect_to_plex()
        if not self.plex:
            return self.library_cache

        try:
            sections = {section.title: section for section in self.plex.library.sections()}
            stats: Dict[str, Dict[str, Any]] = {}
            plex_config = self.config["plex_sections"]
            configured_sections = plex_config["sections"]

            if not plex_config["show_all"]:
                for title in configured_sections:
                    if title in sections:
                        config = configured_sections[title]
                        section = sections[title]
                        stats[title] = self._build_section_stats(section, config)
            else:
                for title in configured_sections:
                    if title in sections:
                        config = configured_sections[title]
                        section = sections[title]
                        stats[title] = self._build_section_stats(section, config)
                for title, section in sections.items():
                    if title not in configured_sections:
                        stats[title] = {
                            "count": len(section.all()),
                            "episodes": 0,
                            "display_name": title,
                            "emoji": "🎬",
                            "show_episodes": False,
                        }

            self.library_cache = stats
            self.last_library_update = current_time
            self.logger.info(f"Library stats updated and cached (interval: {self.library_update_interval}s)")
            return stats
        except Exception as e:
            self.logger.error(f"Error updating library stats: {e}")
            return self.library_cache

    def _build_section_stats(self, section, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build statistics dictionary for a Plex section."""
        return {
            "count": len(section.all()),
            "episodes": sum(show.leafCount for show in section.all()) if config["show_episodes"] and hasattr(section, "all") else 0,
            "display_name": config["display_name"],
            "emoji": config["emoji"],
            "show_episodes": config["show_episodes"],
        }

    def get_active_streams(self) -> List[str]:
        """Retrieve formatted information about active Plex streams."""
        if not self.plex:
            return []
        sessions = self.plex.sessions()
        if self.stream_debug:
            self.logger.debug(f"Found {len(sessions)} active sessions")
        return [
            stream_info
            for idx, session in enumerate(sessions, start=1)
            if (stream_info := self.format_stream_info(session, idx))
            and (self.stream_debug and self.logger.debug(f"Formatted Stream Info:\n{stream_info}\n{'='*50}") or True)
        ]

    def format_stream_info(self, session, idx: int) -> str:
        """Format Plex stream details into a displayable string."""
        try:
            user = session.usernames[0] if session.usernames else "Unbekannt"
            displayed_user = self.user_mapping.get(user, user)
            section_title = getattr(session, "librarySectionTitle", "Unknown")
            stats = self.get_library_stats()
            content_emoji = stats.get(section_title, {}).get("emoji") or (
                "🎵" if getattr(session, "type", "") == "track" else
                "🎥" if getattr(session, "type", "") in ["movie", None] else "📺"
            )

            title = self._get_formatted_title(session)
            progress_percent = (
                (session.viewOffset / session.duration * 100)
                if hasattr(session, "viewOffset") and hasattr(session, "duration") and session.duration
                else 0
            )
            is_paused = getattr(session.players[0], "state", "") == "paused" if hasattr(session, "players") and session.players else False
            progress_display = "⏸️" if is_paused else f"[{'▓' * int(progress_percent / 10)}{'░' * (10 - int(progress_percent / 10))}] {progress_percent:.1f}%"

            current_time = self._format_time(str(timedelta(milliseconds=session.viewOffset or 0)).split(".")[0], session.duration or 0)
            total_time = self._format_time(str(timedelta(milliseconds=session.duration or 0)).split(".")[0], session.duration or 0)

            media = session.media[0] if hasattr(session, "media") and session.media else None
            
            # Handle quality display based on content type
            if getattr(session, "type", "") == "track":
                # For music, show audio quality
                audio_stream = next((stream for part in media.parts for stream in part.streams if stream.streamType == 2), None) if media else None
                quality = f"{getattr(audio_stream, 'bitDepth', '')}bit" if audio_stream and getattr(audio_stream, 'bitDepth', None) else ""
                if audio_stream and getattr(audio_stream, 'samplingRate', None):
                    quality += f" {int(audio_stream.samplingRate/1000)}kHz" if quality else f"{int(audio_stream.samplingRate/1000)}kHz"
                quality = quality if quality else "Audio"
            else:
                # For video content, show video quality
                quality = f"{getattr(media, 'videoResolution', '1080')}p" if media else "1080p"
                quality = quality[:-1] if quality.endswith("pp") else "4K" if quality in ["4kp", "4Kp"] else quality

            transcode_session = getattr(session, "transcodeSession", None)
            transcode_emoji = "🔄" if transcode_session else "⏯️"
            bitrate = (
                f"{transcode_session.bitrate / 1000:.1f} Mbps" if transcode_session and getattr(transcode_session, "bitrate", None)
                else f"{media.bitrate / 1000:.1f} Mbps" if media and getattr(media, "bitrate", None)
                else ""
            )

            product_name = (
                session.players[0].product.replace("Plex for ", "").replace("Infuse-Library", "Infuse")
                if hasattr(session, "players") and session.players
                else "Unknown"
            )

            return (
                f"**```{content_emoji} {title} | {displayed_user}\n"
                f"└─ {progress_display} | {current_time}/{total_time}\n"
                f" └─ {transcode_emoji} {quality} {bitrate} | {product_name}```**"
            )
        except Exception as e:
            self.logger.error(f"Error formatting stream info: {e}")
            return f"```❓ Stream could not be loaded (# {idx})```"

    def _format_time(self, time_str: str, duration: int) -> str:
        """Format time string based on content duration."""
        parts = time_str.split(":")
        less_than_hour = (duration // 1000) < 3600
        return f"{int(parts[-2]):02d}:{int(parts[-1]):02d}" if less_than_hour else f"{int(parts[0]):01d}:{int(parts[1]):02d}:{int(parts[2]):02d}"

    def _get_formatted_title(self, session) -> str:
        """Format content title based on its type."""
        if hasattr(session, "type") and session.type == "track":
            # Handle music tracks
            artist = getattr(session, "grandparentTitle", "Unknown Artist")
            track = getattr(session, "title", "Unknown Track")
            return f"{artist} - {track}"
        elif hasattr(session, "grandparentTitle"):
            # Handle TV shows - keep full title
            series_title = session.grandparentTitle.strip()
            episode_info = (
                f"S{session.parentIndex:02d}E{session.index:02d}"
                if hasattr(session, "parentIndex") and hasattr(session, "index")
                else ""
            )
            return f"{series_title} - {episode_info}"
        # Handle movies - keep full title with year
        year = f" ({session.year})" if hasattr(session, "year") and session.year else ""
        return f"{session.title}{year}"

    async def get_stream_thumbnail_file(self, session) -> Optional[discord.File]:
        """Download thumbnail and return as Discord File."""
        try:
            if not self.plex:
                return None
            
            # Determine best thumbnail path
            content_type = getattr(session, "type", "unknown")
            thumb_path = None
            
            if content_type == "episode":
                # For TV shows, prefer show poster over episode thumbnail
                thumb_path = getattr(session, "grandparentThumb", None) or getattr(session, "thumb", None)
            else:
                # For movies and music
                thumb_path = getattr(session, "thumb", None)
            
            # Fallback to art
            if not thumb_path:
                thumb_path = getattr(session, "art", None)
                
            if not thumb_path:
                return None

            # Get full URL with token
            url = self.plex.url(thumb_path, includeToken=True)
            self.logger.debug(f"Downloading thumbnail from: {url[:100]}...")

            # Download image using aiohttp
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(url) as response:
                    if response.status == 200:
                        data = await response.read()
                        return discord.File(io.BytesIO(data), filename="poster.jpg")
                    else:
                        self.logger.warning(f"Failed to download thumbnail: {response.status}")
                        return None
                        
        except Exception as e:
            self.logger.error(f"Error downloading thumbnail: {e}", exc_info=True)
            return None

    def get_transcoding_details(self, session) -> Dict[str, Any]:
        """Extract detailed transcoding information from a Plex session."""
        try:
            transcode_session = getattr(session, "transcodeSession", None)
            
            # --- Subtitle Logic (always check, even if not transcoding video/audio) ---
            subtitle_decision = "none"
            subtitle_codec = "Unknown"
            subtitle_language = "Unknown"
            subtitle_forced = False
            
            media = session.media[0] if hasattr(session, "media") and session.media else None
            
            if media and hasattr(media, "parts") and media.parts:
                for part in media.parts:
                    if hasattr(part, "streams"):
                        for stream in part.streams:
                            # Stream Type 3 is Subtitle
                            if getattr(stream, "streamType", None) == 3 and getattr(stream, "selected", False):
                                subtitle_codec = getattr(stream, "codec", "Unknown").upper()
                                subtitle_language = getattr(stream, "languageCode", getattr(stream, "language", "Unknown"))
                                subtitle_forced = getattr(stream, "forced", False)
                                
                                # Check decision
                                stream_decision = getattr(stream, "decision", "")
                                if not stream_decision and transcode_session:
                                    # Fallback to transcode session if stream has no decision
                                    # Note: Plex API is sometimes inconsistent here
                                    pass
                                
                                subtitle_decision = stream_decision if stream_decision else "burn" if transcode_session else "direct"
                                break

            if not transcode_session:
                # Even if not full transcoding, we might have subtitle info
                return {
                    "transcoding": False, 
                    "subtitle_decision": subtitle_decision,
                    "subtitle_codec": subtitle_codec,
                    "subtitle_language": subtitle_language,
                    "subtitle_forced": subtitle_forced
                }
            
            # --- Transcoding Logic ---
            
            # Get original codecs from transcode session (these are the source codecs)
            original_video_codec = getattr(transcode_session, "sourceVideoCodec", "Unknown").upper()
            original_audio_codec = getattr(transcode_session, "sourceAudioCodec", "Unknown").upper()
            
            # Get target codecs
            target_video_codec = getattr(transcode_session, "videoCodec", "Unknown").upper()
            target_audio_codec = getattr(transcode_session, "audioCodec", "Unknown").upper()
            
            # Get container info
            # BEST WAY: Fetch the original item from Plex library to get true original container
            # session.media often reflects the current stream (e.g. mp4 for direct stream of mkv)
            original_container = "Unknown"
            try:
                if hasattr(session, 'ratingKey'):
                    original_item = self.plex.fetchItem(session.ratingKey)
                    if original_item and original_item.media:
                        original_container = getattr(original_item.media[0], "container", "Unknown").upper()
                        # Also update codecs if they were unknown
                        if original_video_codec == "UNKNOWN":
                            original_video_codec = getattr(original_item.media[0], "videoCodec", "Unknown").upper()
                        if original_audio_codec == "UNKNOWN":
                            original_audio_codec = getattr(original_item.media[0], "audioCodec", "Unknown").upper()
            except Exception as e:
                self.logger.debug(f"Failed to fetch original item: {e}")
                # Fallback to existing logic if fetch fails
                original_container = getattr(media, "container", "Unknown").upper() if media else "Unknown"
                if original_container == "UNKNOWN" and media and hasattr(media, "parts") and media.parts:
                    original_container = getattr(media.parts[0], "container", "Unknown").upper()

            # Target container is in the TranscodeSession object (destination)
            target_container = getattr(transcode_session, "container", "Unknown").upper()
            
            # Get decisions
            video_decision = getattr(transcode_session, "videoDecision", "Unknown")
            audio_decision = getattr(transcode_session, "audioDecision", "Unknown")
            container_decision = getattr(transcode_session, "containerDecision", "Unknown")
            
            # Fix container decision if it's unknown but containers are different
            if container_decision == "Unknown":
                if original_container != target_container and original_container != "UNKNOWN" and target_container != "UNKNOWN":
                    container_decision = "transcode"
                elif original_container == target_container:
                    container_decision = "copy"
            
            # DEBUG: Log raw attributes to find the correct container info
            self.logger.debug(f"DEBUG TRANSCODE: video_decision={video_decision}, container_decision={container_decision}")
            self.logger.debug(f"DEBUG TRANSCODE: original_container={original_container}, target_container={target_container}")
            
            return {
                "transcoding": True,
                "video_decision": video_decision,
                "audio_decision": audio_decision,
                "container_decision": container_decision,
                "transcode_reasons": getattr(transcode_session, "transcodeReasons", "Unknown"),
                "original_video_codec": original_video_codec,
                "target_video_codec": target_video_codec,
                "original_audio_codec": original_audio_codec,
                "target_audio_codec": target_audio_codec,
                "original_container": original_container,
                "target_container": target_container,
                "transcode_speed": getattr(transcode_session, "speed", None),
                "transcode_progress": getattr(transcode_session, "progress", None),
                # Subtitle info
                "subtitle_decision": subtitle_decision,
                "subtitle_codec": subtitle_codec,
                "subtitle_language": subtitle_language,
                "subtitle_forced": subtitle_forced
            }
        except Exception as e:
            self.logger.error(f"Error extracting transcoding details: {e}", exc_info=True)
            return {"transcoding": False, "error": str(e)}

    def get_offline_info(self) -> Dict[str, Any]:
        """Generate server info when Plex is offline, respecting config order."""
        current_time = discord.utils.utcnow()
        if not self.offline_since:
            self.offline_since = current_time
        stats: Dict[str, Dict[str, Any]] = {}
        plex_config = self.config["plex_sections"]
        configured_sections = plex_config["sections"]

        for title in configured_sections:
            config = configured_sections[title]
            stats[title] = {
                "count": 0,
                "episodes": 0 if config["show_episodes"] else 0,
                "display_name": config["display_name"],
                "emoji": config["emoji"],
                "show_episodes": config["show_episodes"],
            }
        return {
            "status": "🔴 Offline",
            "offline_since": self.offline_since,
            "library_stats": stats,
            "active_users": [],
            "current_streams": [],
        }

    @tasks.loop(minutes=5)
    async def update_status(self) -> None:
        """Update bot presence with Plex status and stream count."""
        try:
            info = self.get_server_info()
            active_streams = len(info["active_users"])
            presence_config = self.config["presence"]
            stats = info["library_stats"]

            if info["status"] != "🟢 Online":
                activity_text = presence_config["offline_text"]
                status = discord.Status.dnd
            elif active_streams > 0:
                activity_text = presence_config["stream_text"].format(
                    count=active_streams, s="s" if active_streams != 1 else ""
                )
                status = discord.Status.online
            else:
                presence_parts = [
                    f"{'{:,.0f}'.format(stats[section['section_title']]['count']).replace(',', '.')} {section['display_name']} {section['emoji']}"
                    for section in presence_config["sections"]
                    if section["section_title"] in stats
                ]
                activity_text = " | ".join(presence_parts) if presence_parts else "No streams or sections configured"
                status = discord.Status.online

            await self.bot.change_presence(activity=discord.CustomActivity(name=activity_text), status=status)
            self.logger.info(f"Status updated: {activity_text} ({status})")
        except Exception as e:
            self.logger.error(f"Error updating status: {e}")

    @tasks.loop(minutes=1)
    async def update_dashboard(self) -> None:
        """Update Discord dashboard with Plex, SABnzbd, and Uptime data."""
        channel = self.bot.get_channel(self.CHANNEL_ID)
        if not channel:
            return

        try:
            info = self.get_server_info()
            sabnzbd_cog = self.bot.get_cog("SABnzbd")
            if sabnzbd_cog:
                info["downloads"] = await sabnzbd_cog.get_sabnzbd_info()

            uptime_cog = self.bot.get_cog("Uptime")
            if uptime_cog:
                uptime_data = uptime_cog.get_uptime_data()
                info["uptime_24h"] = (
                    f"{uptime_data[0]:.1f}% ({uptime_cog.format_online_time(uptime_data[1])})"
                    if uptime_data[0] is not None else "No data"
                )
                info["uptime_7d"] = (
                    f"{uptime_data[2]:.1f}% ({uptime_cog.format_online_time(uptime_data[3])})"
                    if uptime_data[2] is not None else "No data"
                )
                info["uptime_30d"] = (
                    f"{uptime_data[4]:.1f}% ({uptime_cog.format_online_time(uptime_data[5])})"
                    if uptime_data[4] is not None else "No data"
                )
                info["last_offline"] = uptime_data[6] if uptime_data[6] else "Not available"

            embed = await self.create_dashboard_embed(info)
            await self._update_dashboard_message(channel, embed, info)
        except Exception as e:
            self.logger.error(f"Error updating dashboard: {e}")

    async def create_dashboard_embed(self, info: Dict[str, Any]) -> discord.Embed:
        """Create a dashboard embed reflecting server status."""
        dashboard_config = self.config["dashboard"]
        embed = discord.Embed(
            title="Server is currently Offline! :warning:" if info["status"] != "🟢 Online" else "Server is currently Online! :white_check_mark:",
            color=discord.Color.red() if info["status"] != "🟢 Online" else discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

        if info["status"] != "🟢 Online":
            offline_since_str, time_diff_str = "Unknown", "Unknown duration"
            if info["offline_since"] and isinstance(info["offline_since"], datetime):
                offline_since_dt = info["offline_since"]
                offline_since_str = (offline_since_dt + timedelta(hours=1)).strftime("%d.%m.%Y %H:%M")
                time_diff = discord.utils.utcnow() - offline_since_dt
                days, hours, minutes = time_diff.days, time_diff.seconds // 3600, (time_diff.seconds % 3600) // 60
                time_diff_str = (
                    f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''} ago"
                    if days > 0 else
                    f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''} ago"
                    if hours > 0 else
                    f"{minutes} minute{'s' if minutes != 1 else ''} ago"
                    if minutes > 0 else "Just now"
                )
            embed.add_field(name="Offline since:", value=f"```{offline_since_str}\n{time_diff_str}```", inline=False)
            
            uptime_cog = self.bot.get_cog("Uptime")
            if uptime_cog and "uptime_24h" in info and info["uptime_24h"] != "No data":
                embed.add_field(name="Uptime (24h)", value=f"```{info['uptime_24h']}```", inline=True)
                embed.add_field(name="Uptime (7 days)", value=f"```{info['uptime_7d']}```", inline=True)
                embed.add_field(name="Uptime (30 days)", value=f"```{info['uptime_30d']}```", inline=True)
        else:
            await self._add_embed_fields(embed, info)

        embed.set_author(name=dashboard_config["name"], icon_url=dashboard_config["icon_url"])
        embed.set_thumbnail(url=dashboard_config["icon_url"])
        embed.set_footer(text="Last updated", icon_url=dashboard_config["footer_icon_url"])
        return embed

    async def _add_embed_fields(self, embed: discord.Embed, info: Dict[str, Any]) -> None:
        """Add fields to the dashboard embed when server is online."""
        embed.add_field(name="Server Uptime 🖥️", value=f"```{info['uptime']}```", inline=True)
        embed.add_field(name="", value="", inline=True)  # Spacer
        embed.add_field(name="", value="", inline=True)  # Spacer

        stats = info["library_stats"]
        plex_config = self.config["plex_sections"]
        configured_sections = plex_config["sections"]

        sections_to_display = configured_sections if not plex_config["show_all"] else {**configured_sections, **{k: None for k in stats if k not in configured_sections}}
        for title in sections_to_display:
            if title in stats:
                section_data = stats[title]
                display_name = f"{section_data['display_name']} {section_data['emoji']}"
                value = f"```{'{:,.0f}'.format(section_data['count']).replace(',', '.')}```"
                embed.add_field(name=display_name, value=value, inline=True)
                if section_data["show_episodes"]:
                    embed.add_field(
                        name=f"{section_data['display_name']} Episodes 📺",
                        value=f"```{'{:,.0f}'.format(section_data['episodes']).replace(',', '.')}```",
                        inline=True,
                    )

        if info["active_users"]:
            stream_count = len(info["active_users"])

            streams_limited = info["active_users"][:8]
            streams_text = " ".join(streams_limited)
            embed.add_field(
                name=f"{stream_count} current Stream{'s' if stream_count != 1 else ''}:" + (f" (showing 8 of {stream_count})" if stream_count > 8 else ""),
                value=streams_text,
                inline=False,
            )
        else:
            embed.add_field(name="Current Streams:", value="💤 *No active streams currently*", inline=False)

        # SABnzbd Downloads Section - only show if SABnzbd is configured
        sabnzbd_cog = self.bot.get_cog("SABnzbd")
        download_info = info.get("downloads", {})
        
        # Only show SABnzbd section if it's configured
        if sabnzbd_cog and download_info.get("configured", False):
            if download_info.get("downloads"):
                # Active downloads
                downloads = download_info["downloads"][:4]
                download_count = len(download_info["downloads"])
                downloads_text = " ".join(
                    sabnzbd_cog.format_download_info(download, i)
                    for i, download in enumerate(downloads)
                )
                embed.add_field(
                    name=f"{download_count} current Download{'s' if download_count != 1 else ''}:",
                    value=downloads_text,
                    inline=False,
                )
                embed.add_field(name="Downloads 📥", value=f"```{self._calculate_total_size(downloads)}```", inline=True)
                embed.add_field(name="Free Space 💾", value=f"```{download_info['diskspace1']}```", inline=True)
                embed.add_field(name="Total Space 🗄️", value=f"```{download_info['diskspacetotal1']}```", inline=True)
            elif download_info.get("show_when_empty", False):
                # No active downloads - only show if show_when_empty is True
                embed.add_field(name="Current Downloads:", value="💤 *No active downloads currently*", inline=False)

    def _calculate_total_size(self, downloads: List[Dict[str, Any]]) -> str:
        """Calculate total download size in human-readable format."""
        total_size_mb = 0
        for download in downloads:
            if download["size"] == "Unknown":
                continue
            value, unit = download["size"].split()
            value = float(value)
            total_size_mb += value / 1024 if unit == "KB" else value if unit == "MB" else value * 1024 if unit == "GB" else 0
        return f"{total_size_mb / 1024:.2f} GB" if total_size_mb >= 1024 else f"{total_size_mb:.2f} MB"

    async def _update_dashboard_message(self, channel: discord.TextChannel, embed: discord.Embed, info: Dict[str, Any]) -> None:
        """Update or create the dashboard message in the specified channel."""
        # Create view with buttons if there are active streams
        view = None
        if info.get("current_streams") and len(info["current_streams"]) > 0:
            try:
                await self.stream_view.create_buttons(info["current_streams"])
                view = self.stream_view
                self.logger.debug(f"Created {len(self.stream_view.children)} stream detail buttons")
            except Exception as e:
                self.logger.error(f"Error creating stream buttons: {e}")
        
        if self.dashboard_message_id:
            try:
                message = await channel.fetch_message(self.dashboard_message_id)
                await message.edit(embed=embed, view=view)
                self.logger.debug("Dashboard message updated successfully")
            except discord.NotFound:
                self.logger.warning("Dashboard message not found, creating new one")
                self.dashboard_message_id = None

        if not self.dashboard_message_id:
            message = await channel.send(embed=embed, view=view)
            self.dashboard_message_id = message.id
            self._save_message_id(self.dashboard_message_id)
            self.logger.info(f"New dashboard message created with ID: {self.dashboard_message_id}")

async def setup(bot: commands.Bot) -> None:
    """Set up the PlexCore cog for the bot."""
    await bot.add_cog(PlexCore(bot))