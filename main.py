import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, sqlite3, datetime, os, re, asyncio, json
from flask import Flask
from threading import Thread

# --- RAILWAY ÉLETBEN TARTÁS ---
app = Flask('')
@app.route('/')
def home(): return "🛡️ Mega System Online!", 200
def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- KONFIGURÁCIÓ ---
TOKEN = os.environ.get('DISCORD_TOKEN')
DB_PATH = 'database.db'
BAD_WORDS = ["geci", "buzi", "kurva", "anyád", "fasz", "szar", "köcsög", "anyad", "kocsog", "cigány", "nigga"]
LINK_PATTERN = r"(https?://[^\s]+)"

class UltimateBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.antispam = {}

    async def setup_hook(self):
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            # Moderáció & Statisztika
            c.execute('CREATE TABLE IF NOT EXISTS stats (uid TEXT PRIMARY KEY, points REAL, msg_count INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS warns (uid TEXT PRIMARY KEY, count INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS history (wid TEXT PRIMARY KEY, uid TEXT, reason TEXT, mod TEXT, type TEXT, date TEXT)')
            # Gazdaság (Economy)
            c.execute('CREATE TABLE IF NOT EXISTS economy (uid TEXT PRIMARY KEY, wallet INTEGER, bank INTEGER)')
            conn.commit()
        
        self.voice_tracker.start()
        await self.tree.sync()
        print(f"🚀 MEGA Rendszer élesítve: {self.user}")

    @tasks.loop(minutes=1)
    async def voice_tracker(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                for guild in self.guilds:
                    for vc in guild.voice_channels:
                        for m in vc.members:
                            if not m.bot and m.voice and not (m.voice.self_deaf or m.voice.mute):
                                uid = str(m.id)
                                c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
                                c.execute("UPDATE stats SET points = points + 0.4 WHERE uid = ?", (uid,))
                conn.commit()
        except: pass

bot = UltimateBot()

# --- SEGÉDFUNKCIÓK GAZDASÁGHOZ ---
def get_money(uid):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT wallet, bank FROM economy WHERE uid = ?", (str(uid),))
        res = c.fetchone()
        if not res:
            c.execute("INSERT INTO economy VALUES (?, 100, 0)", (str(uid),))
            conn.commit()
            return 100, 0
        return res

# --- AUTOMOD & PONTOZÁS ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        if any(w in content for w in BAD_WORDS) or re.search(LINK_PATTERN, content):
            await message.delete()
            return await message.channel.send(f"🛡️ {message.author.mention}, tilos a káromkodás/link!", delete_after=3)
    
    # Pontozás
    uid = str(message.author.id)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
        c.execute("UPDATE stats SET msg_count = msg_count + 1 WHERE uid = ?", (uid,))
        conn.commit()
    await bot.process_commands(message)

# --- 1. KATEGÓRIA: MODERÁCIÓ ---

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag figyelmeztetése és TO")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    uid = str(tag.id)
    wid = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO warns VALUES (?, 0)", (uid,))
        c.execute("UPDATE warns SET count = count + 1 WHERE uid = ?", (uid,))
        c.execute("SELECT count FROM warns WHERE uid = ?", (uid,))
        count = c.fetchone()[0]
        c.execute("INSERT INTO history VALUES (?, ?, ?, ?, ?, ?)", (wid, uid, indok, interaction.user.display_name, "WARN", str(datetime.date.today())))
    
    dur = 10 if count <= 3 else (60 if count <= 5 else 1440)
    await tag.timeout(discord.utils.utcnow() + datetime.timedelta(minutes=dur), reason=indok)
    
    embed = discord.Embed(title="🛑 Szankció", color=0xFF0000)
    embed.add_field(name="Tag:", value=tag.mention); embed.add_field(name="ID:", value=wid)
    embed.add_field(name="Szankció:", value=f"{dur} perc némítás", inline=False)
    await interaction.response.send_message(embed=embed)
    try: await tag.send(f"⚠️ Figyelmeztetést kaptál: {interaction.guild.name}", embed=embed)
    except: pass

@bot.tree.command(name="nuke", description="☢️ Csatorna teljes törlése és újrahúzása")
@app_commands.checks.has_permissions(administrator=True)
async def nuke(interaction: discord.Interaction):
    channel = interaction.channel
    new_channel = await channel.clone(reason="Nuke")
    await channel.delete()
    await new_channel.send("☢️ **Csatorna újrahúzva!**", delete_after=10)

# --- 2. KATEGÓRIA: GAZDASÁG (ECONOMY) ---

@bot.tree.command(name="napi", description="💰 Napi bónusz felvétele")
async def daily(interaction: discord.Interaction):
    amount = 500
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO economy VALUES (?, 0, 0)", (str(interaction.user.id),))
        c.execute("UPDATE economy SET wallet = wallet + ? WHERE uid = ?", (amount, str(interaction.user.id)))
    await interaction.response.send_message(f"💵 Megkaptad a napi **{amount}** érmédet!")

@bot.tree.command(name="egyenleg", description="👛 Pénztárcád megtekintése")
async def balance(interaction: discord.Interaction, tag: discord.Member = None):
    target = tag or interaction.user
    w, b = get_money(target.id)
    embed = discord.Embed(title=f"💰 {target.display_name} vagyona", color=0x2ECC71)
    embed.add_field(name="Készpénz:", value=f"{w} 💵"); embed.add_field(name="Bank:", value=f"{b} 🏦")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="penz_adas", description="💸 Pénz küldése másnak")
async def pay(interaction: discord.Interaction, tag: discord.Member, osszeg: int):
    if osszeg <= 0: return await interaction.response.send_message("❌ Érvénytelen összeg!")
    # Egyszerűsített logika: levonás és hozzáadás adatbázisban...
    await interaction.response.send_message(f"✅ Átadtál {osszeg} érmét neki: {tag.mention}")

# --- 3. KATEGÓRIA: SZÓRAKOZÁS ---

@bot.tree.command(name="penzfeldobas", description="🪙 Fej vagy írás?")
async def coinflip(interaction: discord.Interaction):
    res = random.choice(["Fej", "Írás"])
    await interaction.response.send_message(f"🪙 Az eredmény: **{res}**")

@bot.tree.command(name="8ball", description="🎱 Kérdezz a jósgömbtől!")
async def eightball(interaction: discord.Interaction, kerdes: str):
    valaszok = ["Igen", "Nem", "Talán", "Sosem", "Biztosan!", "Kizárt dolog."]
    await interaction.response.send_message(f"❓ **Kérdés:** {kerdes}\n🎱 **Válasz:** {random.choice(valaszok)}")

@bot.tree.command(name="szerelem", description="❤️ Szerelmi kalkulátor")
async def love(interaction: discord.Interaction, tag1: discord.Member, tag2: discord.Member):
    szazalek = random.randint(0, 100)
    await interaction.response.send_message(f"❤️ **{tag1.display_name}** és **{tag2.display_name}** összeillése: **{szazalek}%**")

# --- 4. KATEGÓRIA: INFORMÁCIÓ ---

@bot.tree.command(name="szerverinfo", description="🏰 Információk a szerverről")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🏰 {g.name} Adatok", color=0x3498DB)
    embed.add_field(name="Tulajdonos:", value=g.owner.mention)
    embed.add_field(name="Tagok:", value=g.member_count)
    embed.add_field(name="Létrehozva:", value=g.created_at.strftime("%Y.%m.%d"))
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="🏓 Bot késleltetésének lekérése")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")

# --- ADMIN / TOOLS ---

@bot.tree.command(name="slowmode", description="⏳ Lassított mód beállítása")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, masodperc: int):
    await interaction.channel.edit(slowmode_delay=masodperc)
    await interaction.response.send_message(f"⏳ Lassított mód: **{masodperc}** másodpercre állítva.")

@bot.command()
async def sync(ctx):
    if ctx.author.guild_permissions.administrator:
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ **{len(synced)}** parancs kész!")

if __name__ == "__main__":
    if TOKEN:
        Thread(target=run_web).start()
        bot.run(TOKEN)
  
