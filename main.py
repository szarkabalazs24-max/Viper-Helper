import discord
from discord import app_commands
from discord.ext import commands
import datetime
import time
import re
import uuid
import json
import os
from flask import Flask
from threading import Thread

# --- RAILWAY ANTI-CRASH SZERVER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is online!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- BEÁLLÍTÁSOK ---
TOKEN = os.environ.get("TOKEN", "A_TE_BOT_TOKENED")
PROFANITY_LIST = ["szó1", "szó2"] # Bővítsd a listát
LINK_PATTERN = r"(https?://\S+|www\.\S+)"

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        
        self.data_file = "data.json"
        self.load_data()
        self.active_vc = {}
        self.msg_track = {}

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
        await self.tree.sync()

bot = MyBot()

# --- MODERÁCIÓS SZŰRŐK ---

@bot.event
async def on_message(message):
    if message.author.bot or message.author.guild_permissions.manage_messages:
        await bot.process_commands(message)
        return

    content = message.content.lower()
    if any(word in content for word in PROFANITY_LIST) or re.search(LINK_PATTERN, content):
        await message.delete()
        emb = discord.Embed(description=f"⚠️ {message.author.mention}, a tartalom nem engedélyezett!", color=discord.Color.orange())
        await message.channel.send(embed=emb, delete_after=3)
        return

    now = time.time()
    bot.msg_track.setdefault(message.author.id, [])
    bot.msg_track[message.author.id] = [t for t in bot.msg_track[message.author.id] if now - t < 5]
    bot.msg_track[message.author.id].append(now)

    if len(bot.msg_track[message.author.id]) > 5:
        await message.delete()
        try:
            await message.author.timeout(datetime.timedelta(minutes=10), reason="Spam")
            emb = discord.Embed(title="🔇 Automata Némítás", description=f"{message.author.mention} 10 percre némítva (Spam).", color=discord.Color.red())
            await message.channel.send(embed=emb)
        except: pass
        return

    await bot.process_commands(message)

# --- VC MUNKAIDŐ MÉRÉS ---

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

# --- SLASH PARANCSOK ---

@bot.tree.command(name="mute", description="Tag némítása")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, tag: discord.Member, percek: int, indok: str = "Nincs megadva"):
    await tag.timeout(datetime.timedelta(minutes=percek), reason=indok)
    emb = discord.Embed(title="🔇 Felhasználó némítva", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Tag:", value=tag.mention, inline=True)
    emb.add_field(name="Időtartam:", value=f"{percek} perc", inline=True)
    emb.add_field(name="Moderátor:", value=interaction.user.mention, inline=False)
    emb.add_field(name="Indok:", value=indok)
    emb.set_thumbnail(url=tag.display_avatar.url)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmeztetes", description="Figyelmeztetés kiosztása")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    wid = str(uuid.uuid4())[:8]
    uid = str(tag.id)
    bot.warnings.setdefault(uid, {})[wid] = indok
    bot.save_data()
    emb = discord.Embed(title="⚠️ Figyelmeztetés", color=discord.Color.orange())
    emb.add_field(name="Tag:", value=tag.mention)
    emb.add_field(name="ID:", value=f"`{wid}`")
    emb.add_field(name="Indok:", value=indok)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmezteteslista", description="Összes figyelmeztetés")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_list(interaction: discord.Interaction, tag: discord.Member):
    warns = bot.warnings.get(str(tag.id), {})
    emb = discord.Embed(title=f"📋 Warnok: {tag.display_name}", color=discord.Color.blue())
    if not warns:
        emb.description = "Ennek a tagnak nincsenek figyelmeztetései."
    else:
        txt = ""
        for i, (wid, indok) in enumerate(warns.items(), 1):
            txt += f"**{i}.** ID: `{wid}`\n╰ Indok: {indok}\n"
        emb.description = txt
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="figyelmeztetestorles", description="Warn törlése ID alapján")
@app_commands.checks.has_permissions(moderate_members=True)
async def del_warn(interaction: discord.Interaction, tag: discord.Member, warning_id: str):
    uid = str(tag.id)
    if uid in bot.warnings and warning_id in bot.warnings[uid]:
        bot.warnings[uid].pop(warning_id)
        bot.save_data()
        emb = discord.Embed(description=f"✅ Sikeresen törölve: `{warning_id}` ({tag.mention})", color=discord.Color.green())
        await interaction.response.send_message(embed=emb)
    else:
        emb = discord.Embed(description="❌ Nem található ilyen ID.", color=discord.Color.red())
        await interaction.response.send_message(embed=emb, ephemeral=True)

@bot.tree.command(name="munkaido", description="Aktivitási statisztika")
@app_commands.checks.has_permissions(moderate_members=True)
async def worktime(interaction: discord.Interaction, tag: discord.Member):
    uid = str(tag.id)
    total = bot.work_data.get(uid, 0)
    if tag.id in bot.active_vc:
        total += (time.time() - bot.active_vc[tag.id]) * 0.4
    
    hours, minutes = int(total // 3600), int((total % 3600) // 60)
    emb = discord.Embed(title=f"🕒 Munkaidő: {tag.display_name}", color=0x2b2d31)
    emb.add_field(name="Időtartam (0.4x):", value=f"**{hours} óra {minutes} perc**")
    emb.add_field(name="Állapot:", value="🟢 Aktív" if tag.id in bot.active_vc else "⚪ Offline/Nem dolgozik")
    await interaction.response.send_message(embed=emb)

# --- INDÍTÁS ---
Thread(target=run_web).start()
bot.run(TOKEN)
              
