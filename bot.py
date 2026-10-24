import discord
import ctypes.util
from discord import app_commands
from discord.ext import commands, tasks
from datetime import timedelta
import os
import asyncio
import random
import time
import yt_dlp
import aiohttp
import re

# Specific channel allowed for Anime Game
ANIME_GAME_CHANNEL_ID = 1534536134040748033

# Special User ID for strict music lock rule and bypass
LOCKED_USER_ID = 1537275886758264964

# Global toggle to enable/disable the special user restriction lock
music_lock_enabled = True

# Global toggle for auto-rejoin feature
auto_rejoin_enabled = True

# Cooldown flag dictionary to prevent infinite loops during auto-rejoin per guild
rejoining_guilds = set()

# Track active anime games per channel
active_anime_games = set()

# Player points storage for hints and leaderboard (user_id -> integer points)
user_points = {}

# Role ID allowed to use the DM command and clear history
ALLOWED_ROLE_ID = 1483526094937391195

# In-memory storage for user warnings (guild_id -> {user_id: [reason1, reason2, ...]})
user_warnings = {}

# Store active audio filter per guild ('normal', '8d', '4d', 'bass', 'nightcore', 'vaporwave')
guild_filters = {}
# Store active voice quality preset per guild ('normal', 'studio', 'podcast', 'treble', 'crystal')
guild_voice_qualities = {}

# Store the last active voice channel per guild for auto-rejoining
active_voice_channels = {}

# Load Opus audio library safely on Windows
if not discord.opus.is_loaded():
    libname = ctypes.util.find_library('opus') or 'libopus-0.dll'
    try:
        discord.opus.load_opus(libname)
    except Exception as e:
        print(f"Could not load opus: {e}")

# Initialize Bot with necessary Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# State tracking per guild
music_queues = {}       # Queued songs
music_history = {}      # History for Previous button & /history commands
guild_volumes = {}     # Volume level (0.5 = 100%)
current_playing = {}   # Currently playing song dict with start_time & message reference
artist_song_cache = {} # Cache for instant-skip pre-fetching

# Comprehensive Arabic & English name map for popular anime characters
ARABIC_NAME_MAP = {
    "naruto uzumaki": ["ناروتو", "ناروتو أوزوماكي", "ناروتو اوزوماكي"],
    "monkey d. luffy": ["لوفي", "مونكي دي لوفي", "لوفي د مونكي"],
    "son goku": ["جوكو", "سون غوكو", "غوكو"],
    "goku": ["جوكو", "غوكو"],
    "satoru gojo": ["غوجو", "ساتورو غوجو", "جوجو"],
    "eren yeager": ["ايرين", "إيرين", "إيرين ييغر", "ايرين ييغر"],
    "izuku midoriya": ["ديكو", "ميدوريا", "إيزوكو ميدوريا"],
    "tanjiro kamado": ["تانجيرو", "تانجيرو كامادو"],
    "levi ackerman": ["ليفاي", "ليفاي أكرمان"],
    "light yagami": ["لايت", "لايت ياغامي"],
    "itachi uchiha": ["إيتاشي", "ايتاشي", "إيتاشي أوتشيها"],
    "kakashi hatake": ["ككاشي", "كاكاشي", "كاكاشي هاتاكي"],
    "killua zoldyck": ["كيلوا", "كيلوا زولديك"],
    "gon freecss": ["غون", "كون", "غون فريكس"],
    "saitama": ["سايتاما"],
    "roronoa zoro": ["زورو", "رورونوا زورو"],
    "vegeta": ["فيجيتا", "بيجيتا"],
    "sukuna": ["سوكونا", "ريومن سوكونا"],
    "nezuko kamado": ["نيزوكو", "نيزوكو كامادو"],
    "natsu dragneel": ["ناتسو", "ناتسو دراغنيل"],
    "kaneki ken": ["كانيكي", "كانيكي كين"]
}

def clean_text(text: str) -> str:
    """Normalizes Arabic & English string inputs for reliable string comparisons."""
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r'[\u064B-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'[ى]', 'ي', text)
    text = re.sub(r'[ؤئ]', 'ء', text)
    return text

async def fetch_random_anime_character():
    """Fetches a random popular anime character from AniList API with multilingual support."""
    url = 'https://graphql.anilist.co'
    random_page = random.randint(1, 150)
    
    query = '''
    query ($page: Int) {
      Page(page: $page, perPage: 1) {
        characters(sort: FAVOURITES_DESC) {
          name {
            full
            native
            alternative
          }
          image {
            large
          }
          media(sort: POPULARITY_DESC, perPage: 1) {
            nodes {
              title {
                english
                romaji
              }
            }
          }
        }
      }
    }
    '''
    
    variables = {'page': random_page}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={'query': query, 'variables': variables}) as response:
            if response.status == 200:
                data = await response.json()
                char_data = data['data']['Page']['characters'][0]
                
                full_name = char_data['name']['full']
                image_url = char_data['image']['large']
                
                aliases = [clean_text(full_name)]
                name_parts = [clean_text(p) for p in full_name.split()]
                aliases.extend(name_parts)
                
                if char_data['name']['alternative']:
                    for alt in char_data['name']['alternative']:
                        if alt:
                            aliases.append(clean_text(alt))
                lower_full = full_name.lower()
                arabic_names = []
                if lower_full in ARABIC_NAME_MAP:
                    for ar in ARABIC_NAME_MAP[lower_full]:
                        clean_ar = clean_text(ar)
                        aliases.append(clean_ar)
                        arabic_names.append(ar)
                else:
                    for part in lower_full.split():
                        if part in ARABIC_NAME_MAP:
                            for ar in ARABIC_NAME_MAP[part]:
                                clean_ar = clean_text(ar)
                                aliases.append(clean_ar)
                                arabic_names.append(ar)
                if char_data['name']['native']:
                    aliases.append(clean_text(char_data['name']['native']))
                anime_title = "غير معروف"
                if char_data['media']['nodes']:
                    media = char_data['media']['nodes'][0]['title']
                    anime_title = media['english'] or media['romaji'] or "غير معروف"
                primary_arabic = arabic_names[0] if arabic_names else full_name
                return {
                    "name": full_name,
                    "arabic_name": primary_arabic,
                    "aliases": list(set(aliases)),
                    "image": image_url,
                    "anime": anime_title
                }
            return None

# Leaderboard / Top Points Function (Arabic Only)
async def show_points_leaderboard(channel, send_func):
    if not user_points:
        await send_func("📊 **لا توجد نقاط مسجلة بعد! العب لعبة الأنمي لجمع النقاط.**")
        return
    sorted_users = sorted(user_points.items(), key=lambda item: item[1], reverse=True)[:10]
    
    description = ""
    for idx, (uid, pts) in enumerate(sorted_users, start=1):
        medal = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"`#{idx}`"))
        description += f"{medal} <@{uid}> — **{pts}** نقطة\n"
    embed = discord.Embed(
        title="🏆 لوحة شرف نقاط الأنمي",
        description=description,
        color=discord.Color.gold()
    )
    embed.set_footer(text="استمر في اللعب للصعود في الترتيب!")
    await send_func(embed=embed)

# Game UI Buttons View (Hint & Stop Buttons - Arabic Only)
class AnimeGameControls(discord.ui.View):
    def __init__(self, character):
        super().__init__(timeout=30)
        self.character = character
        self.stopped = False
        self.stopped_by = None
    @discord.ui.button(label="💡 تلميح (5 نقاط)", style=discord.ButtonStyle.primary, custom_id="anime_hint_btn")
    async def hint_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        pts = user_points.get(uid, 0)
        if pts < 5:
            return await interaction.response.send_message(
                f"🔒 **نقاط غير كافية!**\nتحتاج إلى **5 نقاط** لشراء تلميح، ولكن لديك **{pts} نقطة** فقط.",
                ephemeral=True
            )
        
        user_points[uid] -= 5
        remaining = user_points[uid]
        first_letter = self.character['name'][0].upper()
        
        hint_text = (
            f"💡 **تلميح خاص:**\n"
            f"• **اسم الأنمي:** *{self.character['anime']}*\n"
            f"• **الحرف الأول:** `{first_letter}`\n"
            f"• **رصيدك المتبقي:** `{remaining}` نقطة"
        )
        await interaction.response.send_message(hint_text, ephemeral=True)
    @discord.ui.button(label="🛑 إيقاف اللعبة", style=discord.ButtonStyle.danger, custom_id="anime_stop_btn")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stopped = True
        self.stopped_by = interaction.user
        self.stop()
        await interaction.response.defer()

