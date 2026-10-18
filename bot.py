import logging
import os

import discord
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

from api import ValorantAPI
from storage import LinkStorage

log = logging.getLogger("valtracker")

PREFIXES = ("valtrack!", "vt!")  # yang pertama dipakai di docs/help


def get_prefix(bot: commands.Bot, message: discord.Message) -> list[str]:
    # Nggak peka huruf besar/kecil, biar "Valtrack!" dari autocapitalize HP tetap jalan
    content = message.content.lower()
    prefixes = [message.content[: len(p)] for p in PREFIXES if content.startswith(p)]
    return commands.when_mentioned_or(*prefixes)(bot, message)


class ValTrackerBot(commands.Bot):
    def __init__(self, api: ValorantAPI, storage: LinkStorage):
        intents = discord.Intents.default()
        intents.message_content = True  # wajib buat command prefix valtrack!
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=None,  # diganti help buatan sendiri di cogs/valorant.py
            case_insensitive=True,
            strip_after_prefix=True,  # "valtrack! track" juga jalan
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, replied_user=False),
        )
        self.api = api
        self.storage = storage
        self.prefixes = PREFIXES
        self.web_runner: web.AppRunner | None = None

    async def setup_hook(self) -> None:
        await self.api.start()
        await self.load_extension("cogs.valorant")
        await self.start_health_server()

        # Sync ke satu server dulu biar slash command langsung muncul (global sync bisa lama).
        guild_id = os.getenv("DEV_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info("Synced %d slash command(s)", len(synced))

    async def start_health_server(self) -> None:
        # Hosting tipe web service (misal Render free) mewajibkan app buka port HTTP.
        # PORT di-set otomatis oleh hosting-nya; kalau jalan lokal, server ini nggak dinyalakan.
        port = os.getenv("PORT")
        if not port:
            return

        async def health(_request: web.Request) -> web.Response:
            return web.Response(text="ok" if self.is_ready() else "starting")

        app = web.Application()
        app.router.add_get("/", health)
        self.web_runner = web.AppRunner(app, access_log=None)
        await self.web_runner.setup()
        await web.TCPSite(self.web_runner, "0.0.0.0", int(port)).start()
        log.info("Health check jalan di port %s", port)

    async def on_ready(self) -> None:
        log.info("Login sebagai %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(f"VALORANT | {PREFIXES[0]}help"))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Cuma di-mention tanpa command: kasih petunjuk
        if message.content.strip() in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
            await message.reply(
                f"Halo! Ketik `{PREFIXES[0]}help` atau `/help` buat lihat cara pakai.\n"
                f"Contoh: `{PREFIXES[0]}track Nama#TAG`"
            )
            return
        await self.process_commands(message)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            await ctx.reply(
                f"Command `{ctx.invoked_with}` nggak dikenal. Ketik `{ctx.clean_prefix}help` buat lihat daftarnya."
            )
            return
        if ctx.cog and ctx.cog.has_error_handler():
            return  # sudah ditangani cog
        await super().on_command_error(ctx, error)

    async def close(self) -> None:
        if self.web_runner:
            await self.web_runner.cleanup()
        await self.api.close()
        await super().close()


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    api_key = os.getenv("HENRIK_API_KEY")
    if not token or not api_key:
        raise SystemExit("DISCORD_TOKEN dan HENRIK_API_KEY wajib diisi di file .env")

    discord.utils.setup_logging(level=logging.INFO)
    # LINKS_PATH buat naruh links.json di persistent disk kalau di-deploy
    bot = ValTrackerBot(ValorantAPI(api_key), LinkStorage(os.getenv("LINKS_PATH") or "links.json"))
    try:
        bot.run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        raise SystemExit(
            "Message Content Intent belum aktif. Buka https://discord.com/developers/applications → "
            "pilih bot → tab Bot → nyalakan 'Message Content Intent' → Save, lalu jalankan lagi."
        )


if __name__ == "__main__":
    main()
