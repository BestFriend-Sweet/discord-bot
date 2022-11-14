from os import environ
from time import time
from pytz import utc
from uuid import uuid4
from datetime import datetime, timedelta
from parsedatetime import Calendar
from random import randint
from asyncio import CancelledError, sleep
from traceback import format_exc

from discord import Embed, File, ButtonStyle, SelectOption, Interaction, PartialEmoji
from discord.commands import slash_command, SlashCommandGroup, Option
from discord.ui import View, button, Button, Select
from discord.errors import NotFound
from google.cloud.firestore import Increment

from helpers import constants
from assets import static_storage
from Processor import process_chart_arguments, process_task
from DatabaseConnector import DatabaseConnector

from commands.base import BaseCommand, Confirm
from commands.ichibot import Ichibot


cal = Calendar()
PERIODS = ["5 minutes", "10 minutes", "15 minutes", "20 minutes", "30 minutes", "1 hour", "2 hours", "3 hours", "4 hours", "6 hours", "8 hours", "12 hours", "1 day"]
PERIOD_TO_TIME = {"5 minutes": 5, "10 minutes": 10, "15 minutes": 15, "20 minutes": 20, "30 minutes": 30, "hour": 60, "2 hours": 120, "3 hours": 180, "4 hours": 240, "6 hours": 360, "8 hours": 480, "12 hours": 720, "day": 1440}
TIME_TO_PERIOD = {value: key for key, value in PERIOD_TO_TIME.items()}


def autocomplete_period(ctx):
	period = " ".join(ctx.options.get("period", "").lower().split())
	options = []
	for option in PERIODS:
		if period == "" or period in option.replace(" ", ""):
			options.append(option)
	return options

def autocomplete_date(ctx):
	date = " ".join(ctx.options.get("start", "").lower().split())
	if date == "":
		options = [datetime.now().strftime("%d/%m/%Y %H:%M") + " UTC"]
		return options
	else:
		timeStructs, _ = cal.parse(date)
		parsed = datetime(*timeStructs[:5])
		if parsed < datetime.now(): parsed += timedelta(days=1)
		options = [parsed.strftime("%d/%m/%Y %H:%M") + " UTC"]
		return options


