from os import environ, _exit
environ["PRODUCTION"] = environ["PRODUCTION"] if "PRODUCTION" in environ and environ["PRODUCTION"] else ""

from time import time
from datetime import datetime
from pytz import utc
from requests import post
from asyncio import CancelledError, sleep, gather, wait, create_task
from traceback import format_exc

from discord import AutoShardedBot, Embed, Intents, Activity, Status, ActivityType, MessageType
from discord.ext import tasks
from discord.errors import NotFound
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.cloud.firestore import Client as FirestoreClient
from google.cloud.firestore import Increment
from google.cloud.error_reporting import Client as ErrorReportingClient

from assets import static_storage
from helpers import constants

from DatabaseConnector import DatabaseConnector
from CommandRequest import CommandRequest

from commands.assistant import AlphaCommand
from commands.alerts import AlertCommand
from commands.charts import ChartCommand
from commands.flow import FlowCommand
from commands.schedule import ScheduleCommand
from commands.heatmaps import HeatmapCommand
from commands.depth import DepthCommand
from commands.prices import PriceCommand
from commands.volume import VolumeCommand
from commands.convert import ConvertCommand
from commands.details import DetailsCommand
from commands.lookup import LookupCommand
from commands.paper import PaperCommand
from commands.ichibot import IchibotCommand, Ichibot


database = FirestoreAsyncClient()
logging = ErrorReportingClient(service="discord")
snapshots = FirestoreClient()

BETA_SERVERS = [
	414498292655980583, 849579081800482846, 779004662157934665, 707238867840925706, 493617351216857088, 642039300208459796, 704211103139233893, 710291265689878669, 614609141318680581, 719265732214390816, 788809517818445875, 834195584398524526, 771423228903030804, 778444625639374858, 813915848510537728, 816446013274718209, 807785366526230569, 817764642423177227, 618471986586189865, 663752459424104456, 697085377802010634, 719215888938827776, 726478017924169748, 748813732620009503, 814738213599445013, 856938896713580555, 793014166553755698, 838822602708353056, 837526018088239105, 700113101353123923, 732072413969383444, 784964427962777640, 828430973775511575, 838573421281411122, 625105491743473689, 469530035645317120, 814256366067253268, 848053870197473290, 802692756773273600, 782315810621882369, 597269708345180160, 821150986567548948, 737326609329291335, 746804569303941281, 825933090311503905, 804771454561681439, 827433009598038016, 830534974381752340, 824300337887576135, 747441663193907232, 832625164801802261, 530964559801090079, 831928179299844166, 812819897305399296, 460731020245991424, 829028161983348776, 299922493924311054, 608761795531767814, 336233207269687299, 805453662746968064, 379077201775296513, 785702300886499369, 690135278978859023
]


# -------------------------
# Initialization
# -------------------------

intents = Intents.none()
intents.dm_messages = True
intents.guild_messages = True
intents.guilds = True
intents.integrations = True
intents.webhooks = True

bot = AutoShardedBot(intents=intents, chunk_guilds_at_startup=False, max_messages=None, status=Status.idle, activity=Activity(type=ActivityType.playing, name="a reboot, brb!"))


# -------------------------
# Guild count & management
# -------------------------

@bot.event
async def on_guild_join(guild):
	try:
		if guild.id in constants.bannedGuilds:
			await guild.leave()
			return
		properties = await guild_secure_fetch(guild.id)
		properties.pop("connection", None)
		properties = CommandRequest.create_guild_settings(properties)
		await database.document(f"discord/properties/guilds/{guild.id}").set(properties)
		await update_guild_count()
	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception(user=str(guild.id))

@bot.event
async def on_guild_remove(guild):
	try:
		await update_guild_count()
	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception(user=str(guild.id))

