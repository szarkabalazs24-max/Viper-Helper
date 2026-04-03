import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
import random
import re

# --- BEÁLLÍTÁSOK ---
TOKEN = "IDE_ÍRD_A_BOT_TOKENEDET"
INTENTS = discord.Intents.all()

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.warns = {}  # Memória-alapú tárolás (élesben adatbázis ajánlott)
        self.autorole_id = None

    async def setup_hook(self):
        # Ticket gomb kezelő regisztrálása (hogy újraindítás után is működjön)
        self.add_view(TicketView())
        await self.tree.sync()
        print(f"✅ Slash parancsok szinkronizálva!")

bot = MyBot()

# --- SEGÉDFÜGGVÉNY: IDŐ KONVERTÁLÁS ---
def parse_duration(duration: str):
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    match = re.match(r"(\d+)([smhd])", duration.lower())
    if not match: return None
    amount, unit = match.groups()
    return int(amount) * time_dict[unit]

# --- TICKET RENDSZER NÉZET ---
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket Nyitása", style=discord.ButtonStyle.primary, emoji="📩", custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ezeket a bot.tree.command-ban állítjuk be, itt csak példa adatokkal futna le, 
        # de a parancsból küldött gombnál elmentjük az adatokat.
        guild = interaction.guild
        user = interaction.user
        
        # Ellenőrizzük, van-e már nyitott ticketje
        existing = discord.utils.get(guild.channels, name=f"ticket-{user.name.lower()}")
        if existing:
            return await interaction.response.send_message(f"❌ Már van egy nyitott ticketed: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        channel = await guild.create_text_channel(name=f"ticket-{user.name}", overwrites=overwrites)
        
        embed = discord.Embed(
            title="📩 Új Ticket érkezett!",
            description=f"Üdvözöllek {user.mention}!\nA Staff hamarosan segítségedre lesz.\n\n**Téma:** Segítségkérés",
            color=discord.Color.green()
        )
        embed.set_footer(text="A lezáráshoz használd a csatorna törlését.")
        
        await channel.send(content=f"{user.mention} | @here", embed=embed)
        await interaction.response.send_message(f"✅ Ticket létrehozva: {channel.mention}", ephemeral=True)

# --- ESEMÉNYEK ---
@bot.event
async def on_ready():
    print(f"🤖 Bot bejelentkezve: {bot.user.name}")
    await bot.change_presence(activity=discord.Game(name="/help | Moderáció"))

@bot.event
async def on_member_join(member):
    if bot.autorole_id:
        role = member.guild.get_role(bot.autorole_id)
        if role:
            await member.add_roles(role)

# --- MODERÁCIÓ (WARN & SUSPEND) ---
@bot.tree.command(name="warn", description="⚠️ Felhasználó figyelmeztetése")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, user: discord.Member, indok: str):
    if user.id not in bot.warns:
        bot.warns[user.id] = []
    
    bot.warns[user.id].append({"reason": indok, "mod": interaction.user.name, "date": str(datetime.date.today())})
    
    embed = discord.Embed(title="⚠️ Figyelmeztetés", color=discord.Color.gold())
    embed.add_field(name="Felhasználó", value=user.mention, inline=True)
    embed.add_field(name="Moderátor", value=interaction.user.mention, inline=True)
    embed.add_field(name="Indok", value=indok, inline=False)
    embed.set_timestamp()
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warn-list", description="📜 Figyelmeztetések megtekintése")
async def warn_list(interaction: discord.Interaction, user: discord.Member):
    user_warns = bot.warns.get(user.id, [])
    
    embed = discord.Embed(title=f"📜 {user.name} Figyelmeztetései", color=discord.Color.blue())
    if not user_warns:
        embed.description = "Ennek a tagnak nincsenek figyelmeztetései."
    else:
        for i, w in enumerate(user_warns, 1):
            embed.add_field(name=f"{i}. Warn", value=f"Indok: {w['reason']}\nModerátor: {w['mod']}", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warn-clear", description="🗑️ Figyelmeztetések törlése")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn_clear(interaction: discord.Interaction, user: discord.Member):
    if user.id in bot.warns:
        bot.warns[user.id] = []
        await interaction.response.send_message(f"✅ {user.mention} összes figyelmeztetése törölve.")
    else:
        await interaction.response.send_message("❌ Nincs mit törölni.", ephemeral=True)

@bot.tree.command(name="suspend", description="🚫 Felhasználó felfüggesztése (Timeout)")
@app_commands.checks.has_permissions(moderate_members=True)
async def suspend(interaction: discord.Interaction, user: discord.Member, ido: str, indok: str):
    seconds = parse_duration(ido)
    if not seconds:
        return await interaction.response.send_message("❌ Érvénytelen időformátum! (Példa: 10m, 1h, 1d)", ephemeral=True)
    
    duration = datetime.timedelta(seconds=seconds)
    await user.timeout(duration, reason=indok)
    
    embed = discord.Embed(title="🚫 Felfüggesztés", color=discord.Color.red())
    embed.add_field(name="Tag", value=user.mention, inline=True)
    embed.add_field(name="Időtartam", value=ido, inline=True)
    embed.add_field(name="Indok", value=indok, inline=False)
    
    await interaction.response.send_message(embed=embed)

# --- TICKET SETUP ---
@bot.tree.command(name="ticket-setup", description="🎫 Ticket panel létrehozása")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_setup(interaction: discord.Interaction, leiras: str):
    embed = discord.Embed(
        title="🎫 Segítségnyújtás",
        description=leiras,
        color=discord.Color.blue()
    )
    embed.set_footer(text="Kattints az alábbi gombra!")
    
    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("✅ Panel kiküldve!", ephemeral=True)

# --- GIVEAWAY ---
@bot.tree.command(name="giveaway", description="🎉 Nyereményjáték indítása")
@app_commands.checks.has_permissions(manage_events=True)
async def giveaway(interaction: discord.Interaction, ido: str, nyeremeny: str, nyertesek: int):
    seconds = parse_duration(ido)
    if not seconds:
        return await interaction.response.send_message("❌ Rossz időformátum!", ephemeral=True)
    
    embed = discord.Embed(title="🎉 NYEREMÉNYJÁTÉK 🎉", color=discord.Color.purple())
    embed.description = f"Nyeremény: **{nyeremeny}**\nIdőtartam: {ido}\nNyertesek száma: {nyertesek}"
    embed.set_footer(text="Jelentkezés a 🎉 reakcióval!")
    
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")
    await interaction.response.send_message("✅ Játék elindítva!", ephemeral=True)
    
    await asyncio.sleep(seconds)
    
    # Sorsolás
    new_msg = await interaction.channel.fetch_message(msg.id)
    users = [user async for user in new_msg.reactions[0].users() if not user.bot]
    
    if not users:
        return await interaction.channel.send(f"❌ A játék lezárult (**{nyeremeny}**), de senki nem jelentkezett.")
    
    winners = random.sample(users, min(len(users), nyertesek))
    winner_mentions = ", ".join([w.mention for w in winners])
    
    await interaction.channel.send(f"🎊 Gratulálunk {winner_mentions}! Megnyerted: **{nyeremeny}**")

# --- AUTOROLE ---
@bot.tree.command(name="autorole", description="🤖 Automatikus rang belépéskor")
@app_commands.checks.has_permissions(administrator=True)
async def autorole(interaction: discord.Interaction, rang: discord.Role):
    bot.autorole_id = rang.id
    await interaction.response.send_message(f"✅ Mostantól minden új tag megkapja ezt a rangot: {rang.name}")

bot.run(TOKEN)
                       