class ScheduleCommand(BaseCommand):
	scheduleGroup = SlashCommandGroup("schedule", "Schedule Alpha Bot commands to post periodically.")

	@scheduleGroup.command(name="chart", description="Schedule a chart to post periodically.")
	async def chart(
		self,
		ctx,
		arguments: Option(str, "Request arguments starting with ticker id.", name="arguments"),
		period: Option(str, "Period of time every which the chart will be posted.", name="period", autocomplete=autocomplete_period),
		start: Option(str, "Time at which the first chart will be posted.", name="start", autocomplete=autocomplete_date, required=False, default=datetime.now().strftime("%d/%m/%Y %H:%M") + " UTC")
	):
		try:
			request = await self.create_request(ctx, ephemeral=True)
			if request is None: return

			posts = await self.database.collection(f"details/scheduledPosts/{request.guildId}").get()
			totalPostCount = len(posts)

			if not ctx.channel.permissions_for(ctx.author).manage_messages:
				embed = Embed(title="You do not have the sufficient permission to create a scheduled post.", description="To be able to create a scheduled post, you must have the `manage messages` permission.", color=constants.colors["red"])
				embed.set_author(name="Permission denied", icon_url=static_storage.icon_bw)
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass

			if totalPostCount >= 10:
				embed = Embed(title="You can only create up to 10 scheduled posts per community. Remove some before creating new ones by calling </schedule list:1041362666872131675>", color=constants.colors["red"])
				embed.set_author(name="Maximum number of scheduled posts reached", icon_url=static_storage.icon_bw)
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass

			elif request.scheduled_posting_available():
				defaultPlatforms = request.get_platform_order_for("c")
				period = period.lower()

				if len(arguments.split(",")) > 1:
					embed = Embed(title="Only one request is allowed to be scheduled at once.", color=constants.colors["gray"])
					embed.set_author(name="Too many requests", icon_url=static_storage.icon_bw)
					try: await ctx.interaction.edit_original_response(embed=embed)
					except NotFound: pass
					return
				elif period not in PERIODS:
					embed = Embed(title="The provided period is not valid. Please pick one of the available periods.", color=constants.colors["gray"])
					embed.set_author(name="Invalid period", icon_url=static_storage.icon_bw)
					try: await ctx.interaction.edit_original_response(embed=embed)
					except NotFound: pass
					return

				try:
					timestamp = datetime.strptime(start, "%d/%m/%Y %H:%M UTC").timestamp()
				except:
					embed = Embed(title="The provided start date is not valid. Please provide a valid date and time.", color=constants.colors["gray"])
					embed.set_author(name="Invalid start time", icon_url=static_storage.icon_bw)
					try: await ctx.interaction.edit_original_response(embed=embed)
					except NotFound: pass
					return

				while timestamp < time():
					timestamp += PERIOD_TO_TIME[period] * 60

				arguments = arguments.lower().split()
				responseMessage, task = await process_chart_arguments(arguments[1:], defaultPlatforms, tickerId=arguments[0].upper())

				if responseMessage is not None:
					description = "[Advanced Charting add-on](https://www.alphabotsystem.com/pro/advanced-charting) unlocks additional assets, indicators, timeframes and more." if responseMessage.endswith("add-on.") else "Detailed guide with examples is available on [our website](https://www.alphabotsystem.com/features/charting)."
					embed = Embed(title=responseMessage, description=description, color=constants.colors["gray"])
					embed.set_author(name="Invalid argument", icon_url=static_storage.icon_bw)
					try: await ctx.interaction.edit_original_response(embed=embed)
					except NotFound: pass
					return
				elif task.get("requestCount") > 1:
					embed = Embed(title="Only one timeframe is allowed per request when scheduling a post.", color=constants.colors["gray"])
					embed.set_author(name="Too many requests", icon_url=static_storage.icon_bw)
					try: await ctx.interaction.edit_original_response(embed=embed)
					except NotFound: pass
					return

				currentTask = task.get(task.get("currentPlatform"))
				timeframes = task.pop("timeframes")
				for p, t in timeframes.items(): task[p]["currentTimeframe"] = t[0]
				payload, responseMessage = await process_task(task, "chart")

				files, embeds = [], []
				if responseMessage == "requires pro":
					embed = Embed(title=f"The requested chart for `{currentTask.get('ticker').get('name')}` is only available on TradingView Premium.", description="All TradingView Premium charts are bundled with the [Advanced Charting add-on](https://www.alphabotsystem.com/pro/advanced-charting).", color=constants.colors["gray"])
					embed.set_author(name="Invalid argument", icon_url=static_storage.icon_bw)
					embeds.append(embed)
				elif payload is None:
					errorMessage = f"Requested chart for `{currentTask.get('ticker').get('name')}` is not available." if responseMessage is None else responseMessage
					embed = Embed(title=errorMessage, color=constants.colors["gray"])
					embed.set_author(name="Chart not available", icon_url=static_storage.icon_bw)
					embeds.append(embed)
				else:
					files.append(File(payload.get("data"), filename="{:.0f}-{}-{}.png".format(time() * 1000, request.authorId, randint(1000, 9999))))

				confirmation = None if payload.get("data") is None else Confirm(user=ctx.author)
				try: await ctx.interaction.edit_original_response(embeds=embeds, files=files, view=confirmation)
				except NotFound: pass
				await confirmation.wait()

				if confirmation is None:
					return
				if confirmation.value is None or not confirmation.value:
					try: await ctx.interaction.delete_original_response()
					except NotFound: pass
					return

				await self.database.document(f"details/scheduledPosts/{request.guildId}/{str(uuid4())}").set({
					"command": "chart",
					"arguments": arguments,
					"authorId": request.authorId,
					"channelId": request.channelId,
					"period": PERIOD_TO_TIME[period],
					"start": timestamp
				})

				try: await ctx.interaction.edit_original_response(view=None)
				except NotFound: pass

				embed = Embed(title="Scheduled post has been created.", description=f"The scheduled chart will be posted every `{period.removeprefix('1 ')}` in this channel, starting at `{start}`.", color=constants.colors["purple"])
				embed.set_author(name="Chart scheduled", icon_url=static_storage.icon)
				await ctx.followup.send(embed=embed, ephemeral=True)
			else:
				embed = Embed(title=":gem: Scheduled Posting functionality is available as an add-on subscription for communities for only $2.00 per month.", description="If you'd like to start your 30-day free trial, visit [our website](https://www.alphabotsystem.com/pro/scheduled-posting).", color=constants.colors["deep purple"])
				# embed.set_image(url="https://www.alphabotsystem.com/files/uploads/pro-hero.jpg")
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass

		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION"]: self.logging.report_exception(user=f"{ctx.author.id} {ctx.guild.id if ctx.guild is not None else -1}: /schedule chart {arguments} period:{period} start:{start}")
			await self.unknown_error(ctx)

	@scheduleGroup.command(name="list", description="List all scheduled posts.")
	async def schedule_list(self, ctx):
		try:
			request = await self.create_request(ctx, ephemeral=True)
			if request is None: return

			response = await self.database.collection(f"details/scheduledPosts/{request.guildId}").get()
			posts = [(p.id, p.to_dict()) for p in response]
			totalPostCount = len(posts)

			if totalPostCount == 0:
				embed = Embed(title="You haven't set any scheduled posts yet.", color=constants.colors["gray"])
				embed.set_author(name="Scheduled Posts", icon_url=static_storage.icon_bw)
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass

			else:
				embed = Embed(title=f"You've created {totalPostCount} scheduled post{'' if totalPostCount == 1 else 's'} in this community.", color=constants.colors["light blue"])
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass

				for key, post in posts:
					timestamp = post["start"]
					while timestamp < time(): timestamp += post["period"]
					nextPost = datetime.fromtimestamp(timestamp, tz=utc).strftime("%d/%m/%Y %H:%M")
					embed = Embed(title=f"Post a {post['command']} every {TIME_TO_PERIOD[post['period']]} starting at {nextPost} UTC.", description=f"Request: `{' '.join(post['arguments'])}`\nChannel: <#{post['channelId']}>\nScheduled by <@{post['authorId']}>", color=constants.colors["deep purple"])
					await ctx.followup.send(embed=embed, view=DeleteView(database=self.database, pathId=f"details/scheduledPosts/{request.guildId}/{key}", userId=request.authorId), ephemeral=True)

		except CancelledError: pass
		except Exception:
			print(format_exc())
			if environ["PRODUCTION"]: self.logging.report_exception(user=f"{ctx.author.id} {ctx.guild.id if ctx.guild is not None else -1}: /schedule list")
			await self.unknown_error(ctx)


class DeleteView(View):
	def __init__(self, database, pathId, userId=None):
		super().__init__(timeout=None)
		self.database = database
		self.pathId = pathId
		self.userId = userId

	@button(label="Delete", style=ButtonStyle.danger)
	async def delete(self, button: Button, interaction: Interaction):
		if self.userId != interaction.user.id: return
		await self.database.document(self.pathId).delete()
		embed = Embed(title="Scheduled post deleted", color=constants.colors["gray"])
		await interaction.response.edit_message(embed=embed, view=None)