@tasks.loop(minutes=60.0)
async def update_guild_count():
	if environ["PRODUCTION"] and len(bot.guilds) > 24000:
		t = datetime.now().astimezone(utc)
		await database.document("discord/statistics").set({"{}-{:02d}".format(t.year, t.month): {"servers": len(bot.guilds)}}, merge=True)
		post(f"https://top.gg/api/bots/{bot.user.id}/stats", data={"server_count": len(bot.guilds)}, headers={"Authorization": environ["TOPGG_KEY"]})


# -------------------------
# Database management
# -------------------------

def update_alpha_settings(settings, changes, timestamp):
	global alphaSettings
	alphaSettings = settings[0].to_dict()
	botStatus[1] = True

# -------------------------
# Message processing
# -------------------------

def process_alpha_messages(pendingMessages, changes, timestamp):
	if len(changes) == 0 or not environ["PRODUCTION"]: return
	try:
		for change in changes:
			message = change.document.to_dict()
			if change.type.name in ["ADDED", "MODIFIED"]:
				bot.loop.create_task(send_alpha_messages(change.document.id, message))

	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

async def send_alpha_messages(messageId, message):
	try:
		while not botStatus[0]:
			await sleep(60)

		content = None
		embed = Embed(title=message["title"], color=message["color"])
		if message.get("description") is not None: embed.description = message.get("description")
		if message.get("tag") is not None: content = f"<@&{message.get('tag')}>"
		if message.get("subtitle") is not None: embed.set_author(name=message["subtitle"], icon_url=message.get("icon", static_storage.icon))
		if message.get("image") is not None: embed.set_image(url=message["image"])
		if message.get("url") is not None: embed.url = message["url"]

		destinationUser = None
		destinationChannel = None
		backupUser = None
		backupChannel = None
		error = ""

		if message.get("user") is not None:
			try:
				destinationUser = bot.get_user(int(message["user"]))
				if destinationUser is None:
					destinationUser = await bot.fetch_user(int(message["user"]))
			except: print(format_exc())
			try:
				backupChannel = bot.get_channel(int(message["backupChannel"]))
				if backupChannel is None:
					backupChannel = await bot.fetch_channel(int(message["backupChannel"]))
			except: print(format_exc())
		else:
			try:
				destinationChannel = bot.get_channel(int(message["channel"]))
				if destinationChannel is None:
					destinationChannel = await bot.fetch_channel(int(message["channel"]))
			except: print(format_exc())
			try:
				backupUser = bot.get_user(int(message["backupUser"]))
				if backupUser is None:
					backupUser = await bot.fetch_user(int(message["backupUser"]))
			except: print(format_exc())

		if destinationUser is not None:
			try:
				await destinationUser.send(embed=embed)
				await database.document(f"discord/properties/messages/{messageId}").delete()
				return
			except:
				print(format_exc())
		elif destinationChannel is not None:
			try:
				await destinationChannel.send(content=content, embed=embed)
				await database.document(f"discord/properties/messages/{messageId}").delete()
				return
			except Exception as e:
				print(format_exc())
				error = e.text.lower() if hasattr(e, 'text') else str(e)
				print(error)

		if backupChannel is not None:
			try:
				mentionText = f"<@!{message['user']}>, you weren't reachable via DMs!" if destinationUser is None else None
				await backupChannel.send(content=mentionText, embed=embed)
				await database.document(f"discord/properties/messages/{messageId}").delete()
				return
			except:
				print(format_exc())
		elif backupUser is not None:
			try:
				await backupUser.send(content=f"The alert could not be sent into the channel that was initially requested. Reason: `{error}`", embed=embed)
				await database.document(f"discord/properties/messages/{messageId}").delete()
				return
			except:
				print(format_exc())

	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

# -------------------------
# Job functions
# -------------------------

