import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
INTRO_CHANNEL_ID = int(os.getenv("INTRO_CHANNEL_ID"))
INTRO_ROLE = os.getenv("INTRO_ROLE")
MEMBER_ROLE = os.getenv("MEMBER_ROLE")
REMINDER_CHANNEL_ID = int(os.getenv("REMINDER_CHANNEL_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
REMINDER_DELAY = int(os.getenv("REMINDER_DELAY", 3))
KICK_DELAY = int(os.getenv("KICK_DELAY", 7))

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
user_intro_tracker = {}

# Function to log actions
async def log_action(guild, message):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel and log_channel.permissions_for(guild.me).send_messages:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        await log_channel.send(f"[{timestamp}] {message}")
    else:
        print(f"Logging failed: {message}")

# Function to send reminders
async def send_reminder(member, guild):
    try:
        await member.send(
            "Hi! You haven't completed your introduction in the server. Please post your intro in the introductions channel to avoid being removed."
        )
        await log_action(guild, f"Sent reminder to {member.mention} to complete their introduction.")
    except discord.Forbidden:
        reminder_channel = guild.get_channel(REMINDER_CHANNEL_ID)
        if reminder_channel:
            await reminder_channel.send(
                f"{member.mention}, you haven't completed your introduction in the server. Please post in <#{INTRO_CHANNEL_ID}> to avoid being removed."
            )
            await log_action(guild, f"Sent public reminder to {member.mention} in the reminders channel.")
        else:
            await log_action(guild, f"Failed to send reminder to {member.mention}: No access to DMs or reminder channel.")
    except Exception as e:
        await log_action(guild, f"Error sending reminder to {member.mention}: {e}")

# Event: Bot is ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        print(f"Connected to guild: {guild.name} (ID: {guild.id})")
        print("Available roles:")
        for role in guild.roles:
            print(f"- {role.name}")
    if not check_intro_status.is_running():
        check_intro_status.start()

# Event: Member joins the server
@bot.event
async def on_member_join(member):
    guild = member.guild
    intro_role = discord.utils.get(guild.roles, name=INTRO_ROLE)

    if intro_role:
        try:
            await member.add_roles(intro_role)
            user_intro_tracker[member.id] = datetime.now()
            await log_action(
                guild,
                f"{member.mention} has joined the server and was assigned the role '{intro_role.name}'."
            )
        except discord.Forbidden:
            await log_action(
                guild,
                f"Failed to assign role '{intro_role.name}' to {member.mention}: Bot lacks permission."
            )
        except Exception as e:
            await log_action(
                guild,
                f"Error assigning role '{intro_role.name}' to {member.mention}: {e}"
            )
    else:
        await log_action(
            guild,
            f"{member.mention} has joined the server, but the role '{INTRO_ROLE}' was not found."
        )

# Command: Assign a role to a member
@bot.command()
async def assign_role(ctx, member: discord.Member, role_name: str):
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if not role:
        await ctx.send(f"Role '{role_name}' not found.")
        return

    try:
        await member.add_roles(role)
        await ctx.send(f"Assigned role '{role_name}' to {member.mention}.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to manage this role.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

# Command: Ping
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# Event: Member leaves the server
@bot.event
async def on_member_remove(member):
    guild = member.guild
    user_intro_tracker.pop(member.id, None)
    await log_action(guild, f"{member.mention} has left or was kicked from the server.")

# Event: Message in the introduction channel
@bot.event
async def on_message(message):
    if message.channel.id == INTRO_CHANNEL_ID and not message.author.bot:
        guild = message.guild
        member_role = discord.utils.get(guild.roles, name=MEMBER_ROLE)
        intro_role = discord.utils.get(guild.roles, name=INTRO_ROLE)

        if intro_role and intro_role in message.author.roles:
            try:
                await message.author.remove_roles(intro_role)
                await message.author.add_roles(member_role)
                await log_action(
                    guild,
                    f"Assigned 'Member' role to {message.author.mention} after completing introduction."
                )
                user_intro_tracker.pop(message.author.id, None)
            except discord.Forbidden:
                await log_action(
                    guild,
                    f"Failed to update roles for {message.author.mention}: Bot lacks permission."
                )
            except Exception as e:
                await log_action(
                    guild,
                    f"Error updating roles for {message.author.mention}: {e}"
                )
        else:
            await log_action(
                guild,
                f"{message.author.mention} tried to complete introduction but has no '{INTRO_ROLE}'."
            )
    await bot.process_commands(message)

# Task: Check intro status periodically
@tasks.loop(hours=24)
async def check_intro_status():
    current_time = datetime.now()
    guild = bot.get_guild(GUILD_ID)

    if not guild:
        print("Guild not found. Ensure the bot is in the correct server.")
        return

    for user_id, join_time in list(user_intro_tracker.items()):
        member = guild.get_member(user_id)

        if not member:
            await log_action(guild, f"User with ID {user_id} is no longer in the server. Cleaning up tracker.")
            user_intro_tracker.pop(user_id, None)
            continue

        if current_time - join_time > timedelta(days=KICK_DELAY):
            if guild.me.top_role <= member.top_role:
                await log_action(guild, f"Cannot kick {member.mention}: Their role is higher or equal to the bot's role.")
                continue
            try:
                await member.kick(reason="Did not complete introduction in time.")
                await log_action(guild, f"Kicked {member.mention} for not completing their introduction after {KICK_DELAY} days.")
                user_intro_tracker.pop(user_id, None)
            except discord.Forbidden:
                await log_action(guild, f"Failed to kick {member.mention}: Bot lacks permissions.")
            except Exception as e:
                await log_action(guild, f"Error kicking {member.mention}: {e}")

        elif current_time - join_time > timedelta(days=REMINDER_DELAY):
            await send_reminder(member, guild)

# Run the bot
bot.run(TOKEN)
