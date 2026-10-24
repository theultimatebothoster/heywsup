"""
nexus_dashboard.py
Complete Gang Family Discord Bot + Web Dashboard in a single Python file.
Technology: Python, discord.py, FastAPI, Discord OAuth2, SQLite, Embedded HTML/CSS/JS, OpenAI, python-dotenv.
"""

import os
import sys
import sqlite3
import json
import time
import datetime
import asyncio
import hmac
import hashlib
import urllib.parse
import random
import re
import ctypes.util
import yt_dlp
import aiohttp
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import uvicorn
from openai import OpenAI

import discord
from discord.ext import commands, tasks

# ==========================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback")
OWNER_DISCORD_ID = str(os.getenv("OWNER_DISCORD_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "gang-family-super-secret-key-change-in-prod")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ==========================================
# DATABASE INITIALIZATION (SQLite)
# ==========================================
DB_FILE = "gang_family_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS moderators (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            added_by TEXT,
            added_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            reason TEXT,
            banned_by TEXT,
            banned_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            username TEXT,
            action TEXT,
            details TEXT,
            timestamp TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    defaults = {
        "ai_enabled": "true",
        "ai_model": "gpt-4o-mini",
        "ai_system_prompt": "You are Gang Family AI, an intelligent assistant.",
        "music_enabled": "true",
        "music_default_volume": "80",
        "welcome_enabled": "true",
        "welcome_channel": "general",
        "welcome_message": "Welcome to Gang Family, {user}!",
        "feature_slash_commands": "true",
        "feature_prefix_commands": "true",
        "feature_auto_mod": "true"
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
        
    default_stats = {
        "commands_executed": "0",
        "ai_requests": "0",
        "errors_logged": "0",
        "start_time": str(time.time())
    }
    for k, v in default_stats.items():
        cursor.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

init_db()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = None
    if fetchone:
        res = cursor.fetchone()
    elif fetchall:
        res = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return res

def log_audit(user_id: str, username: str, action: str, details: str):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db_query(
        "INSERT INTO audit_logs (user_id, username, action, details, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, action, details, timestamp),
        commit=True
    )

def increment_stat(key: str, amount: int = 1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM stats WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row:
        val = int(row[0]) + amount
        cursor.execute("UPDATE stats SET value = ? WHERE key = ?", (str(val), key))
    else:
        cursor.execute("INSERT INTO stats (key, value) VALUES (?, ?)", (key, str(amount)))
    conn.commit()
    conn.close()

# ==========================================
# DISCORD BOT SETUP & LOGIC FROM SCRIPT
# ==========================================
ANIME_GAME_CHANNEL_ID = 1534536134040748033
LOCKED_USER_ID = 1537275886758264964
music_lock_enabled = True
auto_rejoin_enabled = True
rejoining_guilds = set()
active_anime_games = set()
user_points = {}
ALLOWED_ROLE_ID = 1483526094937391195
user_warnings = {}
guild_filters = {}
guild_voice_qualities = {}
active_voice_channels = {}

if not discord.opus.is_loaded():
    libname = ctypes.util.find_library('opus') or 'libopus-0.dll'
    try:
        discord.opus.load_opus(libname)
    except Exception as e:
        print(f"Could not load opus: {e}")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

music_queues = {}
music_history = {}
guild_volumes = {}
current_playing = {}

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
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r'[\u064B-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'[ى]', 'ي', text)
    text = re.sub(r'[ؤئ]', 'ء', text)
    return text

async def fetch_random_anime_character():
    url = 'https://graphql.anilist.co'
    random_page = random.randint(1, 150)
    query = '''
    query ($page: Int) {
      Page(page: $page, perPage: 1) {
        characters(sort: FAVOURITES_DESC) {
          name { full native alternative }
          image { large }
          media(sort: POPULARITY_DESC, perPage: 1) {
            nodes { title { english romaji } }
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
                for p in full_name.split():
                    aliases.append(clean_text(p))
                if char_data['name']['alternative']:
                    for alt in char_data['name']['alternative']:
                        if alt: aliases.append(clean_text(alt))
                lower_full = full_name.lower()
                arabic_names = []
                if lower_full in ARABIC_NAME_MAP:
                    for ar in ARABIC_NAME_MAP[lower_full]:
                        aliases.append(clean_text(ar))
                        arabic_names.append(ar)
                anime_title = "غير معروف"
                if char_data['media']['nodes']:
                    media = char_data['media']['nodes'][0]['title']
                    anime_title = media['english'] or media['romaji'] or "غير معروف"
                primary_arabic = arabic_names[0] if arabic_names else full_name
                return {
                    "name": full_name, "arabic_name": primary_arabic,
                    "aliases": list(set(aliases)), "image": image_url, "anime": anime_title
                }
            return None

async def show_points_leaderboard(channel, send_func):
    if not user_points:
        await send_func("📊 **لا توجد نقاط مسجلة بعد! العب لعبة الأنمي لجمع النقاط.**")
        return
    sorted_users = sorted(user_points.items(), key=lambda item: item[1], reverse=True)[:10]
    description = ""
    for idx, (uid, pts) in enumerate(sorted_users, start=1):
        medal = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"`#{idx}`"))
        description += f"{medal} <@{uid}> — **{pts}** نقطة\n"
    embed = discord.Embed(title="🏆 لوحة شرف نقاط الأنمي", description=description, color=discord.Color.gold())
    await send_func(embed=embed)

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
            return await interaction.response.send_message(f"🔒 نقاط غير كافية لديك {pts} نقطة.", ephemeral=True)
        user_points[uid] -= 5
        await interaction.response.send_message(f"💡 الأنمي: *{self.character['anime']}*, الحرف الأول: `{self.character['name'][0].upper()}`", ephemeral=True)
    @discord.ui.button(label="🛑 إيقاف اللعبة", style=discord.ButtonStyle.danger, custom_id="anime_stop_btn")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stopped = True
        self.stopped_by = interaction.user
        self.stop()
        await interaction.response.defer()

async def start_anime_game(channel, send_func):
    if channel.id != ANIME_GAME_CHANNEL_ID:
        await send_func(f"❌ قناة خاطئة! خصصت اللعبة لـ <#{ANIME_GAME_CHANNEL_ID}>.")
        return
    if channel.id in active_anime_games:
        return
    active_anime_games.add(channel.id)
    try:
        character = await fetch_random_anime_character()
        if not character: return
        view = AnimeGameControls(character)
        embed = discord.Embed(title="🖼️ خمن شخصية الأنمي!", description="لديك 30 ثانية لتخمين اسم الشخصية بالعربية أو الإنجليزية!", color=0xFF69B4)
        embed.set_image(url=character["image"])
        game_msg = await send_func(embed=embed, view=view)
        def check(m: discord.Message):
            return m.channel == channel and not m.author.bot and clean_text(m.content) in character["aliases"]
        guessed_message = None
        start_time = time.time()
        while time.time() - start_time < 30.0:
            if view.stopped: break
            try:
                guessed_message = await bot.wait_for('message', timeout=1.0, check=check)
                if guessed_message: break
            except asyncio.TimeoutError:
                continue
        view.stop()
        if guessed_message:
            uid = guessed_message.author.id
            user_points[uid] = user_points.get(uid, 0) + 1
            await guessed_message.reply(f"🎉 إجابة صحيحة يا {guessed_message.author.mention}! الشخصية هي **{character['name']}** ({character['arabic_name']})")
        else:
            await channel.send(f"⏰ انتهى الوقت! الشخصية الصحيحة كانت **{character['name']}**.")
    finally:
        active_anime_games.remove(channel.id)

YTDL_OPTIONS = {
    'format': 'bestaudio/best', 'extractaudio': True, 'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s', 'restrictfilenames': True,
    'noplaylist': True, 'nocheckcertificate': True, 'quiet': True, 'default_search': 'auto',
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
        if 'entries' in data: data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        if seek_seconds > 0: before_options += f' -ss {seek_seconds}'
        af_options = {
            '8d': 'apulsator=hz=0.09', 'bass': 'equalizer=f=100:width_type=h:width=200:g=15',
            'nightcore': 'asetrate=44100*1.25,aresample=44100,atempo=1.1', 'normal': 'volume=1.0'
        }
        selected_af = af_options.get(audio_filter, 'volume=1.0')
        ffmpeg_options = {'before_options': before_options, 'options': f'-vn -af "{selected_af}"'}
        return cls(discord.FFmpegPCMAudio(filename, executable=FFMPEG_EXECUTABLE, **ffmpeg_options), data=data, volume=volume)

def create_progress_bar(elapsed: int, total: int, bar_length: int = 15) -> str:
    if total <= 0: return "🔘" + "▬" * (bar_length - 1)
    progress = min(1.0, max(0.0, elapsed / total))
    dot_position = int(progress * (bar_length - 1))
    return "".join(["🔘" if i == dot_position else "▬" for i in range(bar_length)])

def create_player_embed(song_info, requester: discord.Member, guild_id: int, elapsed_seconds: int = 0):
    duration = song_info.get('duration', 0)
    duration_str = str(timedelta(seconds=duration)) if duration else "Live"
    elapsed_str = str(timedelta(seconds=elapsed_seconds)) if duration else "0:00"
    progress_bar = create_progress_bar(elapsed_seconds, duration)
    embed = discord.Embed(title=song_info['title'], url=song_info.get('webpage_url', song_info['url']), color=discord.Color.from_rgb(47, 49, 54))
    embed.description = f"**{song_info.get('uploader', 'Artist')}**\n\n{progress_bar} `{elapsed_str} / {duration_str}`"
    if song_info.get('thumbnail'): embed.set_thumbnail(url=song_info['thumbnail'])
    embed.add_field(name="Requested by", value=f"{requester.mention}", inline=True)
    return embed

async def preload_artist_songs(artist_name: str, loop, count: int = 5):
    search_opts = dict(YTDL_OPTIONS)
    search_opts['default_search'] = f'ytsearch15'
    songs = []
    try:
        def search():
            with yt_dlp.YoutubeDL(search_opts) as ytdl_search:
                return ytdl_search.extract_info(f"{artist_name} songs", download=False)
        data = await loop.run_in_executor(None, search)
        if 'entries' in data:
            for entry in data['entries'][:count]:
                songs.append({'title': entry.get('title'), 'url': entry.get('url'), 'thumbnail': entry.get('thumbnail'), 'duration': entry.get('duration', 0), 'uploader': entry.get('uploader', artist_name)})
    except Exception: pass
    return songs

async def ensure_queue_stocked(guild_id: int, artist_name: str, requester, loop, target_size: int = 5):
    if guild_id not in music_queues: music_queues[guild_id] = []
    if len(music_queues[guild_id]) < target_size:
        new_songs = await preload_artist_songs(artist_name, loop, count=5)
        for ns in new_songs:
            ns['requester'] = requester
            music_queues[guild_id].append(ns)

class MusicPlayerView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, custom_id="pause_btn")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing(): vc.pause(); await interaction.response.send_message("⏸️ Paused.", ephemeral=True)
        elif vc and vc.is_paused(): vc.resume(); await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else: await interaction.response.send_message("❌ Nothing playing.", ephemeral=True)
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="stop_btn")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        if guild_id in music_queues: music_queues[guild_id].clear()
        current_playing.pop(guild_id, None)
        vc = interaction.guild.voice_client
        if vc: vc.stop(); await interaction.response.send_message("⏹️ Stopped.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online, activity=discord.Streaming(name="gang family on top", url="https://www.twitch.tv/monstercat"))
    try:
        synced = await bot.tree.sync()
        print(f"Logged in as {bot.user} | Synced {len(synced)} commands.")
    except Exception as e: print(e)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    content_clean = clean_text(message.content)
    if content_clean in ["anime", "انمي"]: await start_anime_game(message.channel, message.channel.send); return
    if content_clean in ["top", "توب"]: await show_points_leaderboard(message.channel, message.channel.send); return
    await bot.process_commands(message)

# ==========================================
# FASTAPI WEB APP & AUTHENTICATION
# ==========================================
app = FastAPI(title="Gang Family Dashboard", version="2.0.0")

def sign_session(data: dict) -> str:
    payload = json.dumps(data)
    sig = hmac.new(SESSION_SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"

def verify_session(cookie_val: str) -> Optional[dict]:
    if not cookie_val or "." not in cookie_val: return None
    payload, sig = cookie_val.rsplit(".", 1)
    expected_sig = hmac.new(SESSION_SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected_sig):
        try: return json.loads(payload)
        except: return None
    return None

def get_current_user(request: Request) -> Optional[dict]:
    return verify_session(request.cookies.get("gang_family_session"))

async def require_auth(request: Request) -> dict:
    user = get_current_user(request)
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_owner_or_mod(request: Request) -> dict:
    user = await require_auth(request)
    uid = str(user["id"])
    is_owner = (uid == OWNER_DISCORD_ID)
    mod = db_query("SELECT * FROM moderators WHERE user_id = ?", (uid,), fetchone=True)
    if not is_owner and not mod:
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    user["is_owner"] = is_owner
    user["is_moderator"] = bool(mod) or is_owner
    return user

async def require_owner(request: Request) -> dict:
    user = await require_auth(request)
    if str(user["id"]) != OWNER_DISCORD_ID:
        raise HTTPException(status_code=403, detail="Owner required")
    user["is_owner"] = True
    user["is_moderator"] = True
    return user

@app.on_event("startup")
async def startup_event():
    if DISCORD_BOT_TOKEN:
        asyncio.create_task(bot.start(DISCORD_BOT_TOKEN))

@app.on_event("shutdown")
async def shutdown_event():
    await bot.close()

@app.get("/auth/login")
def auth_login():
    return RedirectResponse(f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={urllib.parse.quote(DISCORD_REDIRECT_URI, safe='')}&response_type=code&scope=identify%20guilds")

@app.get("/auth/callback")
async def auth_callback(code: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": DISCORD_REDIRECT_URI
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code != 200: raise HTTPException(status_code=400, detail="OAuth token error")
        token_data = resp.json()
        user_resp = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token_data.get('access_token')}"})
    
    user_info = user_resp.json()
    uid = str(user_info["id"])
    is_owner = (uid == OWNER_DISCORD_ID)
    is_mod = bool(db_query("SELECT * FROM moderators WHERE user_id = ?", (uid,), fetchone=True)) or is_owner
    
    session_data = {"id": uid, "username": user_info.get("username"), "avatar": user_info.get("avatar"), "is_owner": is_owner, "is_moderator": is_mod}
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="gang_family_session", value=sign_session(session_data), httponly=True, max_age=60*60*24*7)
    log_audit(uid, user_info.get("username"), "LOGIN", "Logged into dashboard")
    return response

@app.get("/auth/logout")
def auth_logout(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("gang_family_session")
    return response

@app.post("/api/config")
async def update_config(request: Request):
    user = await require_owner(request)
    form = await request.form()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for k, v in form.items(): cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit(); conn.close()
    log_audit(user["id"], user["username"], "UPDATE_CONFIG", "Updated bot configuration")
    return {"status": "success"}

@app.post("/api/moderators/add")
async def add_moderator(request: Request, user_id: str = Form(...), username: str = Form(...)):
    current_user = await require_owner(request)
    db_query("INSERT OR REPLACE INTO moderators (user_id, username, added_by, added_at) VALUES (?, ?, ?, ?)", 
             (user_id, username, current_user["username"], datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")), commit=True)
    log_audit(current_user["id"], current_user["username"], "ADD_MODERATOR", f"Added mod {username}")
    return {"status": "success"}

@app.post("/api/moderators/remove")
async def remove_moderator(request: Request, user_id: str = Form(...)):
    current_user = await require_owner(request)
    db_query("DELETE FROM moderators WHERE user_id = ?", (user_id,), commit=True)
    log_audit(current_user["id"], current_user["username"], "REMOVE_MODERATOR", f"Removed mod ID {user_id}")
    return {"status": "success"}

@app.post("/api/bans/add")
async def add_ban(request: Request, user_id: str = Form(...), username: str = Form(...), reason: str = Form(...)):
    current_user = await require_owner_or_mod(request)
    db_query("INSERT OR REPLACE INTO bans (user_id, username, reason, banned_by, banned_at) VALUES (?, ?, ?, ?, ?)", 
             (user_id, username, reason, current_user["username"], datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")), commit=True)
    log_audit(current_user["id"], current_user["username"], "BAN_USER", f"Banned user {username}")
    return {"status": "success"}

@app.post("/api/bans/remove")
async def remove_ban(request: Request, user_id: str = Form(...)):
    current_user = await require_owner_or_mod(request)
    db_query("DELETE FROM bans WHERE user_id = ?", (user_id,), commit=True)
    log_audit(current_user["id"], current_user["username"], "UNBAN_USER", f"Unbanned user ID {user_id}")
    return {"status": "success"}

# ==========================================
# FRONTEND TEMPLATE (HTML / CSS / JS)
# ==========================================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gang Family Control Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .code-font { font-family: 'JetBrains Mono', monospace; }
        .glass { background: rgba(18, 17, 36, 0.75); backdrop-filter: blur(16px); border: 1px solid rgba(139, 92, 246, 0.2); }
        .glass-card { background: rgba(27, 25, 56, 0.5); backdrop-filter: blur(12px); border: 1px solid rgba(168, 85, 247, 0.15); }
        #wallpaper-canvas { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: -1; background: #05050f; }
    </style>
</head>
<body class="text-gray-100 min-h-screen flex flex-col selection:bg-purple-500 selection:text-white">
    <canvas id="wallpaper-canvas"></canvas>
    <div id="app" class="flex h-screen overflow-hidden">
        <aside class="w-64 glass flex flex-col z-20 border-r border-purple-900/30">
            <div class="p-6 flex items-center space-x-3 border-b border-purple-900/30">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-cyan-400 flex items-center justify-center font-bold">GF</div>
                <div>
                    <h1 class="font-bold tracking-wider bg-gradient-to-r from-purple-400 to-cyan-400 bg-clip-text text-transparent">GANG FAMILY</h1>
                    <p class="text-xs text-purple-300/60 font-mono">DASHBOARD</p>
                </div>
            </div>
            <nav class="flex-1 px-4 py-6 space-y-2 overflow-y-auto">
                <button onclick="switchTab('overview')" id="nav-overview" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium bg-purple-600/20 text-purple-300 border border-purple-500/30"><span>Overview</span></button>
                <button onclick="switchTab('commands')" id="nav-commands" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>Bot Commands</span></button>
                
                {% if user and (user.is_owner or user.is_moderator) %}
                <div class="pt-4 pb-2"><p class="px-4 text-xs font-semibold text-purple-400/50 uppercase tracking-wider">Administration</p></div>
                <button onclick="switchTab('ai')" id="nav-ai" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>AI Settings</span></button>
                <button onclick="switchTab('welcome')" id="nav-welcome" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>Welcome Settings</span></button>
                {% endif %}

                {% if user and user.is_owner %}
                <button onclick="switchTab('moderators')" id="nav-moderators" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>Moderator Roster</span></button>
                <button onclick="switchTab('bans')" id="nav-bans" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>Access Bans</span></button>
                <button onclick="switchTab('audit')" id="nav-audit" class="w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-purple-900/20"><span>Audit Logs</span></button>
                {% endif %}
            </nav>
            <div class="p-4 border-t border-purple-900/30">
                {% if user %}
                <div class="flex items-center space-x-3 mb-3">
                    <img src="https://cdn.discordapp.com/avatars/{{ user.id }}/{{ user.avatar }}.png" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'" class="w-9 h-9 rounded-full border border-purple-500/40">
                    <div class="overflow-hidden">
                        <p class="text-sm font-semibold truncate text-gray-200">{{ user.username }}</p>
                        <p class="text-xs text-purple-400 font-mono">{% if user.is_owner %}👑 Owner{% elif user.is_moderator %}🛡️ Moderator{% else %}👤 Member{% endif %}</p>
                    </div>
                </div>
                <a href="/auth/logout" class="block text-center py-2 px-3 rounded-lg text-xs font-semibold bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20">Logout</a>
                {% else %}
                <a href="/auth/login" class="flex items-center justify-center py-2.5 px-4 rounded-xl text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30">Login with Discord</a>
                {% endif %}
            </div>
        </aside>
        <main class="flex-1 flex flex-col overflow-hidden">
            <header class="glass h-16 border-b border-purple-900/30 flex items-center justify-between px-8 z-10">
                <span id="current-tab-title" class="text-lg font-bold text-gray-200">Overview</span>
                <span class="px-3 py-1 rounded-full text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">● Bot ONLINE</span>
            </header>
            <div class="flex-1 overflow-y-auto p-8 relative">
                <!-- TAB: OVERVIEW -->
                <div id="tab-overview" class="space-y-6 max-w-6xl mx-auto">
                    <div class="glass-card p-6 rounded-2xl">
                        <h2 class="text-2xl font-bold bg-gradient-to-r from-purple-400 to-cyan-400 bg-clip-text text-transparent mb-2">Gang Family Portal</h2>
                        <p class="text-gray-300 text-sm">Welcome to the official control panel. Members can browse available bot commands freely. Owners and moderators can manage configurations and security rules.</p>
                    </div>
                </div>
                <!-- TAB: COMMANDS -->
                <div id="tab-commands" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl space-y-4">
                        <h3 class="text-xl font-bold text-white">Bot Commands Directory</h3>
                        <p class="text-xs text-gray-400">Complete listing of available Slash and Prefix commands loaded in the Gang Family bot.</p>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/play &lt;query&gt;</span><p class="text-xs text-gray-300 mt-1">Stream music or playlists from YouTube.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/skip / stop / pause / resume</span><p class="text-xs text-gray-300 mt-1">Control active music playback streams.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/volume &lt;percent&gt;</span><p class="text-xs text-gray-300 mt-1">Adjust player volume levels from 0% to 300%.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/anime / انمي</span><p class="text-xs text-gray-300 mt-1">Play the multi-language anime guessing game.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/top</span><p class="text-xs text-gray-300 mt-1">View the anime guessing points leaderboard.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/warn add / check</span><p class="text-xs text-gray-300 mt-1">Inspect warnings or issue official infraction records.</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">/ban / kick / timeout</span><p class="text-xs text-gray-300 mt-1">Server moderation suite (Admin/Mod permissions required).</p></div>
                            <div class="p-4 rounded-xl bg-purple-950/30 border border-purple-900/40"><span class="code-font text-cyan-400 font-bold">!dm &lt;user&gt; &lt;msg&gt;</span><p class="text-xs text-gray-300 mt-1">Send direct messages (Restricted to OldAges role).</p></div>
                        </div>
                    </div>
                </div>
                
                {% if user and (user.is_owner or user.is_moderator) %}
                <!-- TAB: AI -->
                <div id="tab-ai" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl">
                        <h3 class="text-xl font-bold text-white mb-4">AI Configuration</h3>
                        <form onsubmit="saveConfig(event, 'ai-form')" id="ai-form" class="space-y-4">
                            <div><label class="block text-xs font-semibold text-purple-300 uppercase mb-2">AI Enabled</label>
                            <select name="ai_enabled" class="w-full bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white"><option value="true">Enabled</option><option value="false">Disabled</option></select></div>
                            <div><label class="block text-xs font-semibold text-purple-300 uppercase mb-2">System Prompt</label>
                            <textarea name="ai_system_prompt" rows="3" class="w-full bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white">{{ config.ai_system_prompt }}</textarea></div>
                            <button type="submit" class="px-6 py-2.5 rounded-xl text-sm font-semibold bg-purple-600 hover:bg-purple-500 text-white">Save AI Settings</button>
                        </form>
                    </div>
                </div>
                <!-- TAB: WELCOME -->
                <div id="tab-welcome" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl">
                        <h3 class="text-xl font-bold text-white mb-4">Welcome Messages</h3>
                        <form onsubmit="saveConfig(event, 'welcome-form')" id="welcome-form" class="space-y-4">
                            <div><label class="block text-xs font-semibold text-purple-300 uppercase mb-2">Message Template</label>
                            <textarea name="welcome_message" rows="3" class="w-full bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white">{{ config.welcome_message }}</textarea></div>
                            <button type="submit" class="px-6 py-2.5 rounded-xl text-sm font-semibold bg-purple-600 hover:bg-purple-500 text-white">Save Welcome Settings</button>
                        </form>
                    </div>
                </div>
                {% endif %}

                {% if user and user.is_owner %}
                <!-- TAB: MODERATORS -->
                <div id="tab-moderators" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl">
                        <h3 class="text-xl font-bold text-white mb-4">Moderator Roster</h3>
                        <form onsubmit="addModerator(event)" class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                            <input type="text" id="mod-userid" placeholder="Discord User ID" required class="bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white code-font">
                            <input type="text" id="mod-username" placeholder="Username" required class="bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white">
                            <button type="submit" class="px-6 py-2.5 rounded-xl text-sm font-semibold bg-purple-600 hover:bg-purple-500 text-white">Add Moderator</button>
                        </form>
                        <table class="w-full text-left border-collapse">
                            <thead><tr class="border-b border-purple-900/40 text-xs text-purple-400 uppercase"><th class="py-3 px-4">User ID</th><th class="py-3 px-4">Username</th><th class="py-3 px-4 text-right">Action</th></tr></thead>
                            <tbody class="text-sm divide-y divide-purple-900/20">
                                {% for mod in mods %}
                                <tr><td class="py-3 px-4 code-font text-purple-300">{{ mod.user_id }}</td><td class="py-3 px-4 text-white">{{ mod.username }}</td><td class="py-3 px-4 text-right"><button onclick="removeModerator('{{ mod.user_id }}')" class="px-3 py-1 rounded text-xs bg-red-500/10 text-red-400">Revoke</button></td></tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
                <!-- TAB: BANS -->
                <div id="tab-bans" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl">
                        <h3 class="text-xl font-bold text-white mb-4">Bot Access Bans</h3>
                        <form onsubmit="addBan(event)" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                            <input type="text" id="ban-userid" placeholder="User ID" required class="bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white code-font">
                            <input type="text" id="ban-username" placeholder="Username" required class="bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white">
                            <input type="text" id="ban-reason" placeholder="Reason" required class="bg-purple-950/40 border border-purple-800/40 rounded-xl px-4 py-2.5 text-sm text-white">
                            <button type="submit" class="px-6 py-2.5 rounded-xl text-sm font-semibold bg-red-600 hover:bg-red-500 text-white">Ban</button>
                        </form>
                        <table class="w-full text-left border-collapse">
                            <thead><tr class="border-b border-purple-900/40 text-xs text-purple-400 uppercase"><th class="py-3 px-4">User ID</th><th class="py-3 px-4">Username</th><th class="py-3 px-4">Reason</th><th class="py-3 px-4 text-right">Action</th></tr></thead>
                            <tbody class="text-sm divide-y divide-purple-900/20">
                                {% for ban in bans %}
                                <tr><td class="py-3 px-4 code-font text-purple-300">{{ ban.user_id }}</td><td class="py-3 px-4 text-white">{{ ban.username }}</td><td class="py-3 px-4 text-gray-300">{{ ban.reason }}</td><td class="py-3 px-4 text-right"><button onclick="removeBan('{{ ban.user_id }}')" class="px-3 py-1 rounded text-xs bg-emerald-500/10 text-emerald-400">Unban</button></td></tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
                <!-- TAB: AUDIT LOGS -->
                <div id="tab-audit" class="space-y-6 max-w-6xl mx-auto hidden">
                    <div class="glass-card p-6 rounded-2xl">
                        <h3 class="text-xl font-bold text-white mb-4">Audit Logs</h3>
                        <div class="overflow-x-auto max-h-[400px]">
                            <table class="w-full text-left border-collapse text-xs">
                                <thead class="sticky top-0 bg-[#121124]"><tr class="border-b border-purple-900/40 text-purple-400 uppercase"><th class="py-2 px-3">Time</th><th class="py-2 px-3">User</th><th class="py-2 px-3">Action</th><th class="py-2 px-3">Details</th></tr></thead>
                                <tbody class="divide-y divide-purple-900/20">
                                    {% for log in audit_logs %}
                                    <tr><td class="py-2 px-3 code-font text-purple-300">{{ log.timestamp }}</td><td class="py-2 px-3 text-white">{{ log.username }}</td><td class="py-2 px-3 text-cyan-400">{{ log.action }}</td><td class="py-2 px-3 text-gray-300">{{ log.details }}</td></tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                {% endif %}
            </div>
        </main>
    </div>
    <script>
        function switchTab(tabId) {
            ['overview', 'commands', 'ai', 'welcome', 'moderators', 'bans', 'audit'].forEach(t => {
                const el = document.getElementById('tab-' + t);
                const nav = document.getElementById('nav-' + t);
                if (el) el.classList.add('hidden');
                if (nav) nav.classList.remove('bg-purple-600/20', 'text-purple-300', 'border', 'border-purple-500/30');
            });
            const targetEl = document.getElementById('tab-' + tabId);
            const targetNav = document.getElementById('nav-' + tabId);
            if (targetEl) targetEl.classList.remove('hidden');
            if (targetNav) targetNav.classList.add('bg-purple-600/20', 'text-purple-300', 'border', 'border-purple-500/30');
            const titles = { 'overview': 'Overview', 'commands': 'Bot Commands', 'ai': 'AI Configuration', 'welcome': 'Welcome Messages', 'moderators': 'Moderator Roster', 'bans': 'Access Bans', 'audit': 'Audit Logs' };
            document.getElementById('current-tab-title').innerText = titles[tabId] || 'Control Center';
        }
        async function saveConfig(event, formId) {
            event.preventDefault();
            const res = await fetch('/api/config', { method: 'POST', body: new FormData(document.getElementById(formId)) });
            if (res.ok) { alert('Saved successfully!'); location.reload(); } else { alert('Failed to save.'); }
        }
        async function addModerator(event) {
            event.preventDefault();
            const fd = new FormData(); fd.append('user_id', document.getElementById('mod-userid').value); fd.append('username', document.getElementById('mod-username').value);
            const res = await fetch('/api/moderators/add', { method: 'POST', body: fd });
            if (res.ok) location.reload();
        }
        async function removeModerator(uid) {
            if (!confirm('Revoke mod role?')) return;
            const fd = new FormData(); fd.append('user_id', uid);
            const res = await fetch('/api/moderators/remove', { method: 'POST', body: fd });
            if (res.ok) location.reload();
        }
        async function addBan(event) {
            event.preventDefault();
            const fd = new FormData(); fd.append('user_id', document.getElementById('ban-userid').value); fd.append('username', document.getElementById('ban-username').value); fd.append('reason', document.getElementById('ban-reason').value);
            const res = await fetch('/api/bans/add', { method: 'POST', body: fd });
            if (res.ok) location.reload();
        }
        async function removeBan(uid) {
            if (!confirm('Unban user?')) return;
            const fd = new FormData(); fd.append('user_id', uid);
            const res = await fetch('/api/bans/remove', { method: 'POST', body: fd });
            if (res.ok) location.reload();
        }
        // Animated background wallpaper
        const canvas = document.getElementById('wallpaper-canvas');
        const ctx = canvas.getContext('2d');
        let width = canvas.width = window.innerWidth, height = canvas.height = window.innerHeight;
        window.addEventListener('resize', () => { width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; });
        const particles = Array.from({length: 35}, () => ({ x: Math.random()*width, y: Math.random()*height, vx: (Math.random()-0.5)*0.5, vy: (Math.random()-0.5)*0.5, radius: Math.random()*2+1 }));
        function animate() {
            ctx.clearRect(0, 0, width, height);
            particles.forEach(p => {
                p.x += p.vx; p.y += p.vy;
                if (p.x < 0) p.x = width; if (p.x > width) p.x = 0;
                if (p.y < 0) p.y = height; if (p.y > height) p.y = 0;
                ctx.beginPath(); ctx.arc(p.x, p.y, p.radius, 0, Math.PI*2); ctx.fillStyle = '#8b5cf6'; ctx.fill();
            });
            requestAnimationFrame(animate);
        }
        animate();
    </script>
</body>
</html>
"""

from jinja2 import Template

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    user = get_current_user(request)
    config = {row["key"]: row["value"] for row in db_query("SELECT key, value FROM config", fetchall=True)}
    mods = db_query("SELECT * FROM moderators", fetchall=True)
    bans = db_query("SELECT * FROM bans", fetchall=True)
    audit_logs = db_query("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 50", fetchall=True)
    
    return Template(DASHBOARD_HTML).render(
        user=user, config=config, mods=mods, bans=bans, audit_logs=audit_logs, owner_id=OWNER_DISCORD_ID
    )

if __name__ == "__main__":
    uvicorn.run("nexus_dashboard:app", host="127.0.0.1", port=8000, reload=True)