@tasks.loop(minutes=60.0)
async def security_check():
	try:
		guildIds = [str(e.id) for e in bot.guilds]

		for guildId in list(alphaSettings["nicknames"].keys()):
			if guildId not in guildIds:
				alphaSettings["nicknames"].pop(guildId)

		for guild in bot.guilds:
			if guild.id in constants.bannedGuilds:
				await guild.leave()
			if guild.member_count < 10:
				if guildId in alphaSettings["nicknames"]:
					alphaSettings["nicknames"].pop(guildId)
				continue

			guildId = str(guild.id)
			if guild.me is not None:
				if guildId in alphaSettings["nicknames"]:
					if guild.me.nick is None:
						alphaSettings["nicknames"].pop(guildId)
					elif alphaSettings["nicknames"][guildId]["nickname"] != guild.me.nick or alphaSettings["nicknames"][guildId]["server name"] != guild.name:
						alphaSettings["nicknames"][guildId] = {"nickname": guild.me.nick, "server name": guild.name, "allowed": None}
				elif guild.me.nick is not None:
					alphaSettings["nicknames"][guildId] = {"nickname": guild.me.nick, "server name": guild.name, "allowed": None}
			elif guildId in alphaSettings["nicknames"]:
				alphaSettings["nicknames"].pop(guildId)

		if environ["PRODUCTION"]:
			await database.document("discord/settings").set(alphaSettings)

	except CancelledError: pass
	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

@tasks.loop(minutes=15.0)
async def database_sanity_check():
	if not environ["PRODUCTION"]: return
	try:
		guilds = await guildProperties.keys()
		if guilds is None: return

		guildIds = [str(g.id) for g in bot.guilds]

		tasks = []
		for guildId in guilds:
			if guildId not in guildIds:
				tasks.append(database.document(f"discord/properties/guilds/{guildId}").set({"stale": {"count": Increment(1), "timestamp": time()}}, merge=True))

		for guildId in guildIds:
			if guildId not in guilds:
				properties = await guild_secure_fetch(guildId)
				if not properties:
					tasks.append(database.document(f"discord/properties/guilds/{guildId}").set(CommandRequest.create_guild_settings({})))

		await wait(tasks)

	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()

async def guild_secure_fetch(guildId):
	properties = await guildProperties.get(guildId)

	if properties is None:
		properties = await database.document(f"discord/properties/guilds/{guildId}").get()
		properties = properties.to_dict()
		if properties is None: properties = {}

	return properties

# -------------------------
# Message handling
# -------------------------

@bot.event
async def on_message(message):
	try:
		# Skip messages in servers, messages with empty content field, messages from self, or all messages when in startup mode
		if message.guild is not None or message.clean_content == "" or message.type != MessageType.default or message.author == bot.user or not is_bot_ready(): return

		# Ignore if user or server is banned
		if message.author.id in constants.blockedUsers: return

		[accountId, user] = await gather(
			accountProperties.match(message.author.id),
			accountProperties.get(str(message.author.id), {})
		)

		commandRequest = CommandRequest(
			raw=message.clean_content,
			content=message.clean_content.lower(),
			accountId=accountId,
			authorId=message.author.id,
			accountProperties=user,
		)
		_snapshot = "{}-{:02d}".format(message.created_at.year, message.created_at.month)

		if commandRequest.content.startswith("x "):
			await process_ichibot_command(message, commandRequest, commandRequest.content.split(" ", 1)[1])
			await database.document("discord/statistics").set({_snapshot: {"x": Increment(1)}}, merge=True)

	except CancelledError: pass
	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()


# -------------------------
# Ichibot
# -------------------------