# Helper logic to handle game instance execution (Arabic Only)
async def start_anime_game(channel, send_func):
    if channel.id != ANIME_GAME_CHANNEL_ID:
        await send_func(f"❌ **قناة خاطئة!** يمكن لعب هذه اللعبة فقط في <#{ANIME_GAME_CHANNEL_ID}>.")
        return
    if channel.id in active_anime_games:
        embed_running = discord.Embed(
            title="⚔️ هناك لعبة جارية بالفعل!",
            description=(
                "⚠️ **تمهل! هناك تحدي أنمي قائم حالياً في هذه القناة.**\n\n"
                "يرجى تخمين الشخصية الحالية أو انتظار انتهاء الوقت لتتمكن من بدء جولة جديدة!"
            ),
            color=discord.Color.gold()
        )
        await send_func(embed=embed_running)
        return
    active_anime_games.add(channel.id)
    try:
        character = await fetch_random_anime_character()
        
        if not character:
            await send_func("❌ تعذر تحميل شخصية من قاعدة البيانات. يجيب المحاولة مرة أخرى!")
            return
        view = AnimeGameControls(character)
        embed = discord.Embed(
            title="🖼️ خمن شخصية الأنمي!",
            description=(
                "اكتب اسم الشخصية بـ **العربية** أو **الإنجليزية**! لديك **30 ثانية**."
            ),
            color=0xFF69B4
        )
        embed.set_image(url=character["image"])
        embed.set_footer(text="تلميح: الاسم الأول أو الأخير يعمل! اربح نقطة مع كل إجابة صحيحة!")
        game_msg = await send_func(embed=embed, view=view)
        def check(m: discord.Message):
            clean_input = clean_text(m.content)
            return (
                m.channel == channel
                and not m.author.bot
                and clean_input in character["aliases"]
            )
        guessed_message = None
        start_time = time.time()
        while time.time() - start_time < 30.0:
            if view.stopped:
                break
            try:
                time_left = 30.0 - (time.time() - start_time)
                if time_left <= 0:
                    break
                guessed_message = await bot.wait_for('message', timeout=min(1.0, time_left), check=check)
                if guessed_message:
                    break
            except asyncio.TimeoutError:
                continue
        view.stop()
        for child in view.children:
            child.disabled = True
        
        try:
            if hasattr(game_msg, 'edit'):
                await game_msg.edit(view=view)
        except Exception:
            pass
        if guessed_message:
            uid = guessed_message.author.id
            user_points[uid] = user_points.get(uid, 0) + 1
            total_p = user_points[uid]
            win_embed = discord.Embed(
                title="🎉 إجابة صحيحة!",
                description=(
                    f"أحسنت {guessed_message.author.mention}! لقد خمنت الشخصية الصحيحة!\n"
                    f"🎉 **تمت إضافة نقطة واحدة!** مجموع نقاطك: `{total_p}`\n\n"
                    f"• **الاسم بالعربية:** **{character['arabic_name']}**\n"
                    f"• **English Name:** **{character['name']}**\n"
                    f"• **الأنمي:** *{character['anime']}*"
                ),
                color=discord.Color.green()
            )
            await guessed_message.reply(embed=win_embed)
        elif view.stopped:
            stop_embed = discord.Embed(
                title="🛑 تم إيقاف اللعبة",
                description=(
                    f"تم إيقاف الجولة بواسطة {view.stopped_by.mention}.\n\n"
                    f"• **الاسم بالعربية:** **{character['arabic_name']}**\n"
                    f"• **English Name:** **{character['name']}**\n"
                    f"• **الأنمي:** *{character['anime']}*"
                ),
                color=discord.Color.red()
            )
            await channel.send(embed=stop_embed)
        else:
            timeout_embed = discord.Embed(
                title="⏰ انتهى الوقت!",
                description=(
                    f"لم يخمن أحد الإجابة الصحيحة في الوقت المحدد!\n\n"
                    f"• **الاسم بالعربية:** **{character['arabic_name']}**\n"
                    f"• **English Name:** **{character['name']}**\n"
                    f"• **الأنمي:** *{character['anime']}*"
                ),
                color=discord.Color.dark_gray()
            )
            await channel.send(embed=timeout_embed)
    finally:
        active_anime_games.remove(channel.id)

# yt-dlp and FFmpeg Configurations
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}
FFMPEG_EXECUTABLE = r"C:\ffmpeg\bin\ffmpeg.exe"
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration', 0)
        self.uploader = data.get('uploader', 'Unknown Artist')
    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, volume=0.5, seek_seconds=0, audio_filter="normal"):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        
        before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        if seek_seconds > 0:
            before_options += f' -ss {seek_seconds}'
        
        af_options = {
            '8d': 'apulsator=hz=0.09',
            '4d': 'apulsator=hz=0.2:amount=0.9',
            'bass': 'equalizer=f=100:width_type=h:width=200:g=15',
            'nightcore': 'asetrate=44100*1.25,aresample=44100,atempo=1.1',
            'vaporwave': 'asetrate=44100*0.8,aresample=44100,atempo=0.9',
            'normal': 'volume=1.0'
        }
        
        vq_options = {
            'normal': 'volume=1.0',
            'studio': 'acompressor=threshold=-12dB:ratio=3:attack=20:release=250,equalizer=f=1000:width_type=q:width=1:g=2',
            'podcast': 'highpass=f=200,lowpass=f=3000,acompressor',
            'treble': 'treble=g=5',
            'crystal': 'crystalizer=i=2.5'
        }
        
        selected_af = af_options.get(audio_filter, 'volume=1.0')
        # We can pass or grab guild_id from context if available, or check if guild_id is passed.
        # Since from_url doesn't take guild_id directly, let's check guild_voice_qualities using active state or default 'normal'.
        # To make it robust, we can check guild_voice_qualities or pass it.

        
        ffmpeg_options = {
            'before_options': before_options,
            'options': f'-vn -af "{selected_af}"',
        }
        return cls(discord.FFmpegPCMAudio(filename, executable=FFMPEG_EXECUTABLE, **ffmpeg_options), data=data, volume=volume)

# Helper function to generate visual progress bar
def create_progress_bar(elapsed: int, total: int, bar_length: int = 15) -> str:
    if total <= 0:
        return "🔘" + "▬" * (bar_length - 1)
    
    progress = min(1.0, max(0.0, elapsed / total))
    dot_position = int(progress * (bar_length - 1))
    
    bar = ""
    for i in range(bar_length):
        if i == dot_position:
            bar += "🔘"
        else:
            bar += "▬"
    return bar

# Helper function to generate UI Embed for the music player with global pause state synchronization
def create_player_embed(song_info, requester: discord.Member, guild_id: int, elapsed_seconds: int = 0):
    duration = song_info.get('duration', 0)
    duration_str = str(timedelta(seconds=duration)) if duration else "Live"
    elapsed_str = str(timedelta(seconds=elapsed_seconds)) if duration else "0:00"
    
    progress_bar = create_progress_bar(elapsed_seconds, duration)
    queue_count = len(music_queues.get(guild_id, []))
    current_vol = int(guild_volumes.get(guild_id, 0.5) * 200)
    current_f = guild_filters.get(guild_id, 'normal').upper()
    
    vc = bot.get_guild(guild_id).voice_client if bot.get_guild(guild_id) else None
    is_paused_state = vc and vc.is_paused()
    status_text = "⏸️ **Paused**" if is_paused_state else "▶️ **Playing**"
    requester_note = ""
    if music_lock_enabled and requester.id == LOCKED_USER_ID:
        requester_note = "\n🔒 *[Protection Lock Enabled: Only song requester can control]*"
    embed = discord.Embed(
        title=song_info['title'],
        url=song_info.get('webpage_url', song_info['url']),
        color=discord.Color.from_rgb(47, 49, 54)
    )
    embed.set_author(name="NOW PLAYING", icon_url="https://cdn-icons-png.flaticon.com/512/461/461238.png")
    embed.description = f"**{song_info.get('uploader', 'Artist')}**{requester_note}\n\n{progress_bar} `{elapsed_str} / {duration_str}`\n{status_text} • 🔊 **{current_vol}%** • 🎛️ **Filter: {current_f}**"
    
    if song_info.get('thumbnail'):
        embed.set_thumbnail(url=song_info['thumbnail'])
        
    embed.add_field(
        name="Requested by", 
        value=f"{requester.mention}", 
        inline=True
    )
    embed.add_field(
        name="Queue Status", 
        value=f"📜 {queue_count} song(s) waiting", 
        inline=True
    )
    embed.set_footer(text=f"Server: {requester.guild.name}", icon_url=requester.display_avatar.url)
    return embed

