import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, sqlite3, datetime, os, re
from flask import Flask
from threading import Thread

# --- RAILWAY ÉLETBEN TARTÁS ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!", 200
def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- KONFIGURÁCIÓ ---
TOKEN = os.environ.get('DISCORD_TOKEN')
DB_PATH = 'database.db' 
BAD_WORDS = ["geci", "buzi", "kurva", "anyád", "fasz", "szar", "köcsög"]
LINK_PATTERN = r"(https?://[^\s]+)"

class UltimateBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.antispam = {}

    async def setup_hook(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stats (uid TEXT PRIMARY KEY, points REAL, msg_count INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS warns (uid TEXT PRIMARY KEY, count INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS history (wid TEXT PRIMARY KEY, uid TEXT, reason TEXT, mod TEXT)')
        conn.commit()
        conn.close()
        self.voice_tracker.start()
        await self.tree.sync()
        print(f"✅ Bejelentkezve: {self.user}")

bot = UltimateBot()

# --- MANUÁLIS SZINKRONIZÁLÁS (EMBEDDEL) ---
@bot.command()
async def sync(ctx):
    if ctx.author.guild_permissions.administrator:
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        embed = discord.Embed(title="🔄 Rendszer Frissítés", description=f"Sikeresen szinkronizálva: **{len(synced)}** slash parancs!", color=0x2ECC71)
        await ctx.send(embed=embed)

# --- AUTOMOD & PONTOZÁS ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return

    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        violation = None
        if any(w in content for w in BAD_WORDS): violation = "Káromkodás"
        elif re.search(LINK_PATTERN, content): violation = "Tiltott link"
        
        uid_int = message.author.id
        now = datetime.datetime.now()
        if uid_int not in bot.antispam: bot.antispam[uid_int] = []
        bot.antispam[uid_int] = [t for t in bot.antispam[uid_int] if (now - t).seconds < 5]
        bot.antispam[uid_int].append(now)
        if len(bot.antispam[uid_int]) > 5: violation = "Spamming"

        if violation:
            await message.delete()
            embed = discord.Embed(title="🛡️ Automatikus Moderáció", description=f"{message.author.mention}, szabályszegést észleltem!", color=0xE74C3C)
            embed.add_field(name="🚫 Indok", value=violation)
            await message.channel.send(embed=embed, delete_after=5)
            return

    uid = str(message.author.id)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
    c.execute("UPDATE stats SET msg_count = msg_count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT msg_count FROM stats WHERE uid = ?", (uid,))
    res = c.fetchone()
    if res and res[0] >= 15:
        c.execute("UPDATE stats SET points = points + 1, msg_count = 0 WHERE uid = ?", (uid,))
    conn.commit(); conn.close()
    await bot.process_commands(message)

# --- VOICE TRACKER ---
@tasks.loop(minutes=1)
async def voice_tracker():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for m in vc.members:
                if not m.bot and m.voice and not m.voice.self_deaf and not m.voice.mute:
                    uid = str(m.id)
                    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
                    c.execute("UPDATE stats SET points = points + 0.4 WHERE uid = ?", (uid,))
    conn.commit(); conn.close()

# --- SLASH PARANCSOK (MINDEGYIK EMBED) ---

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag figyelmeztetése")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Hiba: Rangsor!", ephemeral=True)
    
    uid = str(tag.id)
    wid = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO warns VALUES (?, 0)", (uid,))
    c.execute("UPDATE warns SET count = count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT count FROM warns WHERE uid = ?", (uid,))
    count = c.fetchone()[0]
    c.execute("INSERT INTO history VALUES (?, ?, ?, ?)", (wid, uid, indok, interaction.user.name))
    conn.commit(); conn.close()

    dur = 10 if count <= 3 else (60 if count <= 5 else 1440)
    until = discord.utils.utcnow() + datetime.timedelta(minutes=dur)
    
    embed = discord.Embed(title="🛑 Szankció Kiosztva", color=0xFF2D2D, timestamp=discord.utils.utcnow())
    embed.add_field(name="👤 Felhasználó", value=tag.mention, inline=True)
    embed.add_field(name="🛡️ Moderátor", value=interaction.user.mention, inline=True)
    embed.add_field(name="📝 Indok", value=f"```\n{indok}\n```", inline=False)
    embed.add_field(name="⚖️ Büntetés", value=f"{dur} perc némítás", inline=True)
    embed.set_footer(text=f"ID: {wid} | Összes figyelmeztetés: {count}")

    try: await tag.timeout(until, reason=indok)
    except: pass
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="munkaido", description="📊 Moderátori statisztika")
async def munkaido(interaction: discord.Interaction, tag: discord.Member):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT points FROM stats WHERE uid = ?", (str(tag.id),))
    res = c.fetchone()
    p = res[0] if res else 0.0
    conn.close()

    embed = discord.Embed(title="📊 Statisztika", color=0x3498DB)
    embed.set_thumbnail(url=tag.display_avatar.url)
    embed.add_field(name="👤 Név", value=tag.mention)
    embed.add_field(name="✨ Összpontszám", value=f"**{p:.1f}** pont", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="🧹 Üzenetek törlése")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, mennyiseg: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=mennyiseg)
    embed = discord.Embed(title="🧹 Takarítás", description=f"Sikeresen törölve: **{len(deleted)}** üzenet.", color=0x9B59B6)
    await interaction.followup.send(embed=embed)

if __name__ == "__main__":
    if TOKEN:
        Thread(target=run_web).start()
        bot.run(TOKEN)
