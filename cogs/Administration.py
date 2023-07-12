from disnake.ext import commands
import disnake
import pymongo
import datetime
import os


class Administration(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.db = pymongo.MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))['atc']
        
    @commands.Cog.listener()
    async def on_ready(self):
        print(f'[COGS]: Administration is ready!')
        
    @commands.slash_command(
        name='roles',
        description='Manage your roles.',
    )
    @commands.cooldown(1, 10800, commands.BucketType.user)
    async def roles(self, inter: disnake.ApplicationCommandInteraction):
        self.db.logs.insert_one({
            '_id': inter.id,
            'author': inter.author.id,
            'type': 'INTERACTION_SLASH',
            'interaction': {
                'success': inter.command_failed is False,
                'channel': inter.channel.id,
                'data': dict(inter.data),
            },
            'timestamp': inter.created_at.utcnow(),
        })
        pass
        
        
    @roles.sub_command(
        name='join',
        description='Join a role.',
        options=[
            disnake.Option(
                name='role',
                description='The role to join.',
                choices=commands.option_enum(['Multiplayer', 'QOTD', 'Events', 'Notify']),
                required=True,
            )
        ],
        required=True,
    )
    async def roles_join(self, inter: disnake.ApplicationCommandInteraction, role: str):
        user = self.db['users'].find_one({
            '_id': inter.author.id,
        })
        if user and user['joiner']['state'] == False and role == 'Multiplayer':
            await inter.response.send_message(f'You are blocked from joining the Multiplayer role, for `{user["joiner"]["reason"]}`.', ephemeral=True)
            return
        else:
            if disnake.utils.get(inter.author.roles, name=role) in inter.author.roles:
                return await inter.response.send_message(f'You are already in the {role} role.', ephemeral=True)
            else:
                await inter.author.add_roles(disnake.utils.get(inter.guild.roles, name=role), reason="User requested to join the Role.")
                return await inter.response.send_message(f'You have joined the {role} role.', ephemeral=True)
            
    @roles.sub_command(
        name='leave',
        description='Leave a role.',
        options=[
            disnake.Option(
                name='role',
                description='The role to leave.',
                choices=commands.option_enum(['Multiplayer', 'QOTD', 'Events', 'Notify']),
            )
        ],
        required=True,
    )
    async def roles_leave(self, inter: disnake.ApplicationCommandInteraction, role: str):
        if disnake.utils.get(inter.author.roles, name=role) in inter.author.roles:
            await inter.author.remove_roles(disnake.utils.get(inter.guild.roles, name=role), reason="User requested to leave the Role.")
            return await inter.response.send_message(f'You have left the {role} role.', ephemeral=True)
        else:
            return await inter.response.send_message(f'You are not in the {role} role.', ephemeral=True)
        
    @roles.error
    async def roles_error(self, inter: disnake.ApplicationCommandInteraction, error):
        if isinstance(error, commands.CommandOnCooldown):
            return await inter.response.send_message(embed=disnake.Embed(
                title="You are on cooldown!",
                description=f"You will be able to use this command again <t:{datetime.datetime.now().timestamp() + error.retry_after:.0f}:R>.",
                color=disnake.Color.yellow()
            ), ephemeral=True)
        else:
            return await inter.response.send_message(embed=disnake.Embed(
            title="There was an error!",
            description=f"```{error}```",
            color=disnake.Color.red()
        ), ephemeral=True)
    
    
    
            
            


def setup(bot):
    bot.add_cog(Administration(bot))