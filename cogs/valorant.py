"""Command ValTracker. Tiap command bisa dipanggil 3 cara: slash (/track), prefix (valtrack!track)
dan mention (@ValTracker track). Semuanya diarahkan ke satu implementasi berbasis `commands.Context`."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from api import REGIONS, ValorantAPIError
from embeds import VAL_RED, UserError, parse_riot_id
from views import PlayerView, with_loading

log = logging.getLogger("valtracker")

REGION_CHOICES = [app_commands.Choice(name=r.upper(), value=r) for r in REGIONS]

# Dokumentasi tiap command, dipakai di /help dan valtrack!help <command>
DOCS = {
    "track": {
        "args": "[Nama#TAG] [region]",
        "summary": "Buka tracker interaktif pemain",
        "detail": (
            "Menampilkan **Overview**: rank, peak, form 10 match terakhir, K/D, win rate, ACS, HS% "
            "dan top agent. Dari situ tinggal klik:\n"
            "**Agents**: stats per agent\n"
            "**Matches**: riwayat match, pilih satu buat lihat scoreboard\n"
            "**Refresh**: ambil data terbaru\n"
            "Menu **Mode**: Competitive / Unrated / Swiftplay / Deathmatch / Premier / Semua mode\n\n"
            "Riot ID boleh pakai spasi. Kosongkan Riot ID buat buka akun yang sudah di-link. "
            f"Region otomatis terdeteksi, tapi bisa dipaksa: `{'`, `'.join(REGIONS)}`.\n"
            "Tombolnya bisa dipakai siapa aja di channel, dan nonaktif setelah 15 menit."
        ),
        "examples": ["track TenZ#0505", "track Moon blade#AKA ap", "track"],
    },
    "link": {
        "args": "<Nama#TAG>",
        "summary": "Simpan Riot ID kamu, nanti cukup ketik `track`",
        "detail": "Riot ID dicek dulu ke server Riot, jadi pastikan nama & tag-nya benar.",
        "examples": ["link TenZ#0505"],
    },
    "unlink": {
        "args": "",
        "summary": "Hapus Riot ID yang tersimpan",
        "detail": "Setelah unlink, `track` wajib pakai Riot ID lagi.",
        "examples": ["unlink"],
    },
    "help": {
        "args": "[command]",
        "summary": "Panduan ini, atau detail satu command",
        "detail": "Tanpa argumen menampilkan semua command. Isi nama command buat lihat detailnya.",
        "examples": ["help", "help track"],
    },
}
HELP_CHOICES = [app_commands.Choice(name=name, value=name) for name in DOCS]


def split_region(text: str) -> tuple[str | None, str | None]:
    """`Nama#TAG ap` -> ("Nama#TAG", "ap"). Riot ID selalu diakhiri #TAG, jadi region pasti token terpisah."""
    text = text.strip().strip("\"'`")
    parts = text.split()
    if parts and parts[-1].lower() in REGIONS:
        return " ".join(parts[:-1]).strip("\"'`") or None, parts[-1].lower()
    return text or None, None


def error_text(error: Exception, where: str) -> str:
    if isinstance(error, (UserError, ValorantAPIError)):
        return str(error)
    log.exception("Error di command %s", where, exc_info=error)
    return "Terjadi error tak terduga. Coba lagi nanti."


