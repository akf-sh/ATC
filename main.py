from disnake.ext import commands
import disnake
import os


command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = True

activity = disnake.Activity(
    name='Cabin Crew Simulator',
    type=disnake.ActivityType.playing,
)
bot = commands.InteractionBot(
    test_guilds=[942889868428730369, 1039965646378766347],
    command_sync_flags=command_sync_flags,
    intents=disnake.Intents.all(),
    activity=activity,
)


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        bot.load_extension(f'cogs.{filename[:-3]}')

bot.run(os.getenv('DISCORD_BOT_TOKEN'))