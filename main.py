import discord
from discord import app_commands
from discord.ext import commands
import datetime, time, re, uuid, json, os
from flask import Flask
from threading import Thread

# --- RAILWAY ANTI-CRASH ---
app = Flask('')
@app.route('/')
def home(): return "Bot is online!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- KONFIG ---
TOKEN = os.environ.get("TOKEN", "A_TE_BOT_TOKENED")
PROFANITY_LIST = ["szó1", "szó2"]
LINK_PATTERN = r"(https?://\S+|www\.\S+)"

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        # A prefix parancsokat csak a szinkronizáláshoz használjuk
        super().__init__(command_prefix="!", intents=intents)
        
        self.data_file = "data.json"
        self.active_vc = {}
        self.msg_track = {}
        self.load_data()

    def load_data(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                data = json.load(f)
                self.warnings = data.get("warnings", {})
                self.work_data = data.get("work_data", {})
        else:
            self.warnings = {}
            self.work_data = {}

    def save_data(self):
        with open(self.data_file, "w") as f:
            json.dump({"warnings": self.warnings, "work_data": self.work_data}, f)

    async def setup_hook(self):
        # Ez a rész felel az automatikus szinkronért globálisan
        await self.tree.sync()
        print("Globális parancsok szinkronizálása elküldve a Discordnak.")

bot = MyBot()

# --- AZONNALI SZINKRONIZÁLÁS PARANCS ---
@bot.command()
@commands.is_owner() # Csak te használhatod
async def sync(ctx):
    """Manuális parancsfrissítés: !sync"""
    await bot.tree.sync()
    await ctx.send(embed=discord.Embed(description="✅ Slash parancsok frissítve!", color=discord.Color.green()))

# --- MODERÁCIÓS SZŰRŐK ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    
    # Moderátor mentesség
    if message.author.guild_permissions.manage_messages:
        await bot.process_commands(message)
        return

    content = message.content.lower()
    if any(word in content for word in PROFANITY_LIST) or re.search(LINK_PATTERN, content):
        await message.delete()
        return

    # Spam szűrő (5 üzi / 5 mp)
    now = time.time()
    bot.msg_track.setdefault(message.author.id, [])
    bot.msg_track[message.author.id] = [t for t in bot.msg_track[message.author.id] if now - t < 5]
    bot.msg_track[message.author.id].append(now)

    if len(bot.msg_track[message.author.id]) > 5:
        await message.delete()
        try: await message.author.timeout(datetime.timedelta(minutes=10))
        except: pass
        return

    await bot.process_commands(message)

# --- VC MUNKAIDŐ ---
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    if before.channel is None and after.channel is not None:
        bot.active_vc[member.id] = time.time()
    elif before.channel is not None and after.channel is None:
        if member.id in bot.active_vc:
            duration = (time.time() - bot.active_vc[member.id]) * 0.4
            bot.work_data[uid] = bot.work_data.get(uid, 0) + duration
            del bot.active_vc[member.id]
            bot.save_data()

# --- SLASH PARANCSOK (EMBED) ---

@bot.tree.command(name="mute", description="Tag némítása")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, tag: discord.Member, percek: int, indok: str = "Nincs megadva"):
    await tag.timeout(datetime.timedelta(minutes=percek), reason=indok)
    emb = discord.Embed(title="🔇 Némítás", color=discord.Color.red())
    emb.add_field(name="Tag:", value=tag.mention).add_field(name="Idő:", value=f"{percek} perc")
    emb.add_field(name="Moderátor:", value=interaction.user.mention, inline=False)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmeztetes", description="Warn adása")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    wid, uid = str(uuid.uuid4())[:8], str(tag.id)
    bot.warnings.setdefault(uid, {})[wid] = indok
    bot.save_data()
    emb = discord.Embed(title="⚠️ Warn", color=discord.Color.orange())
    emb.add_field(name="Tag:", value=tag.mention).add_field(name="ID:", value=f"`{wid}`")
    emb.add_field(name="Indok:", value=indok, inline=False)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmezteteslista", description="Warnok listázása")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_list(interaction: discord.Interaction, tag: discord.Member):
    warns = bot.warnings.get(str(tag.id), {})
    emb = discord.Embed(title=f"📋 {tag.name} warnjai", color=discord.Color.blue())
    emb.description = "\n".join([f"`{wid}`: {indok}" for wid, indok in warns.items()]) if warns else "Nincs warn."
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmeztetestorles", description="Warn törlése")
@app_commands.checks.has_permissions(moderate_members=True)
async def del_warn(interaction: discord.Interaction, tag: discord.Member, warning_id: str):
    uid = str(tag.id)
    if uid in bot.warnings and warning_id in bot.warnings[uid]:
        bot.warnings[uid].pop(warning_id); bot.save_data()
        await interaction.response.send_message(embed=discord.Embed(description=f"✅ `{warning_id}` törölve.", color=discord.Color.green()))
    else:
        await interaction.response.send_message(embed=discord.Embed(description="❌ Rossz ID.", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="munkaido", description="Munkaidő lekérése")
@app_commands.checks.has_permissions(moderate_members=True)
async def worktime(interaction: discord.Interaction, tag: discord.Member):
    total = bot.work_data.get(str(tag.id), 0)
    if tag.id in bot.active_vc: total += (time.time() - bot.active_vc[tag.id]) * 0.4
    h, m = int(total // 3600), int((total % 3600) // 60)
    emb = discord.Embed(title=f"🕒 Munkaidő: {tag.name}", color=0x2b2d31)
    emb.add_field(name="Összesen (0.4x):", value=f"**{h} óra {m} perc**")
    await interaction.response.send_message(embed=emb)

# --- RUN ---
Thread(target=run_web).start()
bot.run(TOKEN)
