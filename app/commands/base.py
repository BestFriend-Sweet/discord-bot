from asyncio import sleep

from discord import ButtonStyle, Interaction
from discord.ext.commands import Cog
from discord.ui import View, button, Button

from Processor import Processor
from TickerParser import TickerParser


class BaseCommand(Cog):
	commandMap = {
		"price": "p",
		"volume": "v",
		"depth": "d"
	}

	sources = {
		"alert": {
			"stocks": ["IEXC"],
			"crypto": ["CCXT"]
		},
		"c": {
			"stocks": ["TradingView", "GoCharting", "Finviz"],
			"forex": ["TradingView", "Finviz"],
			"other": ["TradingView", "Finviz"],
			"crypto": ["TradingView", "TradingLite", "GoCharting", "Bookmap"]
		},
		"p": {
			"stocks": ["IEXC"],
			"forex": ["IEXC", "CoinGecko"],
			"crypto": ["CoinGecko", "CCXT"]
		},
		"v": {
			"stocks": ["IEXC"],
			"crypto": ["CoinGecko", "CCXT"]
		},
		"d": {
			"stocks": ["IEXC"],
			"crypto": ["CCXT"]
		},
		"info": {
			"stocks": ["IEXC"],
			"crypto": ["CoinGecko"]
		},
		"paper": {
			"stocks": ["IEXC"],
			"crypto": ["CCXT"]
		}
	}

	def __init__(self, bot, create_request, database, logging):
		self.bot = bot
		self.create_request = create_request
		self.database = database
		self.logging = logging

	async def cleanup(self, ctx, request, removeView=False):
		if request.autodelete is not None:
			await ctx.interaction.delete_original_message(delay=request.autodelete * 60)
		if removeView:
			await sleep(600)
			try: await ctx.interaction.edit_original_message(view=None)
			except: pass

	async def get_types(cls, ctx):
		_commandName = ctx.command.name if ctx.command.parent is None else ctx.command.parent.name
		command = cls.commandMap.get(_commandName, _commandName)
		assetType = " ".join(ctx.options.get("type", "").lower().split())
		venue = " ".join(ctx.options.get("venue", "").lower().split())

		venues = await TickerParser.get_venues("", "")
		venueType = [v for v in venues if v.lower().startswith(venue)]

		return sorted([s for s in cls.sources.get(command) if s.lower().startswith(assetType) and (venue == "" or s in venueType)])

	async def get_venues(cls, ctx):
		_commandName = ctx.command.name if ctx.command.parent is None else ctx.command.parent.name
		command = cls.commandMap.get(_commandName, _commandName)
		tickerId = " ".join(ctx.options.get("ticker", "").lower().split())
		assetType = " ".join(ctx.options.get("type", "").lower().split())
		venue = " ".join(ctx.options.get("venue", "").lower().split())

		if assetType == "" or tickerId == "": return []
		platforms = cls.sources.get(command).get(assetType, [])
		if len(platforms) == 0: return []
		venues = await TickerParser.get_venues(",".join(platforms), tickerId)

		return sorted([v for v in venues if v.lower().startswith(venue)])


class Confirm(View):
	def __init__(self):
		super().__init__(timeout=None)
		self.value = None

	@button(label="Confirm", style=ButtonStyle.primary)
	async def confirm(self, button: Button, interaction: Interaction):
		self.value = True
		self.stop()

	@button(label="Cancel", style=ButtonStyle.secondary)
	async def cancel(self, button: Button, interaction: Interaction):
		self.value = False
		self.stop()