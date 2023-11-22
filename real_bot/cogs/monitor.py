from discord.ext import commands, tasks
import discord
from typing import Union, Mapping, List, Tuple, Optional
from datetime import datetime
from util.checks import is_guild_owner
from util.page import PageView
import requests
import dotenv


class Monitor(commands.Cog):
    """
    Cog for interfacing with the physical hardware monitor.
    In general, the monitor should be used in the following way:

    `-link (channel)`
    """

    def __init__(
        self,
        bot: commands.Bot,
        refresh_rate: Optional[int] = 1,
        num_per_page: Optional[int] = 10,
        max_history_len: Optional[int] = 1000,
    ) -> None:
        """
        Initialize the Monitor cog

        Arguments:
            - bot: commands.Bot - the bot that owns this cog
            - refresh_rate: Optional[int] - how often to check the status of the door
            - num_per_page: Optional[int] - the number of history entries to show per page
            - max_history_len: Optional[int] - the total number of history entries to store
        """
        super().__init__()
        self.bot = bot

        # maps from the guild id to the message that was sent
        self.messages: Mapping[int, discord.Message] = {}

        self.refresh_rate = refresh_rate
        self.num_per_page = num_per_page
        self.max_history_len = max_history_len

        self.history: List[Tuple[int, str]] = []
        self.emojis = {"Open": ":unlock:", "Closed": ":lock:"}

        self.task = tasks.Loop(
            self.send_announcement,
            seconds=self.refresh_rate,
            hours=tasks.MISSING,
            minutes=tasks.MISSING,
            time=tasks.MISSING,
            count=None,
            reconnect=True,
        )

    async def create_status_embed(
        self, door_open: bool
    ) -> Tuple[discord.Embed, discord.File]:
        """
        Create the status embed to display the door status

        Arguments:
            - door_open: bool - whether or not the door is open
        """
        embed = discord.Embed(title="CS Club Door Status")
        file = discord.File(fp="logo.png", filename="logo.png")
        embed.set_thumbnail(url="attachment://logo.png")
        timestamp = f"<t:{int(datetime.now().timestamp())}>"

        if door_open:
            embed.color = discord.Colour.green()
            embed.description = f"MQH 227 is now open - {timestamp}"
        else:
            embed.color = discord.Colour.red()
            embed.description = f"MQH 227 is now closed - {timestamp}"

        return embed, file

    async def send_announcement(self):
        """
        Sends an announcement on the status of the door
        to the channel that the bot's door monitor is linked
        to. If the bot's door monitor isn't linked to a channel,
        nothing will happen.
        """
        # get the door status
        try:
            door_status = requests.get(dotenv.dotenv_values()["DOOR_URL"])
            door_open = door_status.json()["door"][0]["open"]
        except Exception as e:
            print("Couldn't get door status because", e)
            door_open = False

        m = {False: "Closed", True: "Open"}
        if len(self.history) > 0 and m[door_open] == self.history[-1][1]:
            # don't do anything if the status is the same
            return

        for guild in self.messages:
            embed, _ = await self.create_status_embed(door_open)
            self.messages[guild] = await self.messages[guild].edit(embed=embed)

        self.history.append((int(datetime.now().timestamp()), m[door_open]))
        if len(self.history) > self.max_history_len:
            self.history = self.history[1:]

    @commands.command(name="linkMonitor", aliases=["link"])
    @commands.check_any(is_guild_owner(), commands.is_owner())
    async def link_channel(
        self, ctx: commands.Context, channel: Union[discord.TextChannel, str]
    ):
        """
        Set the bot up to send door monitor announcements to the given channel.
        This is necessary to see output after starting the monitor

        Examples:
            `-linkMonitor announcements`
            `-linkMonitor #announcements` where #announcements is the mention for the announcements text channel

        Arguments:
            channel - either the name of the channel or the channel's mention
        """
        if type(channel) == str:
            await ctx.send(
                f"Sorry, couldn't find the channel {channel}. Please try again, and make sure there aren't any typos."
            )
        else:
            if len(self.history) > 0:
                val = self.history[-1][1]
            else:
                val = False

            embed, file = await self.create_status_embed(val)
            self.messages[ctx.guild.id] = await channel.send(embed=embed, file=file)
            await ctx.send(
                f"Now using {channel.mention} as the place to send announcements"
            )

    @commands.command(name="testLink", aliases=["test"])
    @commands.check_any(is_guild_owner(), commands.is_owner())
    async def test_link(self, ctx: commands.Context):
        """
        Test if the bot is correctly set up to send door monitor announcements to the given channel
        """
        if ctx.guild.id in self.messages:
            await ctx.send(
                f"Correctly linked to send door monitor announcements to {self.messages[ctx.guild.id].channel.mention}"
            )
        else:
            await ctx.send(
                "Not linked to any channel. Use `-linkMonitor` to link the door monitor to a channel."
            )

    @commands.command(name="startMonitor", aliases=["start"])
    @commands.is_owner()
    async def start_monitor(self, ctx: commands.Context):
        """
        Start the physical monitor so that updates on the door status
        will be sent to the channel that this bot is set to send
        door announcements to.
        """
        self.task.start()
        await ctx.send("Started monitoring door status.")

    @commands.command(name="stopMonitor", aliases=["stop"])
    @commands.is_owner()
    async def stop_monitor(self, ctx: commands.Context):
        """
        Stop the physical monitor, stopping all door announcement messages as well.
        """
        self.task.stop()
        await ctx.send("Stopped monitoring door status.")

    async def get_page(self, page: int):
        """
        Get the embed that displays the `page` page of the history

        Arguments:
            - page: int - the page (0 indexed) to display the history for
        """
        embed = discord.Embed(
            title="Door History", description="", color=discord.Colour.blurple()
        )

        start = -(page + 1) * self.num_per_page
        end = -page * self.num_per_page if page != 0 else len(self.history)

        for timestamp, state in reversed(self.history[start:end]):
            embed.description += f"{self.emojis[state]} {state} - <t:{timestamp}>\n"

        embed.set_footer(text=f"Showing page {page+1}/{self.get_total_pages()}")
        return embed

    def get_total_pages(self):
        """
        Return the total number of pages that the history command will have
        """
        return len(self.history) // self.num_per_page + (
            1 if (len(self.history) % self.num_per_page) != 0 else 0
        )

    @commands.command(name="history")
    async def get_history(self, ctx: commands.Context):
        """
        Get the history of when the door was opened/closed.
        """
        await ctx.send(
            embed=await self.get_page(0),
            view=PageView(
                user=ctx.author,
                get_page=self.get_page,
                get_total_pages=self.get_total_pages,
                timeout=20,
            ),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Monitor(bot))