async def preload_artist_songs(artist_name: str, loop, count: int = 5):
    search_opts = dict(YTDL_OPTIONS)
    search_opts['default_search'] = f'ytsearch{max(count * 3, 15)}'
    songs = []
    try:
        def search():
            with yt_dlp.YoutubeDL(search_opts) as ytdl_search:
                return ytdl_search.extract_info(f"{artist_name} songs", download=False)
        data = await loop.run_in_executor(None, search)
        if 'entries' in data and len(data['entries']) > 0:
            entries = data['entries']
            random.shuffle(entries)
            for entry in entries:
                if len(songs) >= count:
                    break
                songs.append({
                    'title': entry.get('title'),
                    'url': entry.get('url'),
                    'thumbnail': entry.get('thumbnail'),
                    'duration': entry.get('duration', 0),
                    'uploader': entry.get('uploader', artist_name),
                    'webpage_url': entry.get('webpage_url', entry.get('url'))
                })
    except Exception as e:
        print(f"Preload error: {e}")
    return songs

async def ensure_queue_stocked(guild_id: int, artist_name: str, requester, loop, target_size: int = 5):
    if guild_id not in music_queues:
        music_queues[guild_id] = []
        
    current_count = len(music_queues[guild_id])
    if current_count < target_size:
        needed = target_size - current_count
        new_songs = await preload_artist_songs(artist_name, loop, count=needed)
        for new_song in new_songs:
            new_song['requester'] = requester
            if not any(s['title'] == new_song['title'] for s in music_queues[guild_id]):
                music_queues[guild_id].append(new_song)

async def skip_and_play_artist_random(guild_id: int, requester: discord.Member, vc):
    if not vc or not (vc.is_playing() or vc.is_paused()):
        return False
    
    vc.stop()
    
    async def background_preload():
        current_song_data = current_playing.get(guild_id, {}).get('song')
        if current_song_data and current_song_data.get('uploader'):
            artist = current_song_data['uploader']
            new_songs = await preload_artist_songs(artist, bot.loop, count=5)
            if new_songs:
                if guild_id not in music_queues:
                    music_queues[guild_id] = []
                else:
                    music_queues[guild_id].clear()
                
                for ns in new_songs:
                    ns['requester'] = requester
                    music_queues[guild_id].append(ns)
        play_next(guild_id, guild_id)
    asyncio.create_task(background_preload())
    return True

async def perform_seek(guild_id, vc, target_seconds):
    current_data = current_playing.get(guild_id)
    if not current_data or not current_data.get('song'):
        return False
    song = current_data['song']
    total_duration = song.get('duration', 0)
    if target_seconds < 0:
        target_seconds = 0
    if total_duration > 0 and target_seconds > total_duration:
        target_seconds = total_duration
    current_vol = guild_volumes.get(guild_id, 0.5)
    current_f = guild_filters.get(guild_id, 'normal')
    player = await YTDLSource.from_url(song['url'], loop=bot.loop, stream=True, volume=current_vol * 2.0, seek_seconds=target_seconds, audio_filter=current_f)
    vc.stop()
    vc.play(player, after=lambda e: play_next(guild_id, guild_id))
    current_playing[guild_id]['start_time'] = time.time()
    current_playing[guild_id]['seek_offset'] = target_seconds
    return True

# Dropdown menu for selecting audio filters directly in the player view
class FilterSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Normal", description="Reset to default sound", emoji="🎶"),
            discord.SelectOption(label="8D Audio", description="Spatial 8D audio effect", emoji="🌀"),
            discord.SelectOption(label="4D Audio", description="Immersive 4D audio effect", emoji="💫"),
            discord.SelectOption(label="Bass Boost", description="Amplifies low frequencies", emoji="🔊"),
            discord.SelectOption(label="Nightcore", description="Faster tempo and higher pitch", emoji="⚡"),
            discord.SelectOption(label="Vaporwave", description="Slower tempo and deeper pitch", emoji="🎧"),
        ]
        super().__init__(placeholder="🎛️ Select an Audio Filter...", min_values=1, max_values=1, options=options, custom_id="filter_select")
    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        current_song_data = current_playing.get(guild_id, {})
        song_info = current_song_data.get('song', {})
        requester = song_info.get('requester')
        
        if music_lock_enabled and requester and interaction.user.id != requester.id:
            return await interaction.response.send_message(
                "❌ **Only the user who requested this song can use these controls!**",
                ephemeral=True
            )
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("❌ No music is currently playing to apply filters.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        selected_filter = self.values[0].lower().replace(" audio", "").replace(" boost", "")
        guild_filters[guild_id] = selected_filter
        
        start_time = current_song_data.get('start_time', time.time())
        seek_offset = current_song_data.get('seek_offset', 0)
        current_elapsed = int(time.time() - start_time + seek_offset)
        
        await perform_seek(guild_id, vc, current_elapsed)
        await interaction.followup.send(f"🎛️ Audio filter changed to: **{self.values[0]}**!", ephemeral=True)


# Dropdown menu for selecting voice quality directly
class VoiceQualitySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Normal Quality", description="Default audio stream", emoji="🎶"),
            discord.SelectOption(label="Studio Quality", description="Compressed & balanced studio sound", emoji="🎙️"),
            discord.SelectOption(label="Podcast / Speech", description="Enhanced voice clarity", emoji="📻"),
            discord.SelectOption(label="High Treble", description="Crisp high frequencies", emoji="✨"),
            discord.SelectOption(label="Crystal Clear", description="Sharpened audio definition", emoji="💎"),
        ]
        super().__init__(placeholder="🎙️ Select Voice Quality...", min_values=1, max_values=1, options=options, custom_id="voice_quality_select")
    
    async def callback(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        
        # Check if music lock is active preventing non-authorized users when locked
        allowed, msg = check_music_lock(guild_id, interaction.user.id)
        if not allowed:
            return await interaction.response.send_message(msg, ephemeral=True)
            
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("❌ No music is currently playing to change quality.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        selected_vq = self.values[0].lower().split()[0]
        if selected_vq == 'high':
            selected_vq = 'treble'
        elif selected_vq == 'crystal':
            selected_vq = 'crystal'
            
        guild_voice_qualities[guild_id] = selected_vq
        
        current_song_data = current_playing.get(guild_id, {})
        start_time = current_song_data.get('start_time', time.time())
        seek_offset = current_song_data.get('seek_offset', 0)
        current_elapsed = int(time.time() - start_time + seek_offset)
        
        await perform_seek(guild_id, vc, current_elapsed)
        await interaction.followup.send(f"🎙️ Voice quality updated to: **{self.values[0]}**!", ephemeral=True)

class VoiceQualityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VoiceQualitySelect())

class FilterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FilterSelect())

# Interactive Buttons View for the UI Player (Restricted to requester and same voice channel check)
class MusicPlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild_id = interaction.guild_id
        
        # Voice Channel Validation Check (Bypassed ONLY for LOCKED_USER_ID)
        if interaction.user.id != LOCKED_USER_ID:
            if not interaction.user.voice or not interaction.user.voice.channel:
                await interaction.response.send_message(
                    "❌ **You must be connected to a voice channel to use the music controls!**",
                    ephemeral=True
                )
                return False
            
            vc = interaction.guild.voice_client
            if not vc or not vc.channel or interaction.user.voice.channel.id != vc.channel.id:
                await interaction.response.send_message(
                    f"❌ **You must be in the same voice channel ({vc.channel.name if vc and vc.channel else 'None'}) to use the music controls!**",
                    ephemeral=True
                )
                return False

        current_song_data = current_playing.get(guild_id, {})
        song_info = current_song_data.get('song', {})
        requester = song_info.get('requester')
        
        if music_lock_enabled and requester and interaction.user.id != LOCKED_USER_ID and interaction.user.id != requester.id:
            await interaction.response.send_message(
                "❌ **Only the user who requested this song can use these controls!**",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        if guild_id in music_history and len(music_history[guild_id]) > 0:
            prev_song = music_history[guild_id].pop()
            if guild_id not in music_queues:
                music_queues[guild_id] = []
            
            current = current_playing.get(guild_id, {}).get('song')
            if current:
                music_queues[guild_id].insert(0, current)
            music_queues[guild_id].insert(0, prev_song)
            
            if vc and (vc.is_playing() or vc.is_paused()):
                vc.stop()
            await interaction.followup.send("⏮️ Playing previous track...", ephemeral=True)
        else:
            await interaction.followup.send("❌ No previous track found in history.", ephemeral=True)

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary, custom_id="rewind_btn")
    async def rewind_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.followup.send("❌ Nothing is currently playing.", ephemeral=True)
        current_data = current_playing.get(guild_id, {})
        start_time = current_data.get('start_time', time.time())
        seek_offset = current_data.get('seek_offset', 0)
        current_elapsed = int(time.time() - start_time + seek_offset)
        
        target = max(0, current_elapsed - 10)
        await perform_seek(guild_id, vc, target)
        await interaction.followup.send(f"⏪ Rewound to **{str(timedelta(seconds=target))}**", ephemeral=True)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, custom_id="pause_btn")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        current_data = current_playing.get(guild_id, {})
        
        if vc and vc.is_playing():
            vc.pause()
            current_data['pause_start'] = time.time()
            button.emoji = "▶️"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.followup.send("⏸️ Paused playback.", ephemeral=True)
        elif vc and vc.is_paused():
            vc.resume()
            if 'pause_start' in current_data:
                pause_duration = time.time() - current_data['pause_start']
                current_data['start_time'] = current_data.get('start_time', time.time()) + pause_duration
                current_data.pop('pause_start', None)
                
            button.emoji = "⏸️"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.followup.send("▶️ Resumed playback.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Nothing is currently playing.", ephemeral=True)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="forward_btn")
    async def forward_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.followup.send("❌ Nothing is currently playing.", ephemeral=True)
        current_data = current_playing.get(guild_id, {})
        start_time = current_data.get('start_time', time.time())
        seek_offset = current_data.get('seek_offset', 0)
        current_elapsed = int(time.time() - start_time + seek_offset)
        
        target = current_elapsed + 10
        await perform_seek(guild_id, vc, target)
        await interaction.followup.send(f"⏩ Fast-forwarded to **{str(timedelta(seconds=target))}**", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip_btn")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        vc = interaction.guild.voice_client
        
        success = await skip_and_play_artist_random(guild_id, interaction.user, vc)
        if success:
            await interaction.followup.send("⏭️ Skipped track instantly!", ephemeral=True)
        else:
            await interaction.followup.send("❌ No track to skip.", ephemeral=True)

    @discord.ui.button(emoji="🎙️", label="Quality", style=discord.ButtonStyle.secondary, custom_id="quality_btn")
    async def quality_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select desired voice quality below:", view=VoiceQualityView(), ephemeral=True)
    @discord.ui.button(emoji="🎛️", label="Filters", style=discord.ButtonStyle.secondary, custom_id="filter_btn")
    async def filter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Select an audio filter below:", view=FilterView(), ephemeral=True)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="voldown_btn")
    async def voldown_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        current_vol = guild_volumes.get(guild_id, 0.5)
        new_vol = max(0.0, current_vol - 0.05)
        guild_volumes[guild_id] = new_vol
        vc = interaction.guild.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = new_vol * 2.0
        percent = int(new_vol * 200)
        await interaction.followup.send(f"🔉 Volume decreased to **{percent}%**.", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="volup_btn")
    async def volup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        current_vol = guild_volumes.get(guild_id, 0.5)
        new_vol = min(1.5, current_vol + 0.05)
        guild_volumes[guild_id] = new_vol
        vc = interaction.guild.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = new_vol * 2.0
        percent = int(new_vol * 200)
        await interaction.followup.send(f"🔊 Volume increased to **{percent}%**.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="stop_btn")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        current_playing.pop(guild_id, None)
        active_voice_channels.pop(guild_id, None)
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await interaction.followup.send("⏹️ Playback stopped and queue cleared.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Bot is not in a voice channel.", ephemeral=True)

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary, custom_id="queue_btn")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        current_song = current_playing.get(guild_id, {}).get('song')
        queue_list = music_queues.get(guild_id, [])
        if not current_song and len(queue_list) == 0:
            return await interaction.response.send_message("📄 Queue and current playback are empty.", ephemeral=True)
        embed = discord.Embed(title="🎶 Music Queue & Upcoming Songs", color=discord.Color.blue())
        
        if current_song:
            embed.add_field(name="▶️ Currently Playing", value=f"**{current_song['title']}** (`{current_song.get('uploader', 'Unknown Artist')}`)", inline=False)
        if len(queue_list) > 0:
            description = ""
            for idx, song in enumerate(queue_list[:10], start=1):
                description += f"**{idx}.** {song['title']} — *{song.get('uploader', 'Unknown Artist')}*\n"
            embed.add_field(name="📜 Coming Up Next", value=description, inline=False)
        else:
            embed.add_field(name="📜 Coming Up Next", value="*Loading upcoming tracks...*", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Background Task to update player UI progress timer live every 1 second (Fixed to pause timer when paused)
@tasks.loop(seconds=1)
async def update_player_timer():
    for guild_id, data in list(current_playing.items()):
        msg = data.get('message')
        song = data.get('song')
        start_time = data.get('start_time')
        seek_offset = data.get('seek_offset', 0)
        
        guild = bot.get_guild(guild_id)
        if not guild or not guild.voice_client or (not guild.voice_client.is_playing() and not guild.voice_client.is_paused()):
            continue
        
        vc = guild.voice_client
        if vc.is_paused():
            # Keep elapsed time frozen when paused
            continue

        if msg and song and start_time:
            elapsed = int(time.time() - start_time + seek_offset)
            total_duration = song.get('duration', 0)
            
            if total_duration > 0 and elapsed > total_duration:
                elapsed = total_duration
            new_embed = create_player_embed(song, song['requester'], guild_id, elapsed)
            try:
                is_paused = vc.is_paused()
                view = MusicPlayerView()
                for child in view.children:
                    if getattr(child, 'custom_id', None) == 'pause_btn':
                        child.emoji = "▶️" if is_paused else "⏸️"
                await msg.edit(embed=new_embed, view=view)
            except Exception:
                pass

def play_next(interaction_or_guild, guild_id=None):
    if isinstance(interaction_or_guild, discord.Interaction):
        g_id = interaction_or_guild.guild_id
        channel = interaction_or_guild.channel
    else:
        g_id = interaction_or_guild
        channel = None
    if g_id in current_playing and current_playing[g_id].get('song'):
        if g_id not in music_history:
            music_history[g_id] = []
        music_history[g_id].append(current_playing[g_id]['song'])
        if len(music_history[g_id]) > 20:
            music_history[g_id].pop(0)
            
    if g_id in music_queues and len(music_queues[g_id]) > 0:
        next_song = music_queues[g_id].pop(0)
        guild = bot.get_guild(g_id)
        vc = guild.voice_client if guild else None
        if vc and vc.is_connected():
            current_vol = guild_volumes.get(g_id, 0.5)
            current_f = guild_filters.get(g_id, 'normal')
            
            af_options = {
                '8d': 'apulsator=hz=0.09',
                '4d': 'apulsator=hz=0.2:amount=0.9',
                'bass': 'equalizer=f=100:width_type=h:width=200:g=15',
                'nightcore': 'asetrate=44100*1.25,aresample=44100,atempo=1.1',
                'vaporwave': 'asetrate=44100*0.8,aresample=44100,atempo=0.9',
                'normal': 'volume=1.0'
            }
            selected_af = af_options.get(current_f, 'volume=1.0')
            
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': f'-vn -af "{selected_af}"',
            }
            audio_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(next_song['url'], executable=FFMPEG_EXECUTABLE, **ffmpeg_options),
                volume=current_vol * 2.0
            )
            vc.play(audio_source, after=lambda e: play_next(g_id, g_id))
            
            if next_song.get('uploader'):
                asyncio.run_coroutine_threadsafe(
                    ensure_queue_stocked(g_id, next_song['uploader'], next_song.get('requester'), bot.loop, target_size=5), 
                    bot.loop
                )
            embed = create_player_embed(next_song, next_song['requester'], g_id, elapsed_seconds=0)
            target_channel = channel if channel else (current_playing.get(g_id, {}).get('message').channel if current_playing.get(g_id, {}).get('message') else None)
            async def send_and_store():
                if target_channel:
                    msg = await target_channel.send(embed=embed, view=MusicPlayerView())
                    current_playing[g_id] = {
                        'song': next_song,
                        'start_time': time.time(),
                        'seek_offset': 0,
                        'message': msg
                    }
            if target_channel:
                asyncio.run_coroutine_threadsafe(send_and_store(), bot.loop)
    else:
        current_song_data = current_playing.get(g_id, {}).get('song')
        if current_song_data and current_song_data.get('uploader'):
            artist = current_song_data['uploader']
            requester = current_song_data.get('requester')
            
            async def auto_queue_artist():
                new_songs = await preload_artist_songs(artist, bot.loop, count=5)
                if new_songs:
                    if g_id not in music_queues:
                        music_queues[g_id] = []
                    for ns in new_songs:
                        if requester:
                            ns['requester'] = requester
                        music_queues[g_id].append(ns)
                    
                    guild = bot.get_guild(g_id)
                    if guild and guild.voice_client:
                        play_next(g_id, g_id)
            asyncio.run_coroutine_threadsafe(auto_queue_artist(), bot.loop)
            return
        else:
            current_playing.pop(g_id, None)

