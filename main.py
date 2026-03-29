import discord
from discord import app_commands
from discord.ext import commands, tasks
import random, string, sqlite3, datetime, os, re, asyncio
from flask import Flask
from threading import Thread

# --- RAILWAY ÉLETBEN TARTÁS ---
app = Flask('')
@app.route('/')
def home(): return "🛡️ Ultimate Elite Guard System Online!", 200
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
            c.execute('CREATE TABLE IF NOT EXISTS warns (uid TEXT PRIMARY KEY, count INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS history (wid TEXT PRIMARY KEY, uid TEXT, reason TEXT, mod TEXT, date TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS suspended_users (uid TEXT PRIMARY KEY, roles TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS settings (guild_id TEXT PRIMARY KEY, welcome_ch TEXT, welcome_msg TEXT, leave_ch TEXT, leave_msg TEXT, autorole_id TEXT)')
            conn.commit()
        await self.tree.sync()
        print(f"✅ Minden rendszer élesítve: {self.user}")

bot = UltimateBot()

# --- ESEMÉNYEK: ÜDVÖZLŐ, KILÉPŐ, AUTOROLE ---

@bot.event
async def on_member_join(member):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT welcome_ch, welcome_msg, autorole_id FROM settings WHERE guild_id = ?", (str(member.guild.id),))
        res = c.fetchone()
    
    if res:
        welcome_ch, welcome_msg, autorole_id = res
        # AutoRole kiosztása
        if autorole_id:
            role = member.guild.get_role(int(autorole_id))
            if role: 
                try: await member.add_roles(role)
                except: pass
        
        # Sima szöveges üdvözlő (NEM Embed)
        if welcome_ch and welcome_msg:
            channel = member.guild.get_channel(int(welcome_ch))
            if channel:
                msg = welcome_msg.replace("{user}", member.mention).replace("{server}", member.guild.name)
                await channel.send(msg)

@bot.event
async def on_member_remove(member):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT leave_ch, leave_msg FROM settings WHERE guild_id = ?", (str(member.guild.id),))
        res = c.fetchone()
    
    if res:
        leave_ch, leave_msg = res
        # Sima szöveges kilépő (NEM Embed)
        if leave_ch and leave_msg:
            channel = member.guild.get_channel(int(leave_ch))
            if channel:
                msg = leave_msg.replace("{user}", member.display_name).replace("{server}", member.guild.name)
                await channel.send(msg)

# --- AUTOMOD RENDSZER (Moderátorokra nem vonatkozik) ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    if not message.author.guild_permissions.manage_messages:
        content = message.content.lower()
        
        # 1. LINK FIGYELMEZTETÉS (Nem töröl)
        if re.search(LINK_PATTERN, content):
            embed = discord.Embed(title="🔗 Link Észlelve", description=f"{message.author.mention}, ezen a szerveren a linkek küldése nem ajánlott!", color=0xFFAA00)
            await message.channel.send(embed=embed, delete_after=10)

        # 2. KÁROMKODÁS SZŰRŐ (Töröl)
        if any(w in content for w in BAD_WORDS):
            try:
                await message.delete()
                return await message.channel.send(f"🚫 {message.author.mention}, kérlek figyelj a stílusodra!", delete_after=5)
            except: pass

        # 3. SPAM SZŰRŐ (Töröl)
        uid = message.author.id
        now = datetime.datetime.now()
        if uid not in bot.antispam: bot.antispam[uid] = []
        bot.antispam[uid] = [t for t in bot.antispam[uid] if (now - t).seconds < 5]
        bot.antispam[uid].append(now)
        if len(bot.antispam[uid]) > 5:
            try:
                await message.delete()
                return await message.channel.send(f"🚀 {message.author.mention}, ne spammelj!", delete_after=5)
            except: pass

    await bot.process_commands(message)

# --- MODERÁCIÓS SLASH PARANCSOK ---

@bot.tree.command(name="figyelmeztetes", description="⚠️ Tag figyelmeztetése és egyéni némítása")
@app_commands.describe(tag="Felhasználó", indok="Indok", percek="Némítás hossza (perc)")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, tag: discord.Member, indok: str, percek: int):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Nem büntethetsz feletted állót!", ephemeral=True)

    wid = "TO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    until = discord.utils.utcnow() + datetime.timedelta(minutes=percek)
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO warns VALUES (?, 0)", (str(tag.id),))
        c.execute("UPDATE warns SET count = count + 1 WHERE uid = ?", (str(tag.id),))
        c.execute("SELECT count FROM warns WHERE uid = ?", (str(tag.id),))
        count = c.fetchone()[0]
        c.execute("INSERT INTO history VALUES (?, ?, ?, ?, ?)", (wid, str(tag.id), indok, interaction.user.display_name, str(datetime.date.today())))
        conn.commit()

    embed = discord.Embed(title="🛑 Szankció Kiosztva", color=0xFF0000, timestamp=discord.utils.utcnow())
    embed.add_field(name="👤 Felhasználó:", value=tag.mention, inline=True)
    embed.add_field(name="🛡️ Moderátor:", value=interaction.user.mention, inline=True)
    embed.add_field(name="⏳ Szankció:", value=f"**{percek} perc némítás**", inline=True)
    embed.add_field(name="📝 Indok:", value=f"```\n{indok}\n```", inline=False)
    embed.add_field(name="🆔 ID:", value=f"`{wid}`", inline=True)
    embed.set_footer(text=f"Összes figyelmeztetés: {count}")

    await tag.timeout(until, reason=indok)
    await interaction.response.send_message(embed=embed)
    try: await tag.send(embed=embed)
    except: pass

