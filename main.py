import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, sqlite3, datetime, os, re
from threading import Thread
from flask import Flask

# --- RAILWAY STABILITÁS (Webszerver a port figyeléshez) ---
app = Flask('')
@app.route('/')
def health_check(): return "Bot is Online", 200

def run_web():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- ADATBÁZIS KEZELÉS (SQLite - SOKKAL STABILABB) ---
DB_PATH = 'data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats (uid TEXT PRIMARY KEY, points REAL, msg_count INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS warns (uid TEXT, count INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (wid TEXT PRIMARY KEY, uid TEXT, reason TEXT, mod TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

# --- BOT BEÁLLÍTÁSOK ---
TOKEN = os.environ.get('DISCORD_TOKEN')
BAD_WORDS = ["geci", "buzi", "kurva", "anyád", "fasz"]

class RailwayBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.antispam = {}

    async def setup_hook(self):
        init_db()
        self.voice_tracker.start()
        await self.tree.sync()
        print(f"✅ Bot bejelentkezve: {self.user}")

bot = RailwayBot()

# --- AUTOMOD & AKTIVITÁS ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    # Automod (Kivéve moderátorok)
    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        if any(word in content for word in BAD_WORDS) or re.search(r"(https?://[^\s]+)", content):
            try:
                await message.delete()
                embed = discord.Embed(title="🛡️ Biztonsági Szűrő", description=f"{message.author.mention}, szabályszegést észleltem!", color=0xFF9900)
                return await message.channel.send(embed=embed, delete_after=5)
            except: pass

    # Pontozás (15 üzenet = 1 pont)
    uid = str(message.author.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
    c.execute("UPDATE stats SET msg_count = msg_count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT msg_count FROM stats WHERE uid = ?", (uid,))
    if c.fetchone()[0] >= 15:
        c.execute("UPDATE stats SET points = points + 1, msg_count = 0 WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()

@tasks.loop(minutes=1)
async def voice_tracker():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for m in vc.members:
                if not m.bot and not m.voice.self_deaf:
                    uid = str(m.id)
                    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
                    c.execute("UPDATE stats SET points = points + 0.4 WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()

# --- MODERÁCIÓS PARANCSOK ---

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag warnolása + Auto Mute")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Magasabb rangút nem büntethetsz!", ephemeral=True)

    uid = str(tag.id)
    wid = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO warns VALUES (?, 0)", (uid,))
    c.execute("UPDATE warns SET count = count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT count FROM warns WHERE uid = ?", (uid,))
    count = c.fetchone()[0]
    c.execute("INSERT INTO history VALUES (?, ?, ?, ?)", (wid, uid, indok, interaction.user.name))
    conn.commit()
    conn.close()

    dur = 10 if count <= 3 else (60 if count <= 5 else 1440)
    until = discord.utils.utcnow() + datetime.timedelta(minutes=dur)
    
    embed = discord.Embed(title="🛑 Szankció", color=0xFF0000, timestamp=discord.utils.utcnow())
    embed.add_field(name="Személy", value=tag.mention, inline=True)
    embed.add_field(name="Szankció", value=f"{dur} perc némítás", inline=True)
    embed.add_field(name="ID", value=f"`{wid}`", inline=True)
    embed.add_field(name="Indok", value=f"```\n{indok}\n```", inline=False)
    embed.set_footer(text=f"{count}. figyelmeztetés")

    try: await tag.timeout(until, reason=indok)
    except: pass
    
    await interaction.response.send_message(embed=embed)
    try: await tag.send(embed=embed)
    except: pass

@bot.tree.command(name="munkaido", description="📊 Aktivitás lekérése")
@app_commands.checks.has_permissions(moderate_members=True)
async def munkaido(interaction: discord.Interaction, tag: discord.Member):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points FROM stats WHERE uid = ?", (str(tag.id),))
    res = c.fetchone()
    p = res[0] if res else 0
    conn.close()

    target = 500 if p < 500 else 10000
    perc = min((p/target)*100, 100)
    bar = "🟦" * int(perc/10) + "⬜" * (10 - int(perc/10))

    embed = discord.Embed(title="📊 Munkaidő", color=0x3498DB)
    embed.add_field(name="Tag", value=tag.mention)
    embed.add_field(name="Pontok", value=f"**{p:.1f}** / {target}")
    embed.add_field(name=f"Haladás ({perc:.1f}%)", value=bar, inline=False)
    await interaction.response.send_message(embed=embed)

# További parancsok (Clear, Ban) ugyanígy...
@bot.tree.command(name="clear", description="🧹 Takarítás")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, mennyiseg: int):
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=mennyiseg)
    await interaction.followup.send(f"✅ {mennyiseg} üzenet törölve.")

# --- INDÍTÁS ---
if __name__ == "__main__":
    # Webszerver indítása
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # Bot indítása
    if TOKEN:
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"FATAL ERROR: {e}")
    else:
        print("❌ Nincs TOKEN megadva!")
      
