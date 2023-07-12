from disnake.ext import commands
import disnake
from disnake import Embed
import pymongo
import os
import datetime
from asyncio import sleep, tasks
import re


class FlightCrewConfigurationRulesModal(disnake.ui.Modal):
    def __init__(self, inter: disnake.ApplicationCommandInteraction):
        self.db = pymongo.MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        )["atc"]
        self.user = self.db["users"].find_one(
            {
                "_id": inter.author.id,
            }
        )

        super().__init__(
            title=f"Configure Ruleset",
            custom_id=f"flight_crew_configuration_rules_{inter.author.id}",
            components=[
                disnake.ui.TextInput(
                    label="Short Rules",
                    placeholder="Will be visible on your Flight Crew Post.",
                    value=self.user["flight_crew"]["configuration"]["rules"]["short"],
                    custom_id="short",
                    style=disnake.TextInputStyle.paragraph,
                    min_length=20,
                    max_length=128,
                    required=True,
                ),
                disnake.ui.TextInput(
                    label="Detailed Rules",
                    placeholder="Will be visible when users join the flight.",
                    value=self.user["flight_crew"]["configuration"]["rules"]["long"],
                    custom_id="long",
                    style=disnake.TextInputStyle.paragraph,
                    min_length=20,
                    max_length=512,
                    required=True,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        if inter.user.id != int(self.custom_id.split("_")[-1]):
            await inter.response.send_message(
                "You are not allowed to use this button.", ephemeral=True
            )
            return

        if (
            inter.text_values.get("short") is None
            or inter.text_values.get("long") is None
        ):
            await inter.response.send_message(
                "You must fill out all fields.", ephemeral=True
            )
            return

        self.db["users"].update_one(
            {
                "_id": inter.user.id,
            },
            {
                "$set": {
                    "flight_crew": {
                        "configuration": {
                            "rules": {
                                "short": inter.text_values.get("short"),
                                "long": inter.text_values.get("long"),
                            },
                        }
                    }
                }
            },
            upsert=True,
        )

        await inter.response.send_message(
            "Your rules have been updated.", ephemeral=True
        )

    async def on_error(self, error: Exception, inter: disnake.ModalInteraction):
        error_embed = disnake.Embed(
            color=disnake.Color.red(),
            timestamp=inter.created_at,
            description=f"**An error occured while executing the command. Please try again later:**\n```${error}```",
        )
        if inter.response.is_done():
            await inter.followup.send(embed=error_embed, ephemeral=True)
        else:
            await inter.response.send_message(embed=error_embed, ephemeral=True)


class FlightCrewReportUserModal(disnake.ui.Modal):
    def __init__(self, inter: disnake.ApplicationCommandInteraction):
        self.db = pymongo.MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        )["atc"]

        super().__init__(
            title=f"Report Flight",
            custom_id=f"flight_crew_report_modal_{inter.author.id}",
            components=[
                disnake.ui.TextInput(
                    label="Who are the User(s) that you are Reporting?",
                    placeholder="List their Usernames here.",
                    custom_id="users",
                    style=disnake.TextInputStyle.paragraph,
                    min_length=3,
                    max_length=128,
                    required=True,
                ),
                disnake.ui.TextInput(
                    label="What is the reason you are Reporting them?",
                    placeholder="Be detailed so our Moderators can take action.",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    min_length=20,
                    max_length=512,
                    required=True,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        flight = self.db.flights.find_one(
            {
                "attendants": {
                    "$in": [inter.user.id],
                },
                "status": {"$in": ["Created", "Started"]},
            }
        )
        if flight is None:
            await inter.response.send_message(
                "You are not allowed to use this.", ephemeral=True
            )
            return

        if (
            inter.text_values.get("users") is None
            or inter.text_values.get("reason") is None
        ):
            await inter.response.send_message(
                "You must fill out all fields.", ephemeral=True
            )
            return
        else:
            already_reported = self.db["flight_reports"].find_one(
                {
                    "flight": flight["_id"],
                    "reporter": inter.user.id,
                }
            )
            if already_reported is not None:
                return await inter.response.send_message(
                    "You have already reported this flight.", ephemeral=True
                )

            report_id = (
                self.db["flight_reports"]
                .insert_one(
                    {
                        "flight": flight["_id"],
                        "reporter": inter.user.id,
                        "users": [],
                        "reason": inter.text_values.get("reason"),
                        "timestamp": datetime.datetime.utcnow(),
                        "status": "Created",
                        "moderator": None,
                        "moderator_message": None,
                        "message_id": None,
                        "activity": [
                            {
                                "status": "Created",
                                "type": "CREATE_REPORT",
                                "context": "User created the report.",
                                "timestamp": datetime.datetime.utcnow(),
                            }
                        ],
                    }
                )
                .inserted_id
            )
            message: disnake.message = await inter.guild.get_channel(
                disnake.utils.get(inter.guild.channels, name="flight-reports").id
            ).send(
                f"<@&{disnake.utils.get(inter.guild.roles, name='Moderation Team').id}>",
                embed=Embed(
                    title=f"Flight #{flight['_id']} has been Reported",
                    timestamp=datetime.datetime.utcnow(),
                )
                .add_field(
                    name="Reporter",
                    value=inter.user.mention,
                )
                .add_field(
                    name="Users",
                    value=inter.text_values.get("users"),
                )
                .add_field(
                    name="Thread",
                    value=disnake.utils.get(
                        inter.guild.threads, id=flight["message_data"]["thread_id"]
                    ).mention,
                )
                .add_field(
                    name="Reason",
                    value=inter.text_values.get("reason"),
                    inline=False,
                )
                .add_field(
                    name="Status",
                    value="Created",
                )
                .add_field(
                    name="Moderator",
                    value="None",
                )
                .add_field(
                    name="Moderator Notes",
                    value="None",
                    inline=False,
                )
                .set_footer(
                    text=f"Report ID: {report_id}",
                ),
                components=[
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            style=disnake.ButtonStyle.green,
                            label="Respond",
                            custom_id=f"flight_report_respond_{report_id}",
                        ),
                        disnake.ui.Button(
                            style=disnake.ButtonStyle.red,
                            label="Close",
                            custom_id=f"flight_report_close_{report_id}",
                        ),
                    ),
                ],
            )
            if message is not None:
                self.db.flight_reports.update_one(
                    {
                        "_id": report_id,
                    },
                    {
                        "$set": {
                            "message_id": message.id,
                        }
                    },
                )
            await inter.response.send_message(
                "Your report has been submitted.", ephemeral=True
            )

    async def on_error(self, error: Exception, inter: disnake.ModalInteraction):
        error_embed = disnake.Embed(
            color=disnake.Color.red(),
            timestamp=inter.created_at,
            description=f"**An error occured while executing the command. Please try again later:**\n```${error}```",
        )
        if inter.response.is_done():
            await inter.followup.send(embed=error_embed, ephemeral=True)
        else:
            await inter.response.send_message(embed=error_embed, ephemeral=True)


class FlightCrewReportModModal(disnake.ui.Modal):
    def __init__(self, inter: disnake.ApplicationCommandInteraction):
        self.db = pymongo.MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        )["atc"]

        super().__init__(
            title=f"Flight Report Action Response",
            custom_id=f"flight_crew_report_mod_{inter.author.id}",
            components=[
                disnake.ui.TextInput(
                    label="What actions did you take?",
                    placeholder="Describe the actions taken, include any relevant Case IDs.",
                    custom_id="long",
                    style=disnake.TextInputStyle.paragraph,
                    min_length=20,
                    max_length=2048,
                    required=True,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        report = self.db.flight_reports.find_one(
            {
                "moderator": inter.user.id,
            }
        )

        if (
            inter.text_values.get("short") is None
            or inter.text_values.get("long") is None
        ):
            await inter.response.send_message(
                "You must fill out all fields.", ephemeral=True
            )
            return

        self.db["users"].update_one(
            {
                "_id": inter.user.id,
            },
            {
                "$set": {
                    "flight_crew": {
                        "configuration": {
                            "rules": {
                                "short": inter.text_values.get("short"),
                                "long": inter.text_values.get("long"),
                            },
                        }
                    }
                }
            },
            upsert=True,
        )

        await inter.response.send_message(
            "Your rules have been updated.", ephemeral=True
        )

    async def on_error(self, error: Exception, inter: disnake.ModalInteraction):
        error_embed = disnake.Embed(
            color=disnake.Color.red(),
            timestamp=inter.created_at,
            description=f"**An error occured while executing the command. Please try again later:**\n```${error}```",
        )
        if inter.response.is_done():
            await inter.followup.send(embed=error_embed, ephemeral=True)
        else:
            await inter.response.send_message(embed=error_embed, ephemeral=True)


aircraft_metadata = [
    {
        "name": "DASH-8",
        "crew": 1,
        "earn": 550,
    },
    {
        "name": "E175",
        "crew": 1,
        "earn": 600,
    },
    {
        "name": "B717-200",
        "crew": 1,
        "earn": 750,
    },
    {
        "name": "B737-800",
        "crew": 2,
        "earn": 920,
    },
    {
        "name": "A320",
        "crew": 2,
        "earn": 1150,
    },
    {
        "name": "A321",
        "crew": 3,
        "earn": 1400,
    },
    {
        "name": "B757-200",
        "crew": 4,
        "earn": 1500,
    },
    {
        "name": "B787-8",
        "crew": 7,
        "earn": 1900,
    },
    {
        "name": "A330-200",
        "crew": 7,
        "earn": 2500,
    },
    {
        "name": "B777-300",
        "crew": 7,
        "earn": 3300,
    },
    {"name": "A350-1000", "crew": 7, "earn": 3700},
    {
        "name": "B747-400",
        "crew": 8,
        "earn": 4500,
    },
    {
        "name": "A380",
        "crew": 9,
        "earn": 5500,
    },
]

airports = [
    "Robloxia",
    "New York City",
    "Seattle",
    "Los Angeles",
    "Honolulu",
    "Tokyo",
    "Tahiti",
    "Santorini",
    "Paris",
    "Sydney",
]


class FlightCrew(commands.Cog):
    def __init__(self, bot: commands.InteractionBot):
        self.bot = bot
        self.db = pymongo.MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        )["atc"]
        self.guild = os.getenv("DISCORD_OPERATING_GUILD", 942889868428730369)
        self.channels = {
            "flightcrew": os.getenv("DISCORD_FLIGHT_CREW_CHANNEL", 1101913983931387904)
        }
        self.roles = {
            "multiplayer": os.getenv("DISCORD_FLIGHT_CREW_ROLE", 1127374992141713518),
            "multiplayer_connect": os.getenv(
                "DISCORD_MULTIPLAYER_CONNECT_ROLE", 1016925749036449943
            ),
            "flightcrew_mod": os.getenv(
                "DISCORD_FLIGHT_CREW_MOD_ROLE", 1128039398760529940
            ),
        }

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"[COGS]: FlightCrew is ready!")

    async def link_validator(self, link):
        ExperienceInvite = re.compile(
            r"(?:https:\/\/(?:www\.|web\.)?roblox\.com\/share\?code=)([a-zA-Z0-9]+)(?:&type=ExperienceInvite)"
        )

        Profile = re.compile(
            r"(?:https:\/\/(?:www\.|web\.)?roblox\.com\/users\/)([0-9]+)(?:\/profile)"
        )

        PrivateServerLinkCode = re.compile(
            r"(?:https:\/\/(?:www\.|web\.)?roblox\.com\/games\/)([0-9]+)(?:\?privateServerLinkCode=)([0-9]+)"
        )

        if ExperienceInvite.match(link) is not None:
            return "ExperienceInvite"
        elif Profile.match(link) is not None:
            return "Profile"
        elif PrivateServerLinkCode.match(link) is not None:
            return "PrivateServer"
        else:
            return None

    async def create_user(self, user_id):
        doc = {
            "_id": int(user_id),
            "flight_crew": {
                "configuration": {
                    "rules": {
                        "short": "No rules have been set.",
                        "long": "No rules have been set.",
                    },
                    "blocklist": [],
                },
                "abilities": {
                    "joiner": {"state": True, "reason": None, "mod": None},
                    "host": {"state": True, "reason": None, "mod": None},
                },
            },
        }
        self.db["users"].insert_one(doc)
        return doc

    async def flight_plan_builder(
        self, inter: disnake.ApplicationCommandInteraction, route: list
    ):
        document = {
            "_id": self.db.flights.count_documents({}) + 1,
            "host": inter.author.id,
            "aircraft": inter.filled_options.get("aircraft"),
            "airports": route,
            "attendants": [],
            "link": inter.filled_options.get("link"),
            "created_at": disnake.utils.utcnow(),
            "start_time": disnake.utils.utcnow()
            + datetime.timedelta(minutes=int(inter.filled_options.get("start_time"))),
            "completed_at": None,
            "status": "Created",
            "message_data": {
                "message_id": None,
                "thread_id": None,
                "thread_message_id": None,
            },
            "activity": [
                {
                    "title": "Created Simple Flight",
                    "type": "FLIGHT_CREATE",
                    "user": inter.author.id,
                    "context": "Created a Single Leg Flight Crew Post via Slash Command",
                    "timestamp": disnake.utils.utcnow(),
                }
            ],
        }
        joinable_flights = self.db.flights.count_documents({"status": "Created"})
        if joinable_flights >= 5 and not disnake.utils.get(
            inter.author.roles, name="Nitro Booster"
        ):
            return {
                "success": False,
                "message": "There are too many joinable Flight Crew posting's at this time, please try to create a Flight Crew posting later, or Boost the server to create a Flight Crew posting now.",
                "document": None,
            }
        else:
            self.db.flights.insert_one(document)
            return {
                "success": True,
                "message": f"Flight Created with the ID of {document['_id']}.",
                "document": document,
            }

    async def reply_builder(
        self,
        inter: disnake.ApplicationCommandInteraction,
        title: str,
        message: str,
        type: str = None,
    ):
        """
        Reply Builder
        """
        color = disnake.Color.dark_gray()
        if type == "error":
            color = disnake.Color.red()
        elif type == "success":
            color = disnake.Color.green()

        embed = Embed(
            title=title,
            description=f"**{message}**" if type != "error" else message,
            color=color,
        )
        embed.set_footer(
            text="Interaction ID: " + str(inter.id)
            if type == "error"
            else "ATC Bot by austin.ts"
        )
        if inter.response.is_done():
            await inter.followup.send(embed=embed, ephemeral=True, delete_after=15)
        else:
            await inter.response.send_message(
                embed=embed,
                ephemeral=True,
            )

    async def flight_message_builder(self, flight_plan, flight_host):
        """
        Embed Creation
        """
        embed = disnake.Embed(
            color=disnake.Color.green()
            if flight_plan["status"] == "Created"
            else disnake.Color.dark_grey(),
            description=flight_host["flight_crew"]["configuration"]["rules"]["short"],
        )
        # Aircraft Information
        embed.add_field(
            name="Aircraft",
            value=flight_plan["aircraft"],
            inline=True,
        )
        embed.add_field(
            name="Max Earnings",
            value=f":money_with_wings: **{[aircraft['earn'] for aircraft in aircraft_metadata if aircraft['name'] == flight_plan['aircraft']][0] }**",
            inline=True,
        )

        # Flight Information
        embed.add_field(
            name="Flight Plan",
            value=f"**{' :arrow_right: '.join(airport for airport in flight_plan['airports'])}**",
            inline=False,
        )

        # Crew Information
        embed.add_field(
            name="Host",
            value=f"<@{flight_plan['host']}>",
            inline=True,
        )

        # Footer
        embed.set_footer(
            text=f"Flight Status: {flight_plan['status']}",
            icon_url=self.bot.user.avatar.url,
        )

        """
        Component Creator
        """
        main_view = disnake.ui.View()
        thread_view = disnake.ui.View()

        # Leave Flight Button

        thread_view.add_item(
            disnake.ui.Button(
                style=disnake.ButtonStyle.blurple,
                label="Leave Flight",
                custom_id=f"flight_crew_leave_{flight_plan['_id']}",
                disabled=flight_plan["status"] != "Created",
                row=1,
            )
        )

        # Vote Flight Complete Button

        thread_view.add_item(
            disnake.ui.Button(
                style=disnake.ButtonStyle.green,
                label="Vote Flight Complete",
                custom_id=f"flight_crew_vote_{flight_plan['_id']}",
                emoji="✅",
                disabled=flight_plan["status"]
                in ["Completed", "Canceled", "Moderated"],
            )
        )

        # Report Flight Button

        thread_view.add_item(
            disnake.ui.Button(
                style=disnake.ButtonStyle.red,
                label="Report Flight",
                custom_id=f"flight_crew_report_{flight_plan['_id']}",
                emoji="⚠",
                disabled=flight_plan["status"] in ["Moderated"],
            )
        )

        # Profile / Private Server Button

        if flight_plan["link"] is not None:
            thread_view.add_item(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.link,
                    label="Join Link",
                    url=flight_plan["link"],
                    disabled=flight_plan["status"]
                    in ["Created", "Moderated", "Canceled", "Completed"],
                )
            )

        # Join Flight Button

        main_view.add_item(
            disnake.ui.Button(
                disabled=len(flight_plan["attendants"])
                > int(
                    [
                        aircraft["crew"]
                        for aircraft in aircraft_metadata
                        if aircraft["name"] == flight_plan["aircraft"]
                    ][0]
                )
                or flight_plan["status"] != "Created",
                style=disnake.ButtonStyle.green,
                label="Join Flight",
                custom_id=f"flight_crew_join_{flight_plan['_id']}",
                row=2,
            )
        )

        # Crew Button

        main_view.add_item(
            disnake.ui.Button(
                style=disnake.ButtonStyle.gray,
                label=f"{len(flight_plan['attendants'])}/{[aircraft['crew'] for aircraft in aircraft_metadata if aircraft['name'] == flight_plan['aircraft']][0]} Flight Crew",
                emoji="👨‍✈️",
                custom_id=f"flight_crew_attendants_{flight_plan['_id']}",
                row=1,
            ),
        )

        if (
            disnake.utils.get(
                self.bot.get_guild(self.guild).roles,
                name="Multiplayer Connect",
            )
            in self.bot.get_guild(self.guild).get_member(flight_plan["host"]).roles
        ):
            main_view.add_item(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.green,
                    label="Multiplayer Connect",
                    emoji="<:PlayerConnect:1127429040660295761>",
                    custom_id="flight_crew_mp_connect",
                    row=0,
                )
            )
        if (
            disnake.utils.get(
                self.bot.get_guild(self.guild).roles, name="Emergency Control"
            )
            in self.bot.get_guild(self.guild).get_member(flight_plan["host"]).roles
        ):
            main_view.add_item(
                disnake.ui.Button(
                    style=disnake.ButtonStyle.green,
                    label="Emergency Control",
                    disabled=False,
                    emoji="<:EmergencyControl:1127428140738805800>",
                    custom_id="flight_crew_emergency_control",
                    row=0,
                )
            )

        return {
            "embed": embed,
            "components": {
                "thread": thread_view,
                "main": main_view,
            },
        }

    async def flight_message_manager(self, _id):
        flight_plan = self.db.flights.find_one({"_id": _id})
        flight_host = self.db.users.find_one({"_id": flight_plan["host"]})
        if flight_plan:
            if (
                flight_plan["message_data"]["message_id"]
                and flight_plan["message_data"]["thread_id"]
                and flight_plan["message_data"]["thread_message_id"]
            ):
                if flight_plan["status"] == "Created":
                    built_message = await self.flight_message_builder(
                        flight_plan, flight_host
                    )

                    flight_crew_message: disnake.Message = await self.bot.get_channel(
                        self.channels.get("flightcrew")
                    ).fetch_message(flight_plan["message_data"]["message_id"])

                    flight_crew_thread: disnake.Thread = self.bot.get_guild(
                        self.guild
                    ).get_thread(flight_plan["message_data"]["thread_id"])

                    flight_crew_thread_message: disnake.Message = (
                        await flight_crew_thread.fetch_message(
                            flight_plan["message_data"]["thread_message_id"]
                        )
                    )

                    await flight_crew_message.edit(
                        content=self.bot.get_guild(self.guild)
                        .get_role(self.roles.get("multiplayer"))
                        .mention
                        if flight_plan["status"] == "Created"
                        else None,
                        embed=built_message["embed"],
                        view=built_message["components"]["main"],
                    )

                    await flight_crew_thread_message.edit(
                        content=None,
                        embed=built_message["embed"],
                        view=built_message["components"]["thread"],
                    )

                elif flight_plan["status"] == "Started":
                    built_message = await self.flight_message_builder(
                        flight_plan, flight_host
                    )
                    flight_crew_message: disnake.Message = await self.bot.get_channel(
                        self.channels.get("flightcrew")
                    ).fetch_message(flight_plan["message_data"]["message_id"])

                    flight_crew_thread: disnake.Thread = self.bot.get_guild(
                        self.guild
                    ).get_thread(flight_plan["message_data"]["thread_id"])

                    flight_crew_thread_message: disnake.Message = (
                        await flight_crew_thread.fetch_message(
                            flight_plan["message_data"]["thread_message_id"]
                        )
                    )

                    if flight_crew_message:
                        await flight_crew_message.delete()

                    if flight_crew_thread_message:
                        await flight_crew_thread_message.edit(
                            content=None,
                            embed=built_message["embed"],
                            view=built_message["components"]["thread"],
                        )

                else:
                    flight_crew_thread: disnake.Thread = self.bot.get_guild(
                        self.guild
                    ).get_thread(flight_plan["message_data"]["thread_id"])
                    flight_crew_thread_message: disnake.Message = (
                        await flight_crew_thread.fetch_message(
                            flight_plan["message_data"]["thread_message_id"]
                        )
                    )

                    if flight_crew_thread_message:
                        await flight_crew_thread_message.edit(
                            content=None,
                            embed=built_message["embed"],
                            view=built_message["components"]["thread"],
                        )

                    await flight_crew_thread.edit(archived=True, locked=True)

            else:
                # Create Flight Host User Document

                if not flight_host:
                    flight_host = await self.create_user(flight_plan["host"])

                # Build Message

                built_message = await self.flight_message_builder(
                    flight_plan, flight_host
                )

                # Create Flight Message Post

                flight_crew_message: disnake.Message = await self.bot.get_channel(
                    self.channels.get("flightcrew")
                ).send(
                    content=self.bot.get_guild(self.guild)
                    .get_role(self.roles.get("multiplayer"))
                    .mention,
                    embed=built_message["embed"],
                    view=built_message["components"]["main"],
                )

                if flight_crew_message:
                    flight_plan["message_data"]["message_id"] = flight_crew_message.id
                else:
                    return False

                # Create Flight Thread

                flight_crew_thread: disnake.Thread = await self.bot.get_channel(
                    self.channels.get("flightcrew")
                ).create_thread(
                    name=f"Flight #{flight_plan['_id']} Discussion",
                    auto_archive_duration=60,
                    type=disnake.ChannelType.private_thread,
                    reason=f"Flight #{flight_plan['_id']} Discussion Thread",
                )

                if flight_crew_thread:
                    await flight_crew_thread.add_user(
                        self.bot.get_guild(self.guild).get_member(flight_plan["host"])
                    )
                    flight_plan["message_data"]["thread_id"] = flight_crew_thread.id
                else:
                    return False

                # Create Flight Thread Post

                flight_crew_thread_message = await flight_crew_thread.send(
                    embed=built_message["embed"],
                    view=built_message["components"]["thread"],
                )

                await flight_crew_thread_message.pin(
                    reason=f"Flight #{flight_plan['_id']} Start Message Accessibility Pin"
                )

                if flight_crew_thread_message:
                    flight_plan["message_data"][
                        "thread_message_id"
                    ] = flight_crew_thread_message.id
                else:
                    return False

                # Update Flight Document

                flight_plan_updated = self.db.flights.update_one(
                    {"_id": flight_plan["_id"]},
                    {"$set": {"message_data": flight_plan["message_data"]}},
                )

                if flight_plan_updated.acknowledged:
                    return True
                else:
                    return False

    @commands.Cog.listener()
    async def on_thread_member_remove(self, member: disnake.ThreadMember):
        flight = self.db.flights.find_one(
            {
                "message_data.thread_id": member.thread.id,
                "attendants": {"$in": [member.id]},
            }
        )
        if flight is not None:
            self.db["flight_crew"].update_one(
                {"_id": flight["_id"]},
                {
                    "$pull": {"attendants": member.id},
                    "$push": {
                        "activity": {
                            "title": "Left Flight",
                            "type": "LEAVE_FLIGHT",
                            "user": member.id,
                            "context": "User left the flight by leaving the thread.",
                            "timestamp": disnake.utils.utcnow(),
                        },
                    },
                },
            )

    @commands.Cog.listener()
    async def on_thread_member_join(self, member: disnake.ThreadMember):
        flight = self.db.flights.find_one({"message_data.thread_id": member.thread.id})
        if flight is not None:
            user: disnake.User = disnake.utils.get(
                member.thread.guild.members, id=member.id
            )
            if user is not None:
                if (
                    disnake.utils.get(
                        member.thread.guild.roles, id=self.roles["flightcrew_mod"]
                    )
                    in user.roles
                ):
                    return
                if member.id not in flight["attendants"]:
                    return await member.thread.remove_user(member)

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.ApplicationCommandInteraction):
        if inter.data.custom_id.startswith("flight_crew_join_"):
            user_busy = self.db["flights"].find_one(
                {
                    "$or": [
                        {"host": inter.author.id},
                        {"attendants": {"$in": [inter.author.id]}},
                    ],
                    "status": {"$in": ["Created", "Started"]},
                }
            )
            if user_busy is not None:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You cannot join more than one flight at a time.",
                )
            plan = self.db["flights"].find_one(
                {"_id": int(inter.data.custom_id.split("_")[-1])}
            )
            if plan is None:
                return await self.reply_builder(
                    inter,
                    title="Not Found",
                    message="**Flight not found.**",
                    type="error",
                )
            host = self.db["users"].find_one({"_id": plan["host"]})
            joiner = self.db["users"].find_one({"_id": inter.author.id})
            if not joiner:
                joiner = await self.create_user(inter.author.id)
            if not host:
                host = await self.create_user(plan["host"])
            if plan is None:
                return await self.reply_builder(
                    inter,
                    title="Not Found",
                    message="**Flight not found.**",
                    type="error",
                )
            elif inter.author.id == plan["host"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You cannot join your own flight.",
                )
            elif inter.author.id in plan["attendants"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You are already a part of this flight.",
                )
            elif (
                len(plan["attendants"])
                >= [
                    aircraft["crew"]
                    for aircraft in aircraft_metadata
                    if aircraft["name"] == plan["aircraft"]
                ][0]
            ):
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="**Flight is full.**",
                    type="error",
                )
            elif plan["status"] != "Created":
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="**Flight is no longer joinable.**",
                    type="error",
                )
            elif inter.author.id in host["flight_crew"]["configuration"]["blocklist"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="**An error occured whilst join this flight. Please try again later.**",
                    type="error",
                )
            elif joiner["flight_crew"]["abilities"]["joiner"]["state"] is False:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message=f"You are currently blocked from joining flights, reason: {joiner['flight_crew']['abilities']['joiner']['reason']}",
                )
            elif host["flight_crew"]["abilities"]["host"]["state"] is False:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message=f"**An error occured whilst join this flight. Please try again later.**",
                    type="error",
                )
            else:
                await inter.response.defer()
                activity = [
                    activity
                    for activity in plan["activity"]
                    if activity["type"] == "LEAVE_FLIGHT"
                    and activity["user"] == inter.author.id
                ]
                if len(activity) < 1 or (
                    len(activity) != 0
                    and disnake.utils.utcnow()
                    - activity[-1]["timestamp"].replace(tzinfo=datetime.timezone.utc)
                    > datetime.timedelta(minutes=1)
                ):
                    self.db["flights"].update_one(
                        {
                            "_id": plan["_id"],
                        },
                        {
                            "$push": {
                                "attendants": inter.author.id,
                                "activity": {
                                    "title": "Joined Flight",
                                    "type": "JOIN_FLIGHT",
                                    "user": inter.author.id,
                                    "context": "User joined the flight via a button.",
                                    "timestamp": disnake.utils.utcnow(),
                                },
                            },
                        },
                    )
                    plan["attendants"].append(inter.author.id)
                    await inter.guild.get_thread(
                        plan["message_data"]["thread_id"]
                    ).add_user(inter.author)
                    await self.flight_message_manager(plan["_id"])
                    return await self.reply_builder(
                        inter,
                        title="Success",
                        message=f"You have successfully joined Flight #{plan['_id']}",
                        type="success",
                    )

        if inter.data.custom_id.startswith("flight_crew_leave_"):
            plan = self.db["flights"].find_one(
                {"_id": int(inter.data.custom_id.split("_")[-1])}
            )
            if plan is None:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Flight does not exist.",
                )
            elif inter.author.id == plan["host"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You cannot leave your own flight.",
                )
            elif inter.author.id not in plan["attendants"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You are not a part of this flight.",
                )
            elif plan["status"] != "Created":
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Flight is locked.",
                )
            else:
                await inter.response.defer()
                activity = [
                    activity
                    for activity in plan["activity"]
                    if activity["type"] == "JOIN_FLIGHT"
                    and activity["user"] == inter.author.id
                ]
                if len(activity) == 0 or disnake.utils.utcnow() - activity[-1][
                    "timestamp"
                ].replace(tzinfo=datetime.timezone.utc) > datetime.timedelta(
                    seconds=30
                ):
                    self.db.flights.update_one(
                        {
                            "_id": plan["_id"],
                        },
                        {
                            "$pull": {
                                "attendants": inter.author.id,
                            },
                            "$push": {
                                "activity": {
                                    "title": "Left Flight",
                                    "type": "LEAVE_FLIGHT",
                                    "user": inter.author.id,
                                    "context": "User left the flight via a button.",
                                    "timestamp": disnake.utils.utcnow(),
                                },
                            },
                        },
                    )

                    await self.reply_builder(
                        inter,
                        title="Success",
                        message=f"{inter.author.global_name} have successfully left Flight #{plan['_id']}",
                        type="success",
                    )

                    await self.flight_message_manager(plan["_id"])

                    await inter.guild.get_thread(
                        plan["message_data"]["thread_id"]
                    ).remove_user(inter.author)
                else:
                    return await self.reply_builder(
                        inter,
                        title="Not Allowed",
                        message="You cannot leave this flight, there is a cooldown.",
                    )

        if inter.data.custom_id.startswith("flight_crew_complete_"):
            plan = self.db["flights"].find_one(
                {"_id": int(inter.data.custom_id.split("_")[-1])}
            )
            if plan is None:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Flight does not exist.",
                )
            elif inter.author.id not in plan["attendants"]:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You are not a part of this flight.",
                )
            elif plan["status"] == "Created":
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Flight is not locked.",
                )
            elif plan["status"] == "Completed":
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Flight is already completed.",
                )
            else:
                # check if the user has an activity in plan['activity'] of type 'COMPLETE_FLIGHT'
                activity = [
                    activity
                    for activity in plan["activity"]
                    if activity["type"] == "COMPLETE_FLIGHT"
                    and activity["user"] == inter.author.id
                ]
                if len(activity) == 0:
                    completed = len(
                        [
                            activity
                            for activity in plan["activity"]
                            if activity["type"] == "COMPLETE_FLIGHT"
                        ]
                    )
                    self.db.flights.update_one(
                        {"_id": plan["_id"]},
                        {
                            "$push": {
                                "activity": {
                                    "title": "Vote Completed Flight",
                                    "type": "COMPLETE_FLIGHT",
                                    "user": inter.author.id,
                                    "context": "User marked the flight complete via the button.",
                                    "timestamp": disnake.utils.utcnow(),
                                },
                            }
                        },
                    )

                    if (
                        completed + 1 / len(plan["attendants"]) >= 0.6
                        and len(plan["attendants"]) >= 3
                    ):
                        await self.db.flights.update_one(
                            {"_id": plan["_id"]}, {"$set": {"status": "Completed"}}
                        )
                        await self.flight_message_manager(plan["_id"])
                        return await self.reply_builder(
                            inter,
                            title="Flight Completed",
                            message="Flight has been marked as completed.",
                            type="success",
                        )
                    elif completed + 1 == len(plan["attendants"]):
                        await self.db.flights.update_one(
                            {"_id": plan["_id"]}, {"$set": {"status": "Completed"}}
                        )
                        await self.flight_message_manager(plan["_id"])
                        return await self.reply_builder(
                            inter,
                            title="Flight Completed",
                            message="Flight has been marked as completed.",
                            type="success",
                        )
                    else:
                        return await self.reply_builder(
                            inter,
                            title="Voted to mark Flight Complete",
                            message="You have voted to mark this flight as complete.",
                            type="success",
                        )

        if inter.data.custom_id.startswith("flight_crew_report_"):
            print(inter.data.custom_id)
            flight = self.db["flights"].find_one(
                {
                    "_id": int(inter.data.custom_id.split("_")[-1]),
                    "status": {"$in": ["Created", "Started"]},
                    "attendants": {"$in": [inter.author.id]},
                }
            )
            if flight:
                return await inter.response.send_modal(
                    modal=FlightCrewReportUserModal(inter)
                )
            else:
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="You are not allowed to report this flight at this time.",
                )

        if inter.data.custom_id == "flight_crew_mp_connect":
            return await self.reply_builder(
                inter,
                title="Multiplayer Connect Gamepass",
                message="This host has the Multiplayer Connect Gamepass, meaning you don't need to own the same aircraft as the host to join the flight!",
            )

        if inter.data.custom_id == "flight_crew_emergency_control":
            return await self.reply_builder(
                inter,
                title="Emergency Control Gamepass",
                message="This host has the Emergency Control Gamepass, meaning the host can cause an emergency during the flight.",
            )

        if inter.data.custom_id.startswith("flight_report_respond_"):
            pass

        if inter.data.custom_id.startswith("flight_report_close_"):
            pass

        if inter.data.custom_id.startswith("flight_crew_attendants_"):
            flight = self.db["flights"].find_one(
                {"_id": int(inter.data.custom_id.split("_")[-1])}
            )
            if flight is None:
                return await self.reply_builder(
                    inter,
                    title="Flight Not Found",
                    message=f'Flight #{inter.data.custom_id.split("_")[-1]} does not exist.',
                )
            else:
                return await self.reply_builder(
                    inter,
                    title=f"Flight #{flight['_id']} Crew",
                    message="\n".join(
                        [
                            self.bot.get_user(user).mention
                            for user in flight["attendants"]
                        ]
                    )
                    if len(flight["attendants"]) > 0
                    else "No one has joined this host's flight.",
                )

    @commands.slash_command(
        name="link_validator",
        description="Checks link validity.",
        guild_ids=[942889868428730369],
        options=[
            disnake.Option(
                name="link",
                description="The link to validate.",
                required=True,
            )
        ],
    )
    async def link_validator_command(
        self, inter: disnake.ApplicationCommandInteraction, link: str
    ):
        await inter.response.defer()
        self.db.logs.insert_one(
            {
                "_id": inter.id,
                "author": inter.author.id,
                "type": "INTERACTION_SLASH",
                "interaction": {
                    "success": inter.command_failed is False,
                    "channel": inter.channel.id,
                    "data": dict(inter.data),
                },
                "timestamp": inter.created_at.utcnow(),
            }
        )
        if inter.response.is_done():
            await inter.edit_original_message(
                embed=Embed(
                    title="Link Validator",
                    description=link,
                    color=disnake.Color.green()
                    if await self.link_validator(link)
                    else disnake.Color.red(),
                )
                .add_field(
                    name="Validity",
                    value="Valid" if await self.link_validator(link) else "Invalid",
                )
                .add_field(name="Type", value=await self.link_validator(link))
            )
        else:
            await inter.followup.send(
                embed=Embed(
                    title="Link Validator",
                    description=link,
                    color=disnake.Color.green()
                    if await self.link_validator(link)
                    else disnake.Color.red(),
                )
                .add_field(
                    name="Validity",
                    value="Valid" if await self.link_validator(link) else "Invalid",
                )
                .add_field(name="Type", value=await self.link_validator(link))
            )

    @commands.slash_command(name="flight", description="Flight Crew Command Group")
    @commands.has_role(1012560028475084870)
    async def flight(self, inter):
        self.db.logs.insert_one(
            {
                "_id": inter.id,
                "author": inter.author.id,
                "type": "INTERACTION_SLASH",
                "interaction": {
                    "success": inter.command_failed is False,
                    "channel": inter.channel.id,
                    "data": dict(inter.data),
                },
                "timestamp": inter.created_at.utcnow(),
            }
        )
        pass

    @flight.sub_command_group(
        name="create", description="The commands to create a Flight Crew Post"
    )
    async def flight_create(self, inter):
        pass

    @flight_create.sub_command(
        name="singleleg",
        description="Create a simple Flight Plan, that consists of only a Departure and Arrival airport.",
        options=[
            disnake.Option(
                name="aircraft",
                description="The aircraft you will be hosting the Flight on",
                choices=commands.option_enum(
                    [aircraft["name"] for aircraft in aircraft_metadata]
                ),
                required=True,
            ),
            disnake.Option(
                name="start_time",
                description="The time the flight will Start",
                choices=commands.option_enum(
                    {
                        "In 5 Minutes": "5",
                        "In 10 Minutes": "10",
                        "In 15 Minutes": "15",
                        "In 20  Minutes": "20",
                    }
                ),
                required=True,
            ),
            disnake.Option(
                name="link",
                description="The link to the flight plan",
                required=True,
            ),
            disnake.Option(
                name="departure_airport",
                description="The airport you will be departing from",
                choices=commands.option_enum(airports),
                required=True,
            ),
            disnake.Option(
                name="arrival_airport",
                description="The airport you will be arriving at",
                choices=commands.option_enum(airports),
                required=True,
            ),
        ],
    )
    async def flight_create_singleleg(
        self,
        inter: disnake.ApplicationCommandInteraction,
        aircraft: str,
        start_time: str,
        link: str,
        departure_airport: str,
        arrival_airport: str,
    ):
        await inter.response.defer()
        if departure_airport == arrival_airport:
            self.flight_create_singleleg.reset_cooldown(inter)
            return await self.reply_builder(
                inter,
                title="Not Allowed",
                message="Departure and Arrival airports cannot be the same.",
                type="error",
            )

        if await self.link_validator(link) is None:
            self.flight_create_multileg.reset_cooldown(inter)
            return await self.reply_builder(
                inter,
                title="Not Allowed",
                message="The link you provided is invalid. Please provide a valid link.",
            )
        flight_plan = await self.flight_plan_builder(
            inter,
            route=[departure_airport, arrival_airport],
        )

        if flight_plan["success"] is False:
            return await self.reply_builder(
                inter,
                title="Error",
                message="**" + flight_plan["message"] + "**",
                type="error",
            )

        success = await self.flight_message_manager(_id=flight_plan["document"]["_id"])

        if (success and flight_plan["success"]) is True:
            return await self.reply_builder(
                inter,
                title="Success",
                message=flight_plan["message"],
                type="success",
            )
        else:
            return await self.reply_builder(
                inter,
                title="Error",
                message="An error occured while creating your Flight Crew Post. Use the interaction ID below when reporting the issue so the developers can fix it.",
                type="error",
            )

    @flight_create.sub_command(
        name="multileg",
        description="Create an advanced Flight Plan, that consists of multiple legs (Maximum 5)",
        options=[
            disnake.Option(
                name="aircraft",
                description="The aircraft you will be hosting the Flight on",
                choices=commands.option_enum(
                    [aircraft["name"] for aircraft in aircraft_metadata]
                ),
                required=True,
            ),
            disnake.Option(
                name="start_time",
                description="The time the flight will Start",
                choices=commands.option_enum(
                    {
                        "In 5 Minutes": "5",
                        "In 10 Minutes": "10",
                        "In 15 Minutes": "15",
                        "In 20  Minutes": "20",
                    }
                ),
                required=True,
            ),
            disnake.Option(
                name="link",
                description="The link to the flight plan",
                required=True,
            ),
            disnake.Option(
                name="origin",
                description="The airport you will be departing from",
                choices=commands.option_enum(airports),
                required=True,
            ),
            disnake.Option(
                name="leg_1",
                description="The airport you will be arriving at, then departing from",
                choices=commands.option_enum(airports),
                required=True,
            ),
            disnake.Option(
                name="leg_2",
                description="The airport you will be arriving at, then possibly departing from",
                choices=commands.option_enum(airports),
                required=True,
            ),
            disnake.Option(
                name="leg_3",
                description="The airport you will be arriving at, then possibly departing from",
                choices=commands.option_enum(airports),
                required=False,
            ),
            disnake.Option(
                name="leg_4",
                description="The airport you will be arriving at, and ending the flight at",
                choices=commands.option_enum(airports),
                required=False,
            ),
        ],
    )
    async def flight_create_multileg(
        self,
        inter: disnake.ApplicationCommandInteraction,
        aircraft: str,
        start_time: str,
        link: str,
        origin: str,
        leg_1: str,
        leg_2: str,
        leg_3: str = "",
        leg_4: str = "",
    ):
        await inter.response.defer()

        # Flight Plan Cleaner

        route = [origin, leg_1, leg_2, leg_3, leg_4]
        route = [leg for leg in route if leg != ""]
        for i in range(len(route) - 1):
            if route[i] == route[i + 1]:
                self.flight_create_multileg.reset_cooldown(inter)
                return await self.reply_builder(
                    inter,
                    title="Not Allowed",
                    message="Consecutive legs cannot be the same as the previous leg.",
                    type="error",
                )

        if len(route) > 5:
            await self.flight_create_multileg.reset_cooldown(inter)
            return await self.reply_builder(
                inter,
                title="Not Allowed",
                message="Multileg Flight Plans cannot have more than 5 legs.",
            )

        if len(route) < 2:
            self.flight_create_multileg.reset_cooldown(inter)
            return await self.reply_builder(
                inter,
                title="Not Allowed",
                message="Multileg Flight Plans cannot have less than 3 legs.",
            )

        if self.link_validator(link) is None:
            self.flight_create_multileg.reset_cooldown(inter)
            return await self.reply_builder(
                inter,
                title="Not Allowed",
                message="The link you provided is invalid. Please provide a valid link.",
            )

        flight_plan = await self.flight_plan_builder(
            inter,
            route=route,
        )

        if flight_plan["success"] is False:
            return await self.reply_builder(
                inter,
                title="Error",
                message="**" + flight_plan["message"] + "**",
                type="error",
            )

        success = await self.flight_message_manager(_id=flight_plan["document"]["_id"])

        if (success and flight_plan["success"]) is True:
            return await self.reply_builder(
                inter,
                title="Success",
                message=flight_plan["message"],
                type="success",
            )
        else:
            return await self.reply_builder(
                inter,
                title="Error",
                message="An error occured while creating your Flight Crew Post. Use the interaction ID below when reporting the issue so the developers can fix it.",
                type="error",
            )

    @flight.sub_command(
        name="cancel",
        description="Cancel a Flight Crew Posting",
    )
    @commands.cooldown(1, 10800, commands.BucketType.user)
    async def flight_cancel(self, inter, flight_id: int):
        pass

    @flight.sub_command(name="stats", description="Get the Flight Crew Stats of a User")
    async def flight_stats(self, inter, user: disnake.User = None):
        pass

    """
    Flight Crew Configuration Commands
    """

    @flight.sub_command_group(
        name="configuration",
        description="Flight Crew Configuration commands, used to configure your Flight Crew Experience",
    )
    async def flight_config(self, inter):
        pass

    @flight_config.sub_command(
        name="minimum_role",
        description="Set the minimum flight role required to join your Flight Crew posts.",
    )
    async def flight_config_minimum_role(self, inter, role: disnake.Role):
        pass

    @flight_config.sub_command(
        name="block",
        description="Block a user from joining your Flight Crew posts.",
    )
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def flight_config_block(
        self, inter: disnake.ApplicationCommandInteraction, user: disnake.User = None
    ):
        if str(user.id) == str(inter.author.id):
            return await inter.response.send_message(
                content="You cannot block yourself!", ephemeral=True
            )

        author = self.db["users"].find_one({"_id": inter.author.id})
        if author["blocklist"] and str(user.id) in author["blocklist"]:
            return await inter.response.send_message(
                content="This user is already blocked!", ephemeral=True
            )
        else:
            self.db["users"].update_one(
                {"_id": inter.author.id}, {"$push": {"blocklist": str(user.id)}}
            )
            return await inter.response.send_message(
                content=f"Blocked {user.mention} from joining your Flight Crew posts!",
                ephemeral=True,
            )

    @flight_config.sub_command(
        name="unblock",
        description="Unblock a user from joining your Flight Crew posts.",
    )
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def flight_config_unblock(
        self, inter: disnake.ApplicationCommandInteraction, user: disnake.User = None
    ):
        if str(user.id) == str(inter.author.id):
            return await inter.response.send_message(
                content="You cannot unblock yourself!", ephemeral=True
            )
        author = self.db["users"].find_one({"_id": inter.author.id})
        if author["blocklist"] and str(user.id) not in author["blocklist"]:
            return await inter.response.send_message(
                content="This user is not blocked!", ephemeral=True
            )
        else:
            self.db["users"].update_one(
                {"_id": inter.author.id},
                {"$pull": {"flight_crew.configuration.blocklist": str(user.id)}},
            )
            return await inter.response.send_message(
                content=f"Unblocked {user.mention} from joining your Flight Crew posts!",
                ephemeral=True,
            )

    @flight_config.sub_command(
        name="blocklist",
        description="View the list of users blocked from joining your Flight Crew posts.",
    )
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def flight_config_blocklist(self, inter):
        user = self.db["users"].find_one({"_id": inter.author.id})
        if (
            not user["flight_crew"]["configuration"]["blocklist"]
            or len(user["flight_crew"]["configuration"]["blocklist"]) == 0
        ):
            return await inter.response.send_message(
                content="You have no users blocked from joining your Flight Crew posts!",
                ephemeral=True,
            )
        else:
            return await inter.response.send_message(
                content=f'You have {len(user["flight_crew"]["configuration"]["blocklist"])} users blocked from joining your Flight Crew posts! ```'
                + "\n".join(user["flight_crew"]["configuration"]["blocklist"])
                + "```",
                ephemeral=True,
            )

    @flight_config.sub_command(
        name="rules", description="Set the rules for your Flight Crew posts."
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def flight_config_rules(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.send_modal(modal=FlightCrewConfigurationRulesModal(inter))

    """
    Flight Crew Admin Group
    """

    @flight.sub_command_group(
        name="admin",
        description="Flight Crew Administration commands, used to manage Flight Crew posts",
    )
    async def flight_admin(self, inter):
        pass

    @flight_admin.sub_command(
        name="delete",
        description="Delete a Flight Crew Posting",
    )
    async def flight_admin_delete(self, inter, flight_id: int):
        pass

    @flight_admin.sub_command(
        name="block",
        description="Block a user from joining a Flight Crew post.",
        options=[
            disnake.Option(
                name="user",
                description="The user to block from joining the Flight Crew post.",
                required=True,
            ),
            disnake.Option(
                name="reason",
                description="The reason for blocking the user from joining the Flight Crew post. (include Case ID)",
                required=True,
            ),
        ],
    )
    async def flight_admin_block(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.User,
        reason: str,
    ):
        user = self.db["users"].find_one({"_id": user.id})
        if user:
            if user["flight_crew"]["abilities"]["joiner"] == True:
                self.db["users"].update_one(
                    {"_id": user.id},
                    {
                        "$set": {
                            "permissions": {
                                "state": False,
                                "reason": reason,
                                "mod": inter.author.id,
                            }
                        }
                    },
                )
                await inter.user.remove_roles(
                    disnake.utils.get(inter.guild.roles, name="Multiplayer")
                )
                return await inter.response.send_message(
                    content=f"Blocked {user.mention} from joining Flight Crew posts!",
                    ephemeral=True,
                )
            else:
                return await inter.response.send_message(
                    content=f'This user is already blocked from joining Flight Crew posts, for the following reason: ```{user["permissions"]["reason"]}```',
                    ephemeral=True,
                )

    @flight.error
    async def flight_error(self, inter: disnake.ApplicationCommandInteraction, error):
        if isinstance(error, commands.CommandOnCooldown):
            return await self.reply_builder(
                inter,
                title="You are on cooldown!",
                message=f"**You will be able to use this command again <t:{datetime.datetime.now().timestamp() + error.retry_after:.0f}:R>.**",
            )
        else:
            try:
                if inter.sub_command_name == "create_single_leg":
                    await self.flight_create_singleleg.reset_cooldown(inter)
                elif inter.sub_command_name == "create_multi_leg":
                    await self.flight_create_multileg.reset_cooldown(inter)
            except:
                pass

            return await self.reply_builder(
                inter,
                title="An error occured!",
                message=f"```{error}```",
                type="error",
            )


def setup(bot):
    bot.add_cog(FlightCrew(bot))
