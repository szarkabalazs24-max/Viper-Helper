import discord
from discord import app_commands
from discord.ext import commands
import datetime
import time
import re
import uuid

# --- BEÁLLÍTÁSOK ---
TOKEN = "A_TE_BOT_TOKENED"
PROFANITY_LIST = ["káromkodás1", "rosszszo2"] # Ide írd a tiltott szavakat
LINK_PATTERN = r"(https?://\S+|www\.\S+)"

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        
        # Adattárolók (Memóriában tárolva)
        self.warnings = {}      # {user_id: {warn_id: indok}}
        self.work_data = {}     # {user_id: osszes_masodperc}
        self.active_vc = {}     # {user_id: belepesi_ido}
        self.msg_track = {}     # {user_id: [idopontok]}

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Slash parancsok szinkronizálva!")

bot = MyBot()

# --- ESEMÉNYEK ÉS SZŰRŐK ---

@bot.event
async def on_ready():
    print(f"Bejelentkezve: {bot.user.name}")

@bot.event
async def on_voice_state_update(member, before, after):
    # Belépés VC-be
    if before.channel is None and after.channel is not None:
        bot.active_vc[member.id] = time.time()
    
    # Kilépés VC-ből
    elif before.channel is not None and after.channel is None:
        if member.id in bot.active_vc:
            duration = time.time() - bot.active_vc[member.id]
            # 0.4x szorzó alkalmazása
            adjusted_time = duration * 0.4
            bot.work_data[member.id] = bot.work_data.get(member.id, 0) + adjusted_time
            del bot.active_vc[member.id]

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # MODERÁTOR MENTESSÉG: Ha van üzenetkezelési joga, átugorja a szűrőket
    if message.author.guild_permissions.manage_messages:
        await bot.process_commands(message)
        return

    author = message.author
    content = message.content.lower()
    now = time.time()

    # 1. KÁROMKODÁS SZŰRŐ
    if any(word in content for word in PROFANITY_LIST):
        await message.delete()
        await message.channel.send(f"⚠️ {author.mention}, kérlek figyelj a stílusodra!", delete_after=3)
        return

    # 2. LINK SZŰRŐ
    if re.search(LINK_PATTERN, content):
        await message.delete()
        await message.channel.send(f"🚫 {author.mention}, ezen a szerveren tilos a linkelés!", delete_after=3)
        return

    # 3. SPAM SZŰRŐ (5 üzenet / 5 mp)
    bot.msg_track.setdefault(author.id, [])
    bot.msg_track[author.id] = [t for t in bot.msg_track[author.id] if now - t < 5]
    bot.msg_track[author.id].append(now)

    if len(bot.msg_track[author.id]) > 5:
        await message.delete()
        try:
            await author.timeout(datetime.timedelta(minutes=10), reason="Spam")
            await message.channel.send(f"🔇 {author.mention} némítva lett 10 percre spam miatt!")
        except:
            pass
        return

    await bot.process_commands(message)

# --- MODERÁCIÓS PARANCSOK ---

# 1. NÉMÍTÁS (MUTE)
@bot.tree.command(name="mute", description="Tag némítása megadott időre")
@app_commands.describe(tag="A tag", percek="Hány percre?", indok="Miért?")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, tag: discord.Member, percek: int, indok: str = "Nincs megadva"):
    duration = datetime.timedelta(minutes=percek)
    try:
        await tag.timeout(duration, reason=indok)
        embed = discord.Embed(title="🔇 Némítás", color=discord.Color.red(), timestamp=datetime.datetime.now())
        embed.add_field(name="Felhasználó:", value=tag.mention, inline=True)
        embed.add_field(name="Időtartam:", value=f"{percek} perc", inline=True)
        embed.add_field(name="Moderátor:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Indok:", value=indok, inline=False)
        embed.set_thumbnail(url=tag.display_avatar.url)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"Hiba: {e}", ephemeral=True)

# 2. FIGYELMEZTETÉS ADÁSA (Segédparancs az ID generáláshoz)
@bot.tree.command(name="figyelmeztetes", description="Figyelmeztetés adása egy tagnak")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str):
    warn_id = str(uuid.uuid4())[:8] # Rövid egyedi ID
    bot.warnings.setdefault(tag.id, {})[warn_id] = indok
    
    embed = discord.Embed(title="⚠️ Figyelmeztetés", color=discord.Color.orange())
    embed.add_field(name="Tag:", value=tag.mention, inline=True)
    embed.add_field(name="ID:", value=f"`{warn_id}`", inline=True)
    embed.add_field(name="Indok:", value=indok, inline=False)
    await interaction.response.send_message(embed=embed)

# 3. FIGYELMEZTETÉS LISTA
@bot.tree.command(name="figyelmezteteslista", description="Ki listázza a tag összes figyelmeztetését!")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_list(interaction: discord.Interaction, tag: discord.Member):
    user_warns = bot.warnings.get(tag.id, {})
    if not user_warns:
        await interaction.response.send_message(f"✅ {tag.mention}-nak nincsenek figyelmeztetései.", ephemeral=True)
        return

    embed = discord.Embed(title=f"📋 Listázva: {tag.display_name}", color=discord.Color.gold())
    list_text = ""
    for i, (wid, reason) in enumerate(user_warns.items(), 1):
        list_text += f"**{i}.** ID: `{wid}` | Indok: {reason}\n"
    
    embed.add_field(name="Figyelmeztetések:", value=list_text)
    await interaction.response.send_message(embed=embed)

# 4. FIGYELMEZTETÉS TÖRLÉSE (INDOK NÉLKÜL)
@bot.tree.command(name="figyelmeztetestorles", description="Törli a tagról a figyelmeztetést!")
@app_commands.checks.has_permissions(moderate_members=True)
async def del_warn(interaction: discord.Interaction, tag: discord.Member, warning_id: str):
    if tag.id in bot.warnings and warning_id in bot.warnings[tag.id]:
        bot.warnings[tag.id].pop(warning_id)
        embed = discord.Embed(title="🗑️ Törölve", description=f"ID: `{warning_id}` eltávolítva {tag.mention} profiljáról.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("❌ Nincs ilyen ID-vel figyelmeztetés.", ephemeral=True)

# 5. MUNKAIDŐ
@bot.tree.command(name="munkaido", description="Megmutatja az aktivitásod/munkaidődet!")
@app_commands.checks.has_permissions(moderate_members=True)
async def worktime(interaction: discord.Interaction, tag: discord.Member):
    total_sec = bot.work_data.get(tag.id, 0)
    
    # Ha most is VC-ben van
    if tag.id in bot.active_vc:
        total_sec += (time.time() - bot.active_vc[tag.id]) * 0.4

    hours = int(total_sec // 3600)
    minutes = int((total_sec % 3600) // 60)
    
    status = "🔴 Inaktív"
    if total_sec > 18000: status = "🔥 Nagyon aktív"
    elif total_sec > 0: status = "🟢 Aktív"

    embed = discord.Embed(title=f"🕒 Munkaidő: {tag.display_name}", color=discord.Color.blue())
    embed.add_field(name="Idő (0.4x VC szorzóval):", value=f"{hours} óra {minutes} perc", inline=False)
    embed.add_field(name="Aktivitás:", value=status, inline=True)
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