async def process_ichibot_command(message, commandRequest, requestSlice):
	sentMessages = []
	try:
		if requestSlice == "login":
			embed = Embed(title=":dart: API key preferences are available in your Alpha Account settings.", description="[Sign into you Alpha Account](https://www.alphabotsystem.com/login) and visit [Ichibot preferences](https://www.alphabotsystem.com/account/trading) to update your API keys.", color=constants.colors["deep purple"])
			embed.set_author(name="Ichibot", icon_url=static_storage.ichibot)
			await message.channel.send(embed=embed)

		elif commandRequest.is_registered():
			origin = f"{commandRequest.accountId}_{commandRequest.authorId}_ichibot"

			if origin in Ichibot.sockets:
				socket = Ichibot.sockets.get(origin)
				await socket.send_multipart([commandRequest.accountId.encode(), b"", commandRequest.raw.split(" ", 1)[1].encode()])

				if requestSlice in ["q", "quit", "exit", "logout"]:
					Ichibot.sockets.pop(origin)
					embed = Embed(title="Ichibot connection has been closed.", color=constants.colors["deep purple"])
					embed.set_author(name="Ichibot", icon_url=static_storage.ichibot)
					await message.channel.send(embed=embed)
			else:
				embed = Embed(title="Ichibot connection is not open.", description="You can initiate a connection with </ichibot login:930915616188166225>.", color=constants.colors["pink"])
				embed.set_author(name="Ichibot", icon_url=static_storage.ichibot)
				missingExchangeMessage = await message.channel.send(embed=embed)

		else:
			embed = Embed(title=":dart: You must have an Alpha Account connected to your Discord to execute live trades.", description="[Sign up for a free account on our website](https://www.alphabotsystem.com/signup). If you already signed up, [sign in](https://www.alphabotsystem.com/login), connect your account with your Discord profile, and add an API key.", color=constants.colors["deep purple"])
			embed.set_author(name="Ichibot", icon_url=static_storage.ichibot)
			await message.channel.send(embed=embed)

	except CancelledError: pass
	except Exception:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception(user=f"{message.author.id}: {message.clean_content}")
		await unknown_error(message, commandRequest.authorId)
	return (sentMessages, len(sentMessages))


# -------------------------
# Slash command request
# -------------------------

async def create_request(ctx, autodelete=-1, ephemeral=False):
	authorId = ctx.author.id
	guildId = ctx.guild.id if ctx.guild is not None else -1
	channelId = ctx.channel.id if ctx.channel is not None else -1

	# Ignore if user if locked in a prompt, or banned
	if authorId in constants.blockedUsers or guildId in constants.blockedGuilds: return

	[accountId, user, guild] = await gather(
		accountProperties.match(authorId),
		accountProperties.get(str(authorId), {}),
		guildProperties.get(guildId, {})
	)

	if ctx.command.qualified_name == "alpha":
		ephemeral = not guild.get("settings", {}).get("assistant", {}).get("enabled", True)

	try: await ctx.defer(ephemeral=ephemeral)
	except: return

	request = CommandRequest(
		accountId=accountId,
		authorId=authorId,
		channelId=channelId,
		guildId=guildId,
		accountProperties=user,
		guildProperties=guild,
		autodelete=autodelete
	)

	if request.guildId != -1:
		branding = alphaSettings["nicknames"].get(str(request.guildId), {"allowed": True, "nickname": None})
		if branding["allowed"] == False and ctx.guild.me.nick == branding["nickname"]:
			embed = Embed(title="This Discord community guild was flagged for re-branding Alpha Bot and is therefore violating the Terms of Service. Inability to comply will result in termination of all Alpha branded services.", description="If you wish to present the bot with your own branding, you have to purchase a [Bot License](https://www.alphabotsystem.com/pro/bot-license)", color=0x000000)
			embed.add_field(name="Terms of service", value="[Read now](https://www.alphabotsystem.com/terms-of-service)", inline=True)
			embed.add_field(name="Alpha Bot support Discord server", value="[Join now](https://discord.gg/GQeDE85)", inline=True)
			try: await ctx.interaction.edit_original_response(embed=embed)
			except NotFound: pass
			return None
		elif not request.guildProperties["settings"]["setup"]["completed"]:
			forceFetch = await database.document(f"discord/properties/guilds/{request.guildId}").get()
			forcedFetch = CommandRequest.create_guild_settings(forceFetch.to_dict())
			if forcedFetch["settings"]["setup"]["completed"]:
				request.guildProperties = forcedFetch
				return request
			elif not ctx.bot and ctx.interaction.channel.permissions_for(ctx.author).administrator:
				embed = Embed(title="Hello world!", description="Thanks for adding Alpha Bot to your Discord community, we're thrilled to have you onboard. We think you're going to love everything Alpha Bot can do. Before you start using it, you must complete a short setup process. Sign into your [Alpha Account](https://www.alphabotsystem.com/communities) and visit your [Communities Dashboard](https://www.alphabotsystem.com/communities) to begin.", color=constants.colors["pink"])
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass
			else:
				embed = Embed(title="Hello world!", description="This is Alpha Bot, the most popular financial bot on Discord. A short setup process hasn't been completed in this Discord community yet. Ask administrators to complete it by signing into their [Alpha Account](https://www.alphabotsystem.com/communities) and visiting their [Communities Dashboard](https://www.alphabotsystem.com/communities).", color=constants.colors["pink"])
				try: await ctx.interaction.edit_original_response(embed=embed)
				except NotFound: pass
			return None

	return request


