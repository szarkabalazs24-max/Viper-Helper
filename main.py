import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, sqlite3, datetime, os, re
from flask import Flask
from threading import Thread

# --- RAILWAY ÉLETBEN TARTÓ SZERVER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!", 200
def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- BOT BEÁLLÍTÁSOK ---
TOKEN = os.environ.get('DISCORD_TOKEN')
BAD_WORDS = ["geci", "buzi", "kurva", "anyád", "fasz", "szar", "köcsög"]
LINK_PATTERN = r"(https?://[^\s]+)"

class UltimateModeratorBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.antispam = {}

    async def setup_hook(self):
        # ADATBÁZIS INICIALIZÁLÁSA (SQLite a stabilitásért)
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stats (uid TEXT PRIMARY KEY, points REAL, msg_count INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS warns (uid TEXT PRIMARY KEY, count INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS history (wid TEXT PRIMARY KEY, uid TEXT, reason TEXT, mod TEXT)')
        conn.commit()
        conn.close()
        
        self.voice_tracker.start() # Voice aktivitás indítása
        await self.tree.sync()
        print(f"✅ {self.user} bejelentkezve és szinkronizálva!")

bot = UltimateModeratorBot()

# --- AUTOMOD & ÜZENET AKTIVITÁS ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return

    # AUTOMOD (Csak ha nem moderátor)
    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        violation = None
        v_emoji = "🛡️"
        v_color = 0xFFAA00

        # Káromkodás szűrő
        if any(word in content for word in BAD_WORDS):
            violation, v_emoji, v_color = "Káromkodás", "🤬", 0xE74C3C
        # Link szűrő
        elif re.search(LINK_PATTERN, content):
            violation, v_emoji, v_color = "Tiltott link", "🔗", 0x3498DB
        # Spam szűrő (5 üzenet / 5 mp)
        uid_int = message.author.id
        now = datetime.datetime.now()
        if uid_int not in bot.antispam: bot.antispam[uid_int] = []
        bot.antispam[uid_int].append(now)
        bot.antispam[uid_int] = [t for t in bot.antispam[uid_int] if (now - t).seconds < 5]
        if len(bot.antispam[uid_int]) > 5:
            violation, v_emoji, v_color = "Spamming", "🚀", 0x9B59B6

        if violation:
            await message.delete()
            embed = discord.Embed(title=f"{v_emoji} Automatikus Moderáció", color=v_color, timestamp=discord.utils.utcnow())
            embed.set_author(name="Biztonsági Felügyelet", icon_url=bot.user.display_avatar.url)
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.add_field(name="👤 Felhasználó", value=message.author.mention, inline=True)
            embed.add_field(name="🚫 Indok", value=f"**{violation}**", inline=True)
            embed.set_footer(text="Az üzeneted törlésre került.")
            return await message.channel.send(embed=embed, delete_after=5)

    # AKTIVITÁS PONTOZÁS (15 üzenet = 1 pont)
    uid = str(message.author.id)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
    c.execute("UPDATE stats SET msg_count = msg_count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT msg_count FROM stats WHERE uid = ?", (uid,))
    res = c.fetchone()
    if res and res[0] >= 15:
        c.execute("UPDATE stats SET points = points + 1, msg_count = 0 WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()

# --- VOICE AKTIVITÁS (0.4 szorzó percenként) ---
@tasks.loop(minutes=1)
async def voice_tracker():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for m in vc.members:
                if not m.bot and not m.voice.self_deaf and not m.voice.mute:
                    uid = str(m.id)
                    c.execute("INSERT OR IGNORE INTO stats VALUES (?, 0, 0)", (uid,))
                    c.execute("UPDATE stats SET points = points + 0.4 WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()

# --- MODERÁCIÓS PARANCSOK ---

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag figyelmeztetése és némítása")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Magasabb rangút nem büntethetsz!", ephemeral=True)

    uid = str(tag.id)
    # TO- + 5 karakteres ID generálása
    wid = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO warns VALUES (?, 0)", (uid,))
    c.execute("UPDATE warns SET count = count + 1 WHERE uid = ?", (uid,))
    c.execute("SELECT count FROM warns WHERE uid = ?", (uid,))
    count = c.fetchone()[0]
    c.execute("INSERT INTO history VALUES (?, ?, ?, ?)", (wid, uid, indok, interaction.user.name))
    conn.commit()
    conn.close()

    # SZANKCIÓ LOGIKA (1-3: 10p, 4-5: 1ó, 6+: 1nap)
    if count <= 3: dur, text = 10, "10 perc némítás"
    elif count <= 5: dur, text = 60, "1 óra némítás"
    else: dur, text = 1440, "1 napos némítás"

    until = discord.utils.utcnow() + datetime.timedelta(minutes=dur)
    
    embed = discord.Embed(title="🛑 Szankció Kiosztva", color=0xFF2D2D, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=tag.display_avatar.url)
    embed.add_field(name="👤 Figyelmeztetve:", value=tag.mention, inline=True)
    embed.add_field(name="🛡️ Intézkedett:", value=interaction.user.mention, inline=True)
    embed.add_field(name="📝 Indok:", value=f"```\n{indok}\n```", inline=False)
    embed.add_field(name="⚖️ Szankció:", value=f"**{text}**", inline=True)
    embed.add_field(name="🆔 Figyelmeztetés ID:", value=f"`{wid}`", inline=True)
    embed.set_footer(text=f"Ez a felhasználó {count}. figyelmeztetése.")

    try: await tag.timeout(until, reason=indok)
    except: pass
    
    await interaction.response.send_message(embed=embed)
    try: await tag.send(f"Figyelmeztetést kaptál a(z) **{interaction.guild.name}** szerveren!", embed=embed)
    except: pass

@bot.tree.command(name="figyelmeztetestorles", description="✅ Figyelmeztetés törlése ID alapján")
@app_commands.checks.has_permissions(moderate_members=True)
async def remove_warn(interaction: discord.Interaction, tag: discord.Member, warn_id: str, indok: str):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT wid FROM history WHERE wid = ? AND uid = ?", (warn_id, str(tag.id)))
    if not c.fetchone():
        conn.close()
        return await interaction.response.send_message("❌ Érvénytelen ID vagy nem ehhez a taghoz tartozik!", ephemeral=True)

    c.execute("DELETE FROM history WHERE wid = ?", (warn_id,))
    c.execute("UPDATE warns SET count = count - 1 WHERE uid = ? AND count > 0", (str(tag.id),))
    conn.commit()
    conn.close()

    embed = discord.Embed(title="✅ Figyelmeztetés Törölve", color=0x2ecc71)
    embed.add_field(name="Tag", value=tag.mention)
    embed.add_field(name="Törölt ID", value=f"`{warn_id}`")
    embed.add_field(name="Indok", value=indok)
    await interaction.response.send_message(embed=embed)
    try: await tag.timeout(None); await tag.send(f"Egy figyelmeztetésedet törölték!", embed=embed)
    except: pass

@bot.tree.command(name="munkaido", description="📊 Moderátori pontok és haladás")
@app_commands.checks.has_permissions(moderate_members=True)
async def munkaido(interaction: discord.Interaction, tag: discord.Member):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT points FROM stats WHERE uid = ?", (str(tag.id),))
    res = c.fetchone()
    p = res[0] if res else 0.0
    conn.close()

    # SZINTEK: 1. szint: 500 pont, 2. szint: 10000 pont
    if p < 500: target, lvl = 500, "Junior Moderator (1. szint)"
    else: target, lvl = 10000, "Moderator (2. szint)"
    
    perc = min((p / target) * 100, 100)
    bar = "🟦" * int(perc/10) + "⬜" * (10 - int(perc/10))

    embed = discord.Embed(title="📊 Aktivitási Adatlap", color=0x3498DB, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=tag.display_avatar.url)
    embed.add_field(name="👤 Név", value=tag.mention, inline=True)
    embed.add_field(name="🎖️ Szint", value=f"`{lvl}`", inline=True)
    embed.add_field(name="✨ Összpontszám", value=f"**{p:.1f}** / {target} pont", inline=False)
    embed.add_field(name=f"📈 Haladás - {perc:.1f}%", value=f"{bar}", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="🧹 Üzenetek törlése")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, mennyiseg: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=mennyiseg)
    await interaction.followup.send(f"✅ Törölve: **{len(deleted)}** üzenet.")

# --- INDÍTÁS ---
if __name__ == "__main__":
    Thread(target=run_web).start()
    if TOKEN: bot.run(TOKEN)
      