@bot.tree.command(name="figyelmeztetes_torles", description="✅ Figyelmeztetések törlése (mennyiség alapján)")
@app_commands.checks.has_permissions(moderate_members=True)
async def del_warns(interaction: discord.Interaction, tag: discord.Member, mennyiseg: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT count FROM warns WHERE uid = ?", (str(tag.id),))
        res = c.fetchone()
        current = res[0] if res else 0
        new_count = max(0, current - mennyiseg)
        c.execute("UPDATE warns SET count = ? WHERE uid = ?", (new_count, str(tag.id)))
        conn.commit()
    await interaction.response.send_message(f"✅ Törölve **{mennyiseg}** figyelmeztetés tőle: {tag.mention}. (Új érték: {new_count})")

@bot.tree.command(name="kitiltas", description="🔨 Tag végleges kitiltása")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Nem tilthatsz ki feletted állót!", ephemeral=True)
    
    embed = discord.Embed(title="🔨 Kitiltás", color=0xFF0000)
    embed.add_field(name="Érintett:", value=tag.mention)
    embed.add_field(name="Indok:", value=indok)
    
    try: await tag.send(f"❌ Kitiltottak a(z) {interaction.guild.name} szerverről!", embed=embed)
    except: pass
    
    await tag.ban(reason=indok)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kirugas", description="👢 Tag kirúgása")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, tag: discord.Member, indok: str):
    if tag.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Nem rúghatsz ki feletted állót!", ephemeral=True)
    
    await tag.kick(reason=indok)
    await interaction.response.send_message(f"👢 {tag.mention} kirúgva. Indok: {indok}")

@bot.tree.command(name="felfuggesztes", description="🔒 Tag felfüggesztése (Rangok elvétele)")
@app_commands.checks.has_permissions(administrator=True)
async def suspend(interaction: discord.Interaction, tag: discord.Member, indok: str):
    role = discord.utils.get(interaction.guild.roles, name="Felfüggesztett")
    if not role: return await interaction.response.send_message("❌ Nincs 'Felfüggesztett' rang!", ephemeral=True)
    
    old_roles = ",".join([str(r.id) for r in tag.roles if r.name != "@everyone"])
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO suspended_users VALUES (?, ?)", (str(tag.id), old_roles))
        conn.commit()

    await tag.edit(roles=[role], reason=indok)
    await interaction.response.send_message(f"🔒 {tag.mention} felfüggesztve. Indok: {indok}")

@bot.tree.command(name="felfuggesztes_feloldasa", description="🔓 Felfüggesztés feloldása")
@app_commands.checks.has_permissions(administrator=True)
async def unsuspend(interaction: discord.Interaction, tag: discord.Member):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT roles FROM suspended_users WHERE uid = ?", (str(tag.id),))
        res = c.fetchone()
    
    if not res: return await interaction.response.send_message("❌ Nem található felfüggesztés!", ephemeral=True)
    
    role_ids = res[0].split(",")
    roles = [interaction.guild.get_role(int(rid)) for rid in role_ids if interaction.guild.get_role(int(rid))]
    await tag.edit(roles=roles)
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM suspended_users WHERE uid = ?", (str(tag.id),))
        conn.commit()
    await interaction.response.send_message(f"🔓 {tag.mention} rangjai visszaállítva!")

# --- BEÁLLÍTÁSOK ---

@bot.tree.command(name="beallitas_udvozlo", description="👋 Üdvözlő szöveg beállítása (Sima szöveg)")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, csatorna: discord.TextChannel, uzenet: str):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO settings (guild_id, welcome_ch, welcome_msg) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET welcome_ch=excluded.welcome_ch, welcome_msg=excluded.welcome_msg", (str(interaction.guild.id), str(csatorna.id), uzenet))
        conn.commit()
    await interaction.response.send_message(f"✅ Üdvözlő szöveg beállítva ide: {csatorna.mention}")

@bot.tree.command(name="beallitas_kilepo", description="😢 Kilépő szöveg beállítása (Sima szöveg)")
@app_commands.checks.has_permissions(administrator=True)
async def set_leave(interaction: discord.Interaction, csatorna: discord.TextChannel, uzenet: str):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO settings (guild_id, leave_ch, leave_msg) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET leave_ch=excluded.leave_ch, leave_msg=excluded.leave_msg", (str(interaction.guild.id), str(csatorna.id), uzenet))
        conn.commit()
    await interaction.response.send_message(f"✅ Kilépő szöveg beállítva ide: {csatorna.mention}")

@bot.tree.command(name="beallitas_autorole", description="🎭 Automatikus rang új tagoknak")
@app_commands.checks.has_permissions(administrator=True)
async def set_autorole(interaction: discord.Interaction, rang: discord.Role):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO settings (guild_id, autorole_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET autorole_id=excluded.autorole_id", (str(interaction.guild.id), str(rang.id)))
        conn.commit()
    await interaction.response.send_message(f"✅ AutoRole beállítva: **{rang.name}**")

@bot.tree.command(name="clear", description="🧹 Üzenetek törlése")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, mennyiseg: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=mennyiseg)
    await interaction.followup.send(f"🧹 Törölve: **{len(deleted)}** üzenet.")

@bot.command()
async def sync(ctx):
    if ctx.author.guild_permissions.administrator:
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ **{len(synced)}** parancs frissítve!")

if __name__ == "__main__":
    if TOKEN:
        Thread(target=run_web).start()
        bot.run(TOKEN)