class Valorant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api = bot.api
        self.storage = bot.storage
        self.prefix = bot.prefixes[0]

    def usage(self, ctx: commands.Context, command: str) -> str:
        """Cara panggil command sesuai cara user manggil bot sekarang (slash atau prefix)."""
        if ctx.interaction:
            return f"/{command}"
        return f"{ctx.clean_prefix}{command}"

    # ---------------------------------------------------------------- errors

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        message = error_text(getattr(error, "original", error), f"/{interaction.command.name}")
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        elif interaction.command.name == "track":
            # Ganti pesan "Memuat data..." dengan error-nya
            await interaction.edit_original_response(content=message, embed=None, view=None)
        else:
            await interaction.followup.send(message, ephemeral=True)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        name = ctx.command.name
        if isinstance(error, commands.UserInputError):
            usage = f"{ctx.clean_prefix}{name} {DOCS[name]['args']}".strip()
            message = f"Format salah. Cara pakai: `{usage}`\nDetail: `{ctx.clean_prefix}help {name}`"
        elif isinstance(error, commands.CommandOnCooldown):
            message = f"Pelan-pelan, coba lagi {error.retry_after:.0f} detik lagi."
        else:
            message = error_text(getattr(error, "original", error), f"{ctx.clean_prefix}{name}")
        await ctx.reply(message)

    # ----------------------------------------------------------------- track

    @app_commands.command(name="track", description="Lihat profil & stats Valorant pemain")
    @app_commands.describe(
        riot_id="Contoh: Nama#TAG (kosongkan untuk akun yang di-link)",
        region="Opsional, otomatis terdeteksi",
    )
    @app_commands.choices(region=REGION_CHOICES)
    async def track_slash(
        self,
        interaction: discord.Interaction,
        riot_id: str | None = None,
        region: app_commands.Choice[str] | None = None,
    ):
        ctx = await commands.Context.from_interaction(interaction)
        await self.track(ctx, riot_id, region.value if region else None)

    @commands.command(name="track", aliases=["t", "stats", "profile"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def track_prefix(self, ctx: commands.Context, *, args: str = ""):
        await self.track(ctx, *split_region(args))

    async def track(self, ctx: commands.Context, riot_id: str | None, region: str | None):
        if riot_id:
            name, tag = parse_riot_id(riot_id)
        else:
            linked = self.storage.get(ctx.author.id)
            if not linked:
                raise UserError(
                    f"Masukkan Riot ID (contoh `{self.usage(ctx, 'track')} Nama#TAG`), "
                    f"atau `{self.usage(ctx, 'link')}` akunmu dulu."
                )
            name, tag = linked["name"], linked["tag"]
        await ctx.typing()  # slash: defer, prefix: indikator "sedang mengetik"

        async def work():
            account = await self.api.get_account(name, tag)
            view = PlayerView(self.api, account, region or account["region"])
            await view.load()
            return view, await view.render()

        message: discord.Message | None = None

        async def show_loading(embed: discord.Embed):
            nonlocal message
            if message is None:
                message = await ctx.reply(embed=embed)
            else:
                await message.edit(embed=embed)

        try:
            view, embed = await with_loading(work(), show_loading)
        except Exception:
            # Slash: pesan loading diganti error oleh cog_app_command_error. Prefix: hapus aja.
            if message and not ctx.interaction:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            raise
        if message:
            await message.edit(embed=embed, view=view)
            view.message = message
        else:
            view.message = await ctx.reply(embed=embed, view=view)

    # ------------------------------------------------------------------ link

    @app_commands.command(name="link", description="Simpan Riot ID kamu biar nggak perlu ketik lagi")
    @app_commands.describe(riot_id="Riot ID kamu, contoh: Nama#TAG")
    async def link_slash(self, interaction: discord.Interaction, riot_id: str):
        await self.link(await commands.Context.from_interaction(interaction), riot_id)

    @commands.command(name="link", aliases=["l"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def link_prefix(self, ctx: commands.Context, *, riot_id: str):
        await self.link(ctx, riot_id.strip("\"'`"))

    async def link(self, ctx: commands.Context, riot_id: str):
        name, tag = parse_riot_id(riot_id)
        await ctx.typing(ephemeral=True)
        account = await self.api.get_account(name, tag)
        self.storage.set(ctx.author.id, account["name"], account["tag"], account["region"])

        embed = discord.Embed(
            title="Akun terhubung",
            description=f"**{account['name']}#{account['tag']}** ({account['region'].upper()})\n"
            f"Sekarang cukup ketik `{self.usage(ctx, 'track')}` tanpa Riot ID.",
            color=VAL_RED,
        )
        embed.set_thumbnail(url=account["card"]["small"])
        await ctx.reply(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Hapus Riot ID yang tersimpan")
    async def unlink_slash(self, interaction: discord.Interaction):
        await self.unlink(await commands.Context.from_interaction(interaction))

    @commands.command(name="unlink")
    async def unlink_prefix(self, ctx: commands.Context):
        await self.unlink(ctx)

    async def unlink(self, ctx: commands.Context):
        if self.storage.remove(ctx.author.id):
            await ctx.reply("Akun berhasil di-unlink.", ephemeral=True)
        else:
            await ctx.reply("Kamu belum link akun.", ephemeral=True)

    # ------------------------------------------------------------------ help

    @app_commands.command(name="help", description="Cara pakai ValTracker")
    @app_commands.describe(command="Opsional, lihat detail satu command")
    @app_commands.choices(command=HELP_CHOICES)
    async def help_slash(
        self, interaction: discord.Interaction, command: app_commands.Choice[str] | None = None
    ):
        ctx = await commands.Context.from_interaction(interaction)
        await self.help(ctx, command.value if command else None)

    @commands.command(name="help", aliases=["h", "commands", "docs"])
    async def help_prefix(self, ctx: commands.Context, command: str | None = None):
        await self.help(ctx, command)

    async def help(self, ctx: commands.Context, command: str | None):
        if command:
            cmd = self.bot.get_command(command.lower().removeprefix(ctx.clean_prefix.lower()))
            if not cmd or cmd.cog is not self:
                raise UserError(f"Command `{command}` nggak ada. Lihat daftarnya di `{self.usage(ctx, 'help')}`.")
            embed = self.command_help_embed(cmd)
        else:
            embed = self.help_embed()
        await ctx.reply(embed=embed, ephemeral=True)

    def help_embed(self) -> discord.Embed:
        p = self.prefix
        short = self.bot.prefixes[1] if len(self.bot.prefixes) > 1 else p
        mention = self.bot.user.mention
        embed = discord.Embed(
            title="ValTracker: Panduan",
            description=(
                "Bot buat ngecek stats Valorant, mirip tracker.gg. Region otomatis terdeteksi.\n\n"
                "**Bisa dipanggil 3 cara:**\n"
                f"Slash: `/track Nama#TAG`\n"
                f"Prefix: `{p}track Nama#TAG` (singkatnya `{short}t Nama#TAG`)\n"
                f"Mention: {mention} `track Nama#TAG`"
            ),
            color=VAL_RED,
        )
        embed.add_field(
            name="Command",
            value="\n".join(
                f"`{p}{name}{' ' + doc['args'] if doc['args'] else ''}`\n{doc['summary']}"
                for name, doc in DOCS.items()
            ),
            inline=False,
        )
        embed.add_field(
            name="Tracker interaktif",
            value=(
                "**Overview**: rank, peak, form & ringkasan performa\n"
                "**Agents**: stats per agent\n"
                "**Matches**: riwayat match, pilih satu buat lihat scoreboard\n"
                "**Refresh**: ambil data terbaru\n"
                "Menu **Mode** buat ganti Competitive / Unrated / Swiftplay / dll."
            ),
            inline=False,
        )
        embed.add_field(
            name="Contoh",
            value=(
                f"`{p}track TenZ#0505`\n"
                f"`{p}track Moon blade#AKA ap`: Riot ID pakai spasi + paksa region\n"
                f"`{p}link Nama#TAG` lalu cukup `{short}t`"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Detail tiap command: {p}help <command> · Prefix nggak peka huruf besar/kecil")
        return embed

    def command_help_embed(self, cmd: commands.Command) -> discord.Embed:
        p = self.prefix
        doc = DOCS[cmd.name]
        args = f" {doc['args']}" if doc["args"] else ""
        embed = discord.Embed(
            title=f"{p}{cmd.name}",
            description=f"{doc['summary']}\n\n{doc['detail']}",
            color=VAL_RED,
        )
        embed.add_field(
            name="Cara pakai",
            value=f"`/{cmd.name}{args}`\n`{p}{cmd.name}{args}`\n{self.bot.user.mention} `{cmd.name}{args}`",
            inline=False,
        )
        if cmd.aliases:
            embed.add_field(
                name="Alias", value=" ".join(f"`{p}{a}`" for a in cmd.aliases), inline=False
            )
        embed.add_field(
            name="Contoh", value="\n".join(f"`{p}{e}`" for e in doc["examples"]), inline=False
        )
        embed.set_footer(text="<wajib> · [opsional]")
        return embed


async def setup(bot):
    await bot.add_cog(Valorant(bot))