# -------------------------
# Slash commands
# -------------------------

bot.add_cog(AlphaCommand(bot, create_request, database, logging))
bot.add_cog(AlertCommand(bot, create_request, database, logging))
bot.add_cog(ChartCommand(bot, create_request, database, logging))
# bot.add_cog(FlowCommand(bot, create_request, database, logging))
bot.add_cog(ScheduleCommand(bot, create_request, database, logging))
bot.add_cog(HeatmapCommand(bot, create_request, database, logging))
bot.add_cog(DepthCommand(bot, create_request, database, logging))
bot.add_cog(PriceCommand(bot, create_request, database, logging))
bot.add_cog(VolumeCommand(bot, create_request, database, logging))
bot.add_cog(ConvertCommand(bot, create_request, database, logging))
bot.add_cog(DetailsCommand(bot, create_request, database, logging))
bot.add_cog(LookupCommand(bot, create_request, database, logging))
bot.add_cog(PaperCommand(bot, create_request, database, logging))
bot.add_cog(IchibotCommand(bot, create_request, database, logging))


# -------------------------
# Error handling
# -------------------------

async def unknown_error(ctx, authorId):
	embed = Embed(title="Looks like something went wrong. The issue has been reported.", color=constants.colors["gray"])
	embed.set_author(name="Something went wrong", icon_url=static_storage.icon_bw)
	try: await ctx.channel.send(embed=embed)
	except: return


# -------------------------
# Startup
# -------------------------

botStatus = [False, False]

alphaSettings = {}
accountProperties = DatabaseConnector(mode="account")
guildProperties = DatabaseConnector(mode="guild")
Ichibot.logging = logging

discordSettingsLink = snapshots.document("discord/settings").on_snapshot(update_alpha_settings)
discordMessagesLink = snapshots.collection("discord/properties/messages").on_snapshot(process_alpha_messages)

@bot.event
async def on_ready():
	print("[Startup]: Alpha Bot is online")

	try:
		while not await accountProperties.check_status() or not await guildProperties.check_status():
			await sleep(15)
		botStatus[0] = True
		await bot.change_presence(status=Status.online, activity=Activity(type=ActivityType.watching, name="alphabotsystem.com"))
	except:
		print(format_exc())
		if environ["PRODUCTION"]: logging.report_exception()
		_exit(1)

	if not update_guild_count.is_running():
		update_guild_count.start()
	if not security_check.is_running():
		security_check.start()
	if not database_sanity_check.is_running():
		database_sanity_check.start()

	print("[Startup]: Alpha Bot startup complete")

def is_bot_ready():
	return all(botStatus)


# -------------------------
# Login
# -------------------------

token = environ["DISCORD_PRODUCTION_TOKEN" if environ["PRODUCTION"] else "DISCORD_DEVELOPMENT_TOKEN"]
bot.loop.run_until_complete(bot.start(token))