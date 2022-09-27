from asyncio import sleep
from re import sub

from discord import Embed, ButtonStyle, Interaction, PartialEmoji
from discord.ext.commands import Cog
from discord.ui import View, button, Button

from helpers import constants
from assets import static_storage
from Processor import autocomplete_ticker, autocomplete_venues


class BaseCommand(Cog):
	commandMap = {
		"chart": "c",
		"price": "p"
	}

	sources = {
		"alert": ["IEXC", "CCXT"],
		"c": ["TradingView", "TradingView Premium", "Finviz", "TradingLite", "GoCharting", "Bookmap"],
		"hmap": ["TradingView Stock Heatmap", "TradingView Crypto Heatmap"],
		"flow": ["Alpha Flow"],
		"p": ["IEXC", "CCXT", "CoinGecko"],
		"convert": ["IEXC", "CCXT", "CoinGecko"],
		"volume": ["IEXC", "CoinGecko", "CCXT"],
		"depth": ["IEXC", "CCXT"],
		"info": ["IEXC", "CoinGecko"],
		"paper": ["IEXC", "CCXT"],
		"ichibot": ["Ichibot"]
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

	async def unknown_error(self, ctx):
		embed = Embed(title="Looks like something went wrong. The issue has been reported.", color=constants.colors["gray"])
		embed.set_author(name="Something went wrong", icon_url=static_storage.icon_bw)
		try: await ctx.interaction.edit_original_message(content=None, embed=embed, files=[])
		except: return

	async def autocomplete_from_ticker(cls, ctx):
		return await cls.autocomplete_ticker(ctx, "from")

	async def autocomplete_to_ticker(cls, ctx):
		return await cls.autocomplete_ticker(ctx, "to")

	async def autocomplete_ticker(cls, ctx, mode="ticker"):
		_commandName = ctx.command.name if ctx.command.parent is None else ctx.command.parent.name
		command = cls.commandMap.get(_commandName, _commandName)
		tickerId = " ".join(ctx.options.get(mode, "").lower().split()).split("|")[0]

		if tickerId == "": return []

		platforms = cls.sources.get(command)
		tickers = await autocomplete_ticker(tickerId, ",".join(platforms))
		return tickers

	async def autocomplete_venues(cls, ctx):
		_commandName = ctx.command.name if ctx.command.parent is None else ctx.command.parent.name
		command = cls.commandMap.get(_commandName, _commandName)
		tickerId = " ".join(ctx.options.get("ticker", "").lower().split()).split("|")[0]
		venue = " ".join(ctx.options.get("venue", "").lower().split())

		if command == "ichibot": tickerId = "btc"
		elif tickerId == "": return []

		platforms = cls.sources.get(command)
		venues = await autocomplete_venues(tickerId, ",".join(platforms))
		return sorted([v for v in venues if v.lower().startswith(venue)])

class Confirm(View):
	def __init__(self, user=None):
		super().__init__(timeout=None)
		self.user = user
		self.value = None

	@button(label="Confirm", style=ButtonStyle.primary)
	async def confirm(self, button: Button, interaction: Interaction):
		if self.user.id != interaction.user.id: return
		self.value = True
		self.stop()

	@button(label="Cancel", style=ButtonStyle.secondary)
	async def cancel(self, button: Button, interaction: Interaction):
		if self.user.id != interaction.user.id: return
		self.value = False
		self.stop()


class ActionsView(View):
	def __init__(self, user=None):
		super().__init__(timeout=None)
		self.user = user

	@button(emoji=PartialEmoji.from_str("<:remove_response:929342678976565298>"), style=ButtonStyle.gray)
	async def delete(self, button: Button, interaction: Interaction):
		if self.user.id != interaction.user.id:
			if not interaction.permissions.manage_messages: return
			embed = Embed(title="Chart has been removed by a moderator.", description=f"{interaction.user.mention} has removed the chart requested by {self.user.mention}.", color=constants.colors["pink"])
			await interaction.response.send_message(embed=embed)
		try: await interaction.message.delete()
		except: return