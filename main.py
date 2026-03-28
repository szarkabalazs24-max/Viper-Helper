import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, json, datetime, os, re
from threading import Thread
from flask import Flask

# --- RAILWAY ÉLETBEN TARTÁS ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run_web(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# --- KONFIGURÁCIÓ ---
TOKEN = os.environ.get('DISCORD_TOKEN')
DATABASE = 'server_data.json'
BAD_WORDS = ["geci", "buzi", "kurva", "anyád", "fasz", "ge*i", "f*sz"] 
LINK_PATTERN = r"(https?://[^\s]+)"

class GlobalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        self.antispam = {}

    async def setup_hook(self):
        self.voice_tracker.start()
        await self.tree.sync()
        print("✅ Minden rendszer élesítve, parancsok szinkronizálva!")

bot = GlobalBot()

# --- ADATBÁZIS (Railway-biztos) ---
def load_db():
    if not os.path.exists(DATABASE): return {"users": {}, "history": {}, "stats": {}, "log_channel": None}
    with open(DATABASE, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except: return {"users": {}, "history": {}, "stats": {}, "log_channel": None}

def save_db(data):
    with open(DATABASE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- LOGGING FUNKCIÓ ---
async def send_log(guild, embed):
    db = load_db()
    channel_id = db.get("log_channel")
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel: await channel.send(embed=embed)

# --- AUTOMOD & AKTIVITÁS ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    
    # Automod (Csak nem moderátorokra)
    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        violation = None
        
        if any(word in content for word in BAD_WORDS): violation = "Káromkodás"
        elif re.search(LINK_PATTERN, content): violation = "Tiltott link"
        
        uid = message.author.id
        now = datetime.datetime.now()
        if uid not in bot.antispam: bot.antispam[uid] = []
        bot.antispam[uid].append(now)
        bot.antispam[uid] = [t for t in bot.antispam[uid] if (now - t).seconds < 5]
        if len(bot.antispam[uid]) > 5: violation = "Spamming"

        if violation:
            await message.delete()
            embed = discord.Embed(title="🛡️ Automod Intézkedés", color=0xFF9900, timestamp=discord.utils.utcnow())
            embed.add_field(name="Személy", value=message.author.mention)
            embed.add_field(name="Indok", value=violation)
            embed.set_footer(text="Üzenet törölve.")
            await message.channel.send(embed=embed, delete_after=5)
            await send_log(message.guild, embed)
            return

    # Munkaidő pontozás (15 üzenet = 1 pont)
    db = load_db()
    uid = str(message.author.id)
    if uid not in db["stats"]: db["stats"][uid] = {"points": 0.0, "msg_count": 0}
    db["stats"][uid]["msg_count"] += 1
    if db["stats"][uid]["msg_count"] >= 15:
        db["stats"][uid]["points"] += 1
        db["stats"][uid]["msg_count"] = 0
        save_db(db)

@tasks.loop(minutes=1)
async def voice_tracker():
    db = load_db()
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot and not member.voice.self_deaf and not member.voice.mute:
                    uid = str(member.id)
                    if uid not in db["stats"]: db["stats"][uid] = {"points": 0.0, "msg_count": 0}
                    db["stats"][uid]["points"] += 0.4
    save_db(db)

# --- MODERÁCIÓS PARANCSOK ---

@bot.tree.command(name="setup_logs", description="Beállítja a log csatornát")
@app_commands.checks.has_permissions(administrator=True)
async def setup_logs(interaction: discord.Interaction, csatorna: discord.TextChannel):
    db = load_db()
    db["log_channel"] = csatorna.id
    save_db(db)
    await interaction.response.send_message(f"✅ Log csatorna beállítva: {csatorna.mention}")

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag warnolása + Mute")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Nem büntethetsz feletted állót!", ephemeral=True)

    db = load_db()
    uid = str(tag.id)
    warn_id = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    db["users"][uid] = db["users"].get(uid, 0) + 1
    count = db["users"][uid]

    # Szankció logika
    dur = 10 if count <= 3 else (60 if count <= 5 else 1440)
    until = discord.utils.utcnow() + datetime.timedelta(minutes=dur)
    
    embed = discord.Embed(title="🛑 Figyelmeztetés", color=0xFF0000, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=tag.display_avatar.url)
    embed.add_field(name="👤 Tag", value=tag.mention, inline=True)
    embed.add_field(name="🛡️ Moderátor", value=interaction.user.mention, inline=True)
    embed.add_field(name="📝 Indok", value=f"```\n{indok}\n```", inline=False)
    embed.add_field(name="⚖️ Szankció", value=f"**{dur} perc némítás**", inline=True)
    embed.add_field(name="🆔 ID", value=f"`{warn_id}`", inline=True)
    embed.set_footer(text=f"{count}. figyelmeztetés")

    try: await tag.timeout(until, reason=indok)
    except: embed.add_field(name="Hiba", value="Nincs jogom némítani!", inline=False)

    db["history"][warn_id] = {"user_id": tag.id, "reason": indok, "mod": interaction.user.name}
    save_db(db)

    await interaction.response.send_message(embed=embed)
    await send_log(interaction.guild, embed)
    try: await tag.send(f"Figyelmeztetve lettél a(z) **{interaction.guild.name}** szerveren!", embed=embed)
    except: pass

@bot.tree.command(name="munkaido", description="📊 Moderátor aktivitás")
@app_commands.checks.has_permissions(moderate_members=True)
async def munkaido(interaction: discord.Interaction, tag: discord.Member):
    db = load_db()
    p = db["stats"].get(str(tag.id), {}).get("points", 0)
    target = 500 if p < 500 else 10000
    lvl = "Junior Moderator" if p < 500 else "Moderator"
    perc = min((p/target)*100, 100)
    bar = "🟦" * int(perc/10) + "⬜" * (10 - int(perc/10))

    embed = discord.Embed(title="📊 Munkaidő Statisztika", color=0x3498DB)
    embed.add_field(name="Név", value=tag.mention, inline=True)
    embed.add_field(name="Szint", value=lvl, inline=True)
    embed.add_field(name="Pontok", value=f"**{p:.1f}** / {target}", inline=False)
    embed.add_field(name=f"Haladás - {perc:.1f}%", value=bar, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="🧹 Üzenetek takarítása")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, mennyiseg: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=mennyiseg)
    await interaction.followup.send(f"✅ Törölve: **{len(deleted)}** üzenet.")

@bot.tree.command(name="unmute", description="🔊 Némítás feloldása")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, tag: discord.Member):
    await tag.timeout(None)
    await interaction.response.send_message(f"🔊 {tag.mention} némítása feloldva.")

@bot.tree.command(name="ban", description="🔨 Kitiltás")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, tag: discord.Member, indok: str):
    await tag.ban(reason=indok)
    await interaction.response.send_message(f"🔨 {tag} ki lett tiltva. Indok: {indok}")

# --- INDÍTÁS ---
if __name__ == "__main__":
    Thread(target=run_web).start()
    if TOKEN: bot.run(TOKEN)
    else: print("HIBA: Nincs DISCORD_TOKEN!")
              