@bot.event
async def on_ready():
    stream_activity = discord.Streaming(
        name="gang family on top", 
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    await bot.change_presence(status=discord.Status.online, activity=stream_activity)
    try:
        synced = await bot.tree.sync()
        if not update_player_timer.is_running():
            update_player_timer.start()
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Fixed Auto-Rejoin Listener with protection lock against bounce-back loops
@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id and auto_rejoin_enabled:
        guild_id = member.guild.id
        
        if guild_id in rejoining_guilds:
            return
        if guild_id in current_playing:
            target_channel = active_voice_channels.get(guild_id)
            if target_channel:
                if after.channel is None or after.channel.id != target_channel.id:
                    rejoining_guilds.add(guild_id)
                    await asyncio.sleep(1.0)
                    try:
                        if member.guild.voice_client:
                            await member.guild.voice_client.disconnect(force=True)
                        
                        vc = await target_channel.connect()
                        song_data = current_playing[guild_id]
                        song = song_data.get('song')
                        if song:
                            start_time = song_data.get('start_time', time.time())
                            seek_offset = song_data.get('seek_offset', 0)
                            current_elapsed = int(time.time() - start_time + seek_offset)
                            current_vol = guild_volumes.get(guild_id, 0.5)
                            current_f = guild_filters.get(guild_id, 'normal')
                            player = await YTDLSource.from_url(song['url'], loop=bot.loop, stream=True, volume=current_vol * 2.0, seek_seconds=current_elapsed, audio_filter=current_f)
                            vc.play(player, after=lambda e: play_next(guild_id, guild_id))
                    except Exception as e:
                        print(f"Auto-rejoin error: {e}")
                    finally:
                        await asyncio.sleep(2.0)
                        rejoining_guilds.discard(guild_id)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You must be an **Administrator** to use this command.", ephemeral=True)
    else:
        print(f"Command error: {error}")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    content_clean = clean_text(message.content)
    
    if content_clean in ["anime", "انمي"]:
        await start_anime_game(message.channel, message.channel.send)
        return
    if content_clean in ["top", "توب"]:
        await show_points_leaderboard(message.channel, message.channel.send)
        return
    # AUTO-MODERATION
    if not message.channel.is_nsfw():
        is_nsfw_content = False
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                if attachment.is_spoiler() or 'nsfw' in attachment.filename.lower():
                    is_nsfw_content = True
        if message.stickers:
            for sticker in message.stickers:
                if 'nsfw' in sticker.name.lower():
                    is_nsfw_content = True
        content_lower = message.content.lower()
        if 'tenor.com' in content_lower or 'giphy.com' in content_lower:
            if 'nsfw' in content_lower or '18+' in content_lower:
                is_nsfw_content = True
        if is_nsfw_content:
            try:
                await message.delete()
            except Exception:
                pass
            guild_id = message.guild.id
            user_id = message.author.id
            if guild_id not in user_warnings:
                user_warnings[guild_id] = {}
            if user_id not in user_warnings[guild_id]:
                user_warnings[guild_id][user_id] = []
            
            automod_reason = "Automod: Sent NSFW content in a non-NSFW channel"
            user_warnings[guild_id][user_id].append(automod_reason)
            total_warns = len(user_warnings[guild_id][user_id])
            try:
                mute_duration = timedelta(hours=1)
                await message.author.timeout(mute_duration, reason="Auto-Mod: Sent NSFW content in non-NSFW channel.")
            except Exception:
                pass
            try:
                dm_embed = discord.Embed(
                    title="⚠️ Official Server Warning",
                    description=f"Hello **{message.author.name}**, you have received a warning and a **1-hour timeout** in **{message.guild.name}**.",
                    color=discord.Color.red()
                )
                dm_embed.add_field(name="Reason", value=automod_reason, inline=False)
                dm_embed.add_field(name="Total Warnings", value=f"`{total_warns}` active warnings", inline=False)
                dm_embed.set_footer(text="Please adhere to the server rules to avoid further disciplinary actions.")
                await message.author.send(embed=dm_embed)
            except Exception:
                pass
            warning_msg = await message.channel.send(
                f"⚠️ {message.author.mention}, **NSFW images, stickers, or GIFs are strictly prohibited in non-NSFW channels!** You have been muted for 1 hour."
            )
            await asyncio.sleep(10)
            try:
                await warning_msg.delete()
            except Exception:
                pass
            return
    if message.content.startswith('!dm'):
        if not isinstance(message.author, discord.Member) or ALLOWED_ROLE_ID not in [r.id for r in message.author.roles]:
            await message.reply("❌ You must have the **OldAges** role to use this command.")
            return
        args = message.content.split()[1:]
        if len(args) < 2:
            await message.reply("Usage example: `!dm @User Hello!`")
            return
        target_user = message.mentions[0] if message.mentions else None
        if not target_user:
            try:
                target_user = await bot.fetch_user(int(args[0]))
            except:
                pass
        if not target_user:
            await message.reply("User not found.")
            return
        dm_message = " ".join(args[1:]) if message.mentions else " ".join(args[2:])
        
        try:
            await target_user.send(dm_message)
            await message.reply(f"✅ Successfully sent DM to {target_user.name}.")
        except Exception as e:
            await message.reply("❌ Could not send a private message to this user.")
    if message.content.startswith('!delete'):
        if not message.author.guild_permissions.manage_messages:
            await message.reply("❌ You do not have permission to use this command.")
            return
        args = message.content.split()[1:]
        if not args:
            await message.reply("Usage example: `!delete 10` or `!delete 10 @User`")
            return
        amount = 10
        target_user = message.mentions[0] if message.mentions else None
        for arg in args:
            if arg.isdigit():
                amount = int(arg)
        if amount < 1 or amount > 100:
            await message.reply("Please specify a number between 1 and 100.")
            return
        try:
            await message.delete()
        except:
            pass
        if target_user:
            def is_user(msg):
                return msg.author.id == target_user.id
            await message.channel.purge(limit=amount, check=is_user)
        else:
            await message.channel.purge(limit=amount)
        return
    await bot.process_commands(message)

def has_oldages_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member) and ALLOWED_ROLE_ID in [r.id for r in interaction.user.roles]:
            return True
        await interaction.response.send_message("❌ You must have the **OldAges** role to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)

@bot.tree.command(name="dm", description="Sends a private message to a user.")
@app_commands.describe(target="The user to DM", message="The message to send")
@has_oldages_role()
async def slash_dm(interaction: discord.Interaction, target: discord.Member, message: str):
    try:
        await target.send(message)
        await interaction.response.send_message(f"✅ Successfully sent a DM to **{target}**.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Could not send DM to {target}. Their DMs might be closed.", ephemeral=True)

@bot.tree.command(name="anime", description="Guess a random anime character!")
async def anime_slash(interaction: discord.Interaction):
    if interaction.channel_id != ANIME_GAME_CHANNEL_ID:
        return await interaction.response.send_message(f"❌ **قناة خاطئة!** يمكن لعب هذه اللعبة فقط في <#{ANIME_GAME_CHANNEL_ID}>.", ephemeral=True)
    
    await interaction.response.defer()
    async def send_followup(embed=None, content=None, view=None):
        if embed and view:
            return await interaction.followup.send(embed=embed, view=view)
        elif embed:
            return await interaction.followup.send(embed=embed)
        elif content:
            return await interaction.followup.send(content)
    await start_anime_game(interaction.channel, send_followup)

@bot.tree.command(name="انمي", description="خمن شخصية أنمي عشوائية!")
async def anime_arabic_slash(interaction: discord.Interaction):
    if interaction.channel_id != ANIME_GAME_CHANNEL_ID:
        return await interaction.response.send_message(f"❌ **قناة خاطئة!** يمكن لعب هذه اللعبة فقط في <#{ANIME_GAME_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer()
    async def send_followup(embed=None, content=None, view=None):
        if embed and view:
            return await interaction.followup.send(embed=embed, view=view)
        elif embed:
            return await interaction.followup.send(embed=embed)
        elif content:
            return await interaction.followup.send(content)
    await start_anime_game(interaction.channel, send_followup)

@bot.tree.command(name="top", description="View the anime game points leaderboard!")
async def top_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    async def send_followup(embed=None, content=None):
        if embed:
            await interaction.followup.send(embed=embed)
        elif content:
            await interaction.followup.send(content)
    await show_points_leaderboard(interaction.channel, send_followup)

def check_music_lock(guild_id: int, user_id: int) -> tuple[bool, str]:
    if not music_lock_enabled:
        return True, ""
    current_song_data = current_playing.get(guild_id, {})
    song_info = current_song_data.get('song', {})
    requester = song_info.get('requester')
    
    if requester and requester.id == LOCKED_USER_ID and user_id != LOCKED_USER_ID:
        return False, "❌ **Protection lock is active!** This song was requested by the protected user, and other users cannot use music commands right now."
    return True, ""

@bot.tree.command(name="lock", description="Enables the protection lock on music controls (Restricted to the designated user).")
async def lock_command(interaction: discord.Interaction):
    if interaction.user.id != LOCKED_USER_ID:
        return await interaction.response.send_message("❌ **You are not authorized to use this command!** Only the designated user can lock the music controls.", ephemeral=True)
    
    global music_lock_enabled
    music_lock_enabled = True
    await interaction.response.send_message("🔒 Music control protection lock has been **ENABLED**.", ephemeral=True)

@bot.tree.command(name="unlock", description="Disables the protection lock on music controls (Administrator only).")
@app_commands.checks.has_permissions(administrator=True)
async def unlock_command(interaction: discord.Interaction):
    global music_lock_enabled
    music_lock_enabled = False
    await interaction.response.send_message("🔓 Music control protection lock has been **DISABLED**.", ephemeral=True)

@bot.tree.command(name="autorejoin", description="Enables auto-rejoin protection if the bot is kicked or moved (Administrator only).")
@app_commands.checks.has_permissions(administrator=True)
async def autorejoin_command(interaction: discord.Interaction):
    global auto_rejoin_enabled
    if auto_rejoin_enabled:
        return await interaction.response.send_message("ℹ️ Auto-rejoin protection is **already enabled**.", ephemeral=True)
    auto_rejoin_enabled = True
    await interaction.response.send_message("🔄 Auto-rejoin protection has been **ENABLED**.", ephemeral=True)

@bot.tree.command(name="disablerejoin", description="Disables auto-rejoin protection if the bot is kicked or moved (Administrator only).")
@app_commands.checks.has_permissions(administrator=True)
async def disablerejoin_command(interaction: discord.Interaction):
    global auto_rejoin_enabled
    if not auto_rejoin_enabled:
        return await interaction.response.send_message("ℹ️ Auto-rejoin protection is **already disabled**.", ephemeral=True)
    auto_rejoin_enabled = False
    await interaction.response.send_message("🛑 Auto-rejoin protection has been **DISABLED**.", ephemeral=True)

@bot.tree.command(name="setactivity", description="Changes the bot's activity status (Administrator only).")
@app_commands.describe(
    activity_type="Choose the activity type (streaming, playing, listening, watching)", 
    text="The message/status text to show", 
    url="Paste your YouTube or Twitch video URL here"
)
@app_commands.choices(activity_type=[
    app_commands.Choice(name="Streaming (Purple status with link)", value="streaming"),
    app_commands.Choice(name="Playing", value="playing"),
    app_commands.Choice(name="Listening", value="listening"),
    app_commands.Choice(name="Watching", value="watching")
])
@app_commands.checks.has_permissions(administrator=True)
async def setactivity(interaction: discord.Interaction, activity_type: str, text: str, url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
    if activity_type == "streaming":
        activity = discord.Streaming(name=text, url=url)
    elif activity_type == "playing":
        activity = discord.Game(name=text)
    elif activity_type == "listening":
        activity = discord.Activity(type=discord.ActivityType.listening, name=text)
    elif activity_type == "watching":
        activity = discord.Activity(type=discord.ActivityType.watching, name=text)
    else:
        activity = discord.Game(name=text)
    await bot.change_presence(activity=activity)
    await interaction.response.send_message(f"✅ Successfully updated bot activity to **{activity_type}**: `{text}` (URL: `{url}`)", ephemeral=True)

@bot.tree.command(name="join", description="Joins your current voice channel.")
async def join(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ You are not in a voice channel!", ephemeral=True)
    channel = interaction.user.voice.channel
    active_voice_channels[interaction.guild_id] = channel
    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.move_to(channel)
    else:
        await channel.connect()
    await interaction.response.send_message(f"🔊 Joined **{channel.name}**")

@bot.tree.command(name="watch", description="Starts a YouTube Watch Together activity in your voice channel.")
async def watch(interaction: discord.Interaction):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ You must be in a voice channel first!", ephemeral=True)
    
    channel = interaction.user.voice.channel
    try:
        invite = await channel.create_invite(
            target_type=discord.InviteTarget.embedded_application,
            target_application_id=880218394243220458
        )
        await interaction.response.send_message(f"📺 Click here to start watching YouTube together:\n{invite}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Could not create activity link. Make sure the bot has 'Create Invite' permissions.\nError: {e}", ephemeral=True)

async def play_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if not current or len(current.strip()) < 2:
        default_suggestions = [
            "A.L.A - L.V.L 15",
            "Top Hits Playlist",
            "Top Rap Mix",
            "Trending Music"
        ]
        return [app_commands.Choice(name=c, value=c) for c in default_suggestions]
    search_opts = dict(YTDL_OPTIONS)
    search_opts['default_search'] = 'ytsearch10'
    
    try:
        def search():
            with yt_dlp.YoutubeDL(search_opts) as ytdl_search:
                return ytdl_search.extract_info(f"{current} tracks", download=False)
                
        data = await bot.loop.run_in_executor(None, search)
        choices = []
        if 'entries' in data:
            for entry in data['entries']:
                title = entry.get('title')
                uploader = entry.get('uploader', '')
                if title:
                    display_name = f"{title} — ({uploader})" if uploader else title
                    choices.append(app_commands.Choice(name=display_name[:100], value=title[:100]))
                    
        return choices[:25] if choices else [app_commands.Choice(name=current, value=current)]
    except Exception:
        return [app_commands.Choice(name=current, value=current)]

@bot.tree.command(name="play", description="Plays a song from YouTube (URL or search term).")
@app_commands.describe(query="Song title, artist name, or YouTube URL")
@app_commands.autocomplete(query=play_autocomplete)
async def play(interaction: discord.Interaction, query: str):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ You must be in a voice channel first!", ephemeral=True)
    await interaction.response.defer()
    
    channel = interaction.user.voice.channel
    active_voice_channels[interaction.guild_id] = channel
    voice_client = interaction.guild.voice_client
    if not voice_client:
        voice_client = await channel.connect()
    guild_id = interaction.guild_id
    if guild_id not in guild_volumes:
        guild_volumes[guild_id] = 0.5
    if guild_id not in guild_filters:
        guild_filters[guild_id] = 'normal'
    try:
        current_vol = guild_volumes[guild_id]
        current_f = guild_filters[guild_id]
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True, volume=current_vol * 2.0, audio_filter=current_f)
    except Exception as e:
        return await interaction.followup.send(f"⚠️ Could not process audio: {e}")
    if guild_id not in music_queues:
        music_queues[guild_id] = []
    song_info = {
        'title': player.title,
        'url': player.url,
        'thumbnail': player.thumbnail,
        'duration': player.duration,
        'uploader': player.uploader,
        'webpage_url': player.data.get('webpage_url', player.url),
        'requester': interaction.user
    }
    if voice_client.is_playing() or voice_client.is_paused():
        music_queues[guild_id].insert(0, song_info)
        voice_client.stop()
        await interaction.followup.send(f"🎵 Skipped queue and playing now: **{player.title}**")
    else:
        voice_client.play(player, after=lambda e: play_next(interaction, guild_id))
        
        asyncio.create_task(ensure_queue_stocked(guild_id, song_info['uploader'], interaction.user, bot.loop, target_size=5))
        
        embed = create_player_embed(song_info, interaction.user, guild_id, elapsed_seconds=0)
        msg = await interaction.followup.send(embed=embed, view=MusicPlayerView())
        current_playing[guild_id] = {
            'song': song_info,
            'start_time': time.time(),
            'seek_offset': 0,
            'message': msg
        }

@bot.tree.command(name="seek", description="Jumps to a specific second in the current song.")
@app_commands.describe(seconds="Second mark to jump to (e.g. 90 for 1 minute 30 seconds)")
async def seek(interaction: discord.Interaction, seconds: int):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    guild_id = interaction.guild_id
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        return await interaction.response.send_message("❌ No music is currently playing to seek.", ephemeral=True)
    await interaction.response.defer()
    success = await perform_seek(guild_id, vc, seconds)
    if success:
        time_formatted = str(timedelta(seconds=seconds))
        await interaction.followup.send(f"⏩ Seeked to **{time_formatted}** ({seconds}s).")
    else:
        await interaction.followup.send("❌ Could not seek audio.", ephemeral=True)

@bot.tree.command(name="skip", description="Skips current song and plays a random song from the same singer.")
async def skip(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    await interaction.response.defer()
    guild_id = interaction.guild_id
    vc = interaction.guild.voice_client
    success = await skip_and_play_artist_random(guild_id, interaction.user, vc)
    if success:
        await interaction.followup.send("⏭️ Skipped track instantly!", ephemeral=True)
    else:
        await interaction.followup.send("❌ No music is currently playing to skip.", ephemeral=True)

@bot.tree.command(name="volume", description="Changes the player volume (0 to 300%).")
@app_commands.describe(percent="Volume percentage from 0 to 300")
async def volume(interaction: discord.Interaction, percent: int):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    if percent < 0 or percent > 300:
        return await interaction.response.send_message("❌ Volume must be between **0** and **300** percent.", ephemeral=True)
    guild_id = interaction.guild_id
    volume_factor = percent / 200.0
    guild_volumes[guild_id] = volume_factor
    vc = interaction.guild.voice_client
    if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = volume_factor * 2.0
    await interaction.response.send_message(f"🔊 Volume set to **{percent}%**.")

@bot.tree.command(name="pause", description="Pauses current music playback.")
async def pause(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Music paused.")
    else:
        await interaction.response.send_message("❌ No music is currently playing.", ephemeral=True)

@bot.tree.command(name="resume", description="Resumes paused music.")
async def resume(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Music resumed.")
    else:
        await interaction.response.send_message("❌ Music is not paused.", ephemeral=True)

@bot.tree.command(name="stop", description="Stops music and clears queue.")
async def stop(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    guild_id = interaction.guild_id
    if guild_id in music_queues:
        music_queues[guild_id].clear()
    current_playing.pop(guild_id, None)
    active_voice_channels.pop(guild_id, None)
    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")
    else:
        await interaction.response.send_message("❌ Bot is not in a voice channel.", ephemeral=True)

@bot.tree.command(name="queue", description="Displays songs currently in queue.")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    current_song = current_playing.get(guild_id, {}).get('song')
    queue_list = music_queues.get(guild_id, [])
    if not current_song and len(queue_list) == 0:
        return await interaction.response.send_message("📄 Queue and current playback are empty.", ephemeral=True)
    embed = discord.Embed(title="🎶 Music Queue & Upcoming Songs", color=discord.Color.blue())
    
    if current_song:
        embed.add_field(name="▶️ Currently Playing", value=f"**{current_song['title']}** (`{current_song.get('uploader', 'Unknown Artist')}`)", inline=False)
    if len(queue_list) > 0:
        description = ""
        for idx, song in enumerate(queue_list[:10], start=1):
            description += f"**{idx}.** {song['title']} — *{song.get('uploader', 'Unknown Artist')}*\n"
        embed.add_field(name="📜 Coming Up Next", value=description, inline=False)
    else:
        embed.add_field(name="📜 Coming Up Next", value="*Loading upcoming tracks...*", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

history_group = app_commands.Group(name="history", description="Manage song playback history")
@history_group.command(name="show", description="Displays the recently played songs history.")
async def history_show(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    history_list = music_history.get(guild_id, [])
    if not history_list:
        return await interaction.response.send_message("📜 No song history found yet.", ephemeral=True)
    embed = discord.Embed(title="📜 Recently Played History", color=discord.Color.purple())
    description = ""
    for idx, song in enumerate(reversed(history_list[-10:]), start=1):
        description += f"**{idx}.** [{song['title']}]({song.get('webpage_url', song['url'])}) — *{song.get('uploader', 'Unknown Artist')}*\n"
    
    embed.description = description
    await interaction.response.send_message(embed=embed, ephemeral=True)

@history_group.command(name="clear", description="Clears the recently played songs history (Requires specific role or higher).")
async def history_clear(interaction: discord.Interaction):
    required_role_id = 1483526094937391195
    role = interaction.guild.get_role(required_role_id)
    if not role:
        return await interaction.response.send_message("❌ The specified role ID does not exist on this server.", ephemeral=True)
    has_permission = role in interaction.user.roles or interaction.user.top_role.position >= role.position
    if not has_permission:
        return await interaction.response.send_message("❌ You do not have the required role hierarchy to clear the history!", ephemeral=True)
    guild_id = interaction.guild_id
    if guild_id in music_history and len(music_history[guild_id]) > 0:
        music_history[guild_id].clear()
        await interaction.response.send_message("🗑️ Successfully cleared the recently played music history.", ephemeral=True)
    else:
        await interaction.response.send_message("📜 There is no history to clear.", ephemeral=True)
bot.tree.add_command(history_group)

warn_group = app_commands.Group(name="warn", description="Manage user warnings")
@warn_group.command(name="check", description="Checks how many warnings a user has and the reasons.")
@app_commands.describe(target="The user to check warnings for")
async def warn_check(interaction: discord.Interaction, target: discord.Member):
    guild_id = interaction.guild.id
    user_id = target.id
    
    warnings = user_warnings.get(guild_id, {}).get(user_id, [])
    count = len(warnings)
    embed = discord.Embed(title=f"⚠️ Warning Record for {target.name}", color=discord.Color.orange())
    embed.add_field(name="Total Warnings", value=str(count), inline=False)
    if count > 0:
        reasons_desc = ""
        for idx, reason in enumerate(warnings, start=1):
            reasons_desc += f"**{idx}.** {reason}\n"
        embed.add_field(name="Reasons", value=reasons_desc, inline=False)
    else:
        embed.add_field(name="Reasons", value="*This user has a clean record!*", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@warn_group.command(name="add", description="Issues a warning to a user.")
@app_commands.describe(target="The user to warn", reason="Reason for the warning")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_add(interaction: discord.Interaction, target: discord.Member, reason: str = "No reason provided"):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(
            f"❌ You cannot warn **{target}** because they have a higher or equal role to you!", ephemeral=True
        )
    guild_id = interaction.guild.id
    user_id = target.id
    if guild_id not in user_warnings:
        user_warnings[guild_id] = {}
    if user_id not in user_warnings[guild_id]:
        user_warnings[guild_id][user_id] = []
    user_warnings[guild_id][user_id].append(reason)
    total_warns = len(user_warnings[guild_id][user_id])
    
    try:
        dm_embed = discord.Embed(
            title="⚠️ Official Server Warning",
            description=f"Hello **{target.name}**, you have received a formal warning in **{interaction.guild.name}**.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        dm_embed.add_field(name="Reason", value=f"`{reason}`", inline=False)
        dm_embed.add_field(name="Total Warnings", value=f"`{total_warns}` active warning(s)", inline=False)
        dm_embed.set_footer(text=f"Action taken by {interaction.user.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await target.send(embed=dm_embed)
    except Exception:
        pass
    await interaction.response.send_message(
        f"⚠️ Successfully warned **{target}** and sent them a notification DM. Total warnings: **{total_warns}**\n*Reason:* `{reason}`", ephemeral=True
    )

@warn_group.command(name="remove", description="Removes the most recent warning from a user (Unwarn).")
@app_commands.describe(target="The user to remove a warning from")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_remove(interaction: discord.Interaction, target: discord.Member):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot manage warnings for **{target}** because they have a higher or equal role to you!", ephemeral=True)
    guild_id = interaction.guild.id
    user_id = target.id
    if guild_id in user_warnings and user_id in user_warnings[guild_id] and len(user_warnings[guild_id][user_id]) > 0:
        removed_reason = user_warnings[guild_id][user_id].pop()
        remaining_count = len(user_warnings[guild_id][user_id])
        await interaction.response.send_message(f"✅ Removed latest warning from **{target}**.\n*Removed reason:* `{removed_reason}`\nRemaining warnings: **{remaining_count}**", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{target}** has no active warnings to remove.", ephemeral=True)
bot.tree.add_command(warn_group)

@bot.tree.command(name="leave", description="Disconnects the bot from voice.")
async def leave(interaction: discord.Interaction):
    allowed, msg = check_music_lock(interaction.guild_id, interaction.user.id)
    if not allowed:
        return await interaction.response.send_message(msg, ephemeral=True)
    vc = interaction.guild.voice_client
    if vc:
        guild_id = interaction.guild_id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        current_playing.pop(guild_id, None)
        active_voice_channels.pop(guild_id, None)
        await vc.disconnect()
        await interaction.response.send_message("👋 Disconnected from voice channel.")
    else:
        await interaction.response.send_message("❌ I am not in a voice channel.", ephemeral=True)

@bot.tree.command(name="ban", description="Bans a user from the server.")
@app_commands.describe(target="The user to ban", reason="Reason for the ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, target: discord.Member, reason: str = "No reason provided"):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot ban **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    if not target.bannable:
        return await interaction.response.send_message("Cannot ban this user.", ephemeral=True)
    await target.ban(reason=reason)
    embed = discord.Embed(title="🔨 User Banned", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=False)
    embed.add_field(name="Moderator", value=f"{interaction.user}", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unban", description="Unbans a user by User ID.")
@app_commands.describe(user_id="The ID of the user to unban", reason="Reason for the unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(f"✅ Successfully unbanned **{user.name}** (`{user.id}`).")
    except discord.NotFound:
        await interaction.response.send_message("User was not found or is not banned.", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("Invalid User ID format.", ephemeral=True)

@bot.tree.command(name="kick", description="Kicks a user from the server.")
@app_commands.describe(target="The user to kick", reason="Reason for the kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, target: discord.Member, reason: str = "No reason provided"):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot kick **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    if not target.kickable:
        return await interaction.response.send_message("Cannot kick this user.", ephemeral=True)
    await target.kick(reason=reason)
    embed = discord.Embed(title="👢 User Kicked", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=False)
    embed.add_field(name="Moderator", value=f"{interaction.user}", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="timeout", description="Times out (mutes) a user for a duration in minutes.")
@app_commands.describe(target="The user to timeout", minutes="Duration in minutes", reason="Reason for timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, target: discord.Member, minutes: int, reason: str = "No reason provided"):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot timeout **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    if not target.is_moderatable():
        return await interaction.response.send_message("Cannot timeout this user.", ephemeral=True)
    duration = timedelta(minutes=minutes)
    await target.timeout(duration, reason=reason)
    await interaction.response.send_message(f"🔇 **{target}** has been timed out for **{minutes}** minute(s).")

@bot.tree.command(name="untimeout", description="Removes timeout from a user.")
@app_commands.describe(target="The user to remove timeout from")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, target: discord.Member):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot remove timeout from **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    await target.timeout(None)
    await interaction.response.send_message(f"🔊 Removed timeout for **{target}**.")

@bot.tree.command(name="addrole", description="Gives a role to a user.")
@app_commands.describe(target="The user to give the role to", role="The role to assign")
@app_commands.checks.has_permissions(manage_roles=True)
async def addrole(interaction: discord.Interaction, target: discord.Member, role: discord.Role):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot assign roles to **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    if role in target.roles:
        return await interaction.response.send_message(f"**{target}** already has the **{role.name}** role.", ephemeral=True)
    
    await target.add_roles(role)
    await interaction.response.send_message(f"✅ Added **{role.name}** to **{target}**.")

@bot.tree.command(name="removerole", description="Removes a role from a user.")
@app_commands.describe(target="The user to remove the role from", role="The role to remove")
@app_commands.checks.has_permissions(manage_roles=True)
async def removerole(interaction: discord.Interaction, target: discord.Member, role: discord.Role):
    if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(f"❌ You cannot remove roles from **{target}** because they are higher than you or have an equal role!", ephemeral=True)
    if role not in target.roles:
        return await interaction.response.send_message(f"**{target}** does not have the **{role.name}** role.", ephemeral=True)
    
    await target.remove_roles(role)
    await interaction.response.send_message(f"❌ Removed **{role.name}** from **{target}**.")

@bot.tree.command(name="purge", description="Deletes up to 100 messages in this channel.")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("Please specify between 1 and 100 messages.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Bulk deleted **{len(deleted)}** messages.", ephemeral=True)

@bot.tree.command(name="delete", description="Deletes messages (optionally from a specific user).")
@app_commands.describe(amount="Number of messages to scan (1-100)", target="Optional user whose messages to delete")
@app_commands.checks.has_permissions(manage_messages=True)
async def delete_slash(interaction: discord.Interaction, amount: int = 10, target: discord.Member = None):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("Please specify a number between 1 and 100.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    if target:
        if interaction.user.top_role.position <= target.top_role.position and interaction.user != interaction.guild.owner:
            return await interaction.followup.send(f"❌ You cannot delete messages from **{target}** because they are higher than you or have an equal role!", ephemeral=True)
        def is_user(msg):
            return msg.author.id == target.id
        deleted = await interaction.channel.purge(limit=amount, check=is_user)
        await interaction.followup.send(f"🧹 Successfully deleted **{len(deleted)}** messages from **{target}**.", ephemeral=True)
    else:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Successfully deleted **{len(deleted)}** messages.", ephemeral=True)

bot.run("MTU2MDI5MDg1NTc3OTA0MTM4MQ.GhmjRD.YnEImusiYgmPxniO_n34gCzRoEQNjnNo07pJ14")
