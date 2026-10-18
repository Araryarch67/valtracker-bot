"""View interaktif /track: overview lengkap dulu, detail dibuka lewat tombol & menu."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord

from api import ValorantAPI, ValorantAPIError
from embeds import (
    UserError,
    agents_embed,
    find_player,
    history_embed,
    kda,
    loading_embed,
    match_embed,
    match_result,
    overview_embed,
    tracker_url,
)

log = logging.getLogger("valtracker")

MATCH_COUNT = 10
LOADING_DELAY = 1.5  # request cepat langsung tampil, animasi loading cuma kalau lambat
LOADING_INTERVAL = 3
ALL_MODES = "all"
MODES = {
    "competitive": "Competitive",
    "unrated": "Unrated",
    "swiftplay": "Swiftplay",
    "deathmatch": "Deathmatch",
    "premier": "Premier",
    ALL_MODES: "Semua mode",
    # spikerush & teamdeathmatch nggak didukung API v3 (malah balikin match Deathmatch)
}
TABS = [("overview", "Overview"), ("agents", "Agents"), ("matches", "Matches")]


async def with_loading(work: Awaitable, show: Callable[[discord.Embed], Awaitable]):
    """Jalankan `work`; kalau lama (misal lagi nunggu rate limit reset), tampilkan animasi loading."""
    task = asyncio.ensure_future(work)
    frame = 0
    timeout = LOADING_DELAY
    while True:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if done:
            return task.result()
        try:
            await show(loading_embed(frame))
        except discord.HTTPException:
            pass
        frame += 1
        timeout = LOADING_INTERVAL


class PlayerView(discord.ui.View):
    def __init__(self, api: ValorantAPI, account: dict, region: str):
        # Siapa pun di channel boleh pakai tombolnya, pesan tracker-nya dipakai bareng
        super().__init__(timeout=900)
        self.api = api
        self.account = account
        self.region = region
        self.name, self.tag = account["name"], account["tag"]

        self.mmr: dict | None = None
        self.page = "overview"
        self.mode = "competitive"
        self.selected = 0  # index match yang dibuka di halaman detail
        self._matches: dict[str, list[dict]] = {}  # cache per mode, biar hemat rate limit
        self.message: discord.Message | None = None

    # ----------------------------------------------------------------- data

    async def load(self, fresh: bool = False) -> None:
        # State baru dipasang setelah semua fetch berhasil, jadi kalau gagal data lama tetap utuh
        try:
            mmr = await self.api.get_mmr(self.region, self.name, self.tag, fresh=fresh)
        except ValorantAPIError as e:
            if e.status != 404:  # 404 = belum pernah main ranked
                raise
            mmr = None
        matches = await self._fetch_matches(self.mode, fresh=fresh)
        self.mmr = mmr
        if fresh:
            self._matches.clear()
        self._matches[self.mode] = matches

    async def _fetch_matches(self, mode: str, fresh: bool = False) -> list[dict]:
        matches = await self.api.get_matches(
            self.region,
            self.name,
            self.tag,
            None if mode == ALL_MODES else mode,
            MATCH_COUNT,
            fresh=fresh,
        )
        return [m for m in matches or [] if find_player(m, self.name, self.tag)]

    async def _get_matches(self) -> list[dict]:
        if self.mode not in self._matches:
            self._matches[self.mode] = await self._fetch_matches(self.mode)
        return self._matches[self.mode]

    # --------------------------------------------------------------- render

    async def render(self) -> discord.Embed:
        matches = await self._get_matches()
        label = MODES[self.mode]
        if self.page == "overview":
            embed = overview_embed(self.account, self.mmr, matches, label)
        elif self.page == "agents":
            embed = agents_embed(self.account, matches, label)
        elif self.page == "matches":
            embed = history_embed(self.account, matches, label)
        else:
            embed = match_embed(matches[self.selected], self.name, self.tag)
            embed.set_footer(text=f"Match {self.selected + 1} dari {len(matches)} · {label}")
        self._build(matches)
        return embed

    async def _update(self, interaction: discord.Interaction, **state) -> None:
        await interaction.response.defer()
        old = {k: getattr(self, k) for k in state}
        for k, v in state.items():
            setattr(self, k, v)

        async def show_loading(embed: discord.Embed):
            # Komponen disembunyikan selama loading biar nggak diklik dobel
            await interaction.edit_original_response(embed=embed, view=None)

        try:
            embed = await with_loading(self.render(), show_loading)
        except Exception:
            for k, v in old.items():  # balikin ke halaman sebelumnya kalau gagal
                setattr(self, k, v)
            await interaction.edit_original_response(embed=await self.render(), view=self)
            raise
        await interaction.edit_original_response(embed=embed, view=self)

    # ----------------------------------------------------------- components

    def _build(self, matches: list[dict]) -> None:
        self.clear_items()

        for page, label in TABS:
            active = self.page == page or (page == "matches" and self.page == "match")
            self._button(
                label, row=0,
                style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
                disabled=self.page == page,
                callback=lambda i, page=page: self._update(i, page=page),
            )
        self._button("Refresh", row=0, callback=self._on_refresh)
        self.add_item(
            discord.ui.Button(label="tracker.gg", url=tracker_url(self.name, self.tag), row=0)
        )

        self._add_mode_select()
        if self.page in ("matches", "match") and matches:
            self._add_match_select(matches)

        if self.page == "match":
            self._button(
                "< Sebelumnya", row=3, disabled=self.selected == 0,
                callback=lambda i: self._update(i, selected=self.selected - 1),
            )
            self._button("Kembali", row=3, callback=lambda i: self._update(i, page="matches"))
            self._button(
                "Berikutnya >", row=3, disabled=self.selected >= len(matches) - 1,
                callback=lambda i: self._update(i, selected=self.selected + 1),
            )

    def _button(self, label, row, callback, disabled=False,
                style=discord.ButtonStyle.secondary) -> None:
        button = discord.ui.Button(label=label, row=row, style=style, disabled=disabled)
        button.callback = callback
        self.add_item(button)

    def _add_mode_select(self) -> None:
        select = discord.ui.Select(
            placeholder="Pilih mode",
            row=1,
            options=[
                discord.SelectOption(label=f"Mode: {label}", value=value, default=value == self.mode)
                for value, label in MODES.items()
            ],
        )

        async def callback(interaction: discord.Interaction):
            # Detail match nggak relevan lagi kalau mode ganti, balik ke daftar match
            page = "matches" if self.page == "match" else self.page
            await self._update(interaction, mode=select.values[0], page=page, selected=0)

        select.callback = callback
        self.add_item(select)

    def _add_match_select(self, matches: list[dict]) -> None:
        options = []
        for i, m in enumerate(matches):
            p = find_player(m, self.name, self.tag)
            result, score = match_result(m, p)
            meta = m["metadata"]
            options.append(
                discord.SelectOption(
                    label=f"{i + 1}. [{result}] {meta['map'] or '?'} · {p['character'] or '?'} · {score}",
                    description=f"{meta['mode'] or '?'} · K/D/A {kda(p)}",
                    value=str(i),
                    default=self.page == "match" and i == self.selected,
                )
            )
        select = discord.ui.Select(placeholder="Pilih match buat lihat scoreboard", options=options, row=2)

        async def callback(interaction: discord.Interaction):
            await self._update(interaction, page="match", selected=int(select.values[0]))

        select.callback = callback
        self.add_item(select)

    # Jangan dinamai _refresh: itu method internal discord.ui.View yang dipanggil tiap pesan di-edit
    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        async def work():
            await self.load(fresh=True)
            if self.selected >= len(self._matches[self.mode]):
                self.page, self.selected = "matches", 0
            return await self.render()

        async def show_loading(embed: discord.Embed):
            await interaction.edit_original_response(embed=embed, view=None)

        try:
            embed = await with_loading(work(), show_loading)
        except Exception:
            await interaction.edit_original_response(embed=await self.render(), view=self)
            raise
        await interaction.edit_original_response(embed=embed, view=self)

    # ---------------------------------------------------------------- hooks

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        if isinstance(error, (UserError, ValorantAPIError)):
            message = str(error)
        else:
            message = "Terjadi error tak terduga. Coba lagi nanti."
            log.exception("Error di tracker view", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            if not getattr(item, "url", None):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
