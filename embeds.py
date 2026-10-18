"""Helper data match + pembuat embed untuk tiap halaman tracker."""

from collections import Counter

import discord

from api import RANK_ICON_URL

VAL_RED = 0xFF4655
RESULT_COLORS = {"W": 0x3BA55D, "L": 0xED4245, "D": 0xFAA61A, "-": 0x4F545C}

# Deathmatch nggak punya data ronde & tembakan, jadi ACS/HS% nggak bermakna
NO_ROUND_MODES = {"deathmatch", "team deathmatch"}


class UserError(Exception):
    """Error yang pesannya aman ditampilkan langsung ke user."""


def parse_riot_id(riot_id: str) -> tuple[str, str]:
    name, sep, tag = riot_id.strip().rpartition("#")
    if not sep or not name or not tag:
        raise UserError("Format Riot ID salah. Contoh yang benar: `TenZ#0505`")
    return name.strip(), tag.strip()


def tracker_url(name: str, tag: str) -> str:
    return f"https://tracker.gg/valorant/profile/riot/{name}%23{tag}/overview".replace(" ", "%20")


def find_player(match: dict, name: str, tag: str) -> dict | None:
    # metadata/players bisa null untuk match yang datanya belum tersedia
    if not match.get("metadata") or not match.get("players"):
        return None
    for p in match["players"]["all_players"]:
        if p["name"].lower() == name.lower() and p["tag"].lower() == tag.lower():
            return p
    return None


def headshot_pct(stats: dict) -> float:
    shots = stats["headshots"] + stats["bodyshots"] + stats["legshots"]
    return stats["headshots"] / shots * 100 if shots else 0.0


def match_result(match: dict, player: dict) -> tuple[str, str]:
    """Return (W/L/D/-, skor) dari sudut pandang player."""
    team = (match.get("teams") or {}).get(player["team"].lower())
    if not team or team.get("has_won") is None:
        return "-", "-"
    if team["rounds_won"] == team["rounds_lost"]:
        result = "D"
    else:
        result = "W" if team["has_won"] else "L"
    return result, f"{team['rounds_won']}-{team['rounds_lost']}"


def acs(player: dict, match: dict) -> int:
    rounds = match["metadata"]["rounds_played"] or 1
    return round(player["stats"]["score"] / rounds)


def has_rounds(match: dict) -> bool:
    return (match["metadata"]["mode"] or "").lower() not in NO_ROUND_MODES


def kda(player: dict) -> str:
    s = player["stats"]
    return f"{s['kills']}/{s['deaths']}/{s['assists']}"


def stat_line(player: dict, match: dict) -> str:
    parts = [f"`{kda(player)}`"]
    if has_rounds(match):
        parts.append(f"ACS {acs(player, match)}")
        parts.append(f"HS {headshot_pct(player['stats']):.0f}%")
    return " · ".join(parts)


# -------------------------------------------------------------- statistik


class Summary:
    """Akumulasi stats dari sekumpulan match, total dan per agent."""

    def __init__(self, matches: list[dict], name: str, tag: str):
        self.total: Counter[str] = Counter()
        self.agents: dict[str, Counter[str]] = {}
        self.form: list[str] = []  # W/L/D/-, terbaru duluan
        for m in matches:
            p = find_player(m, name, tag)
            if not p:
                continue
            s = p["stats"]
            c = Counter(games=1, kills=s["kills"], deaths=s["deaths"], assists=s["assists"])
            if has_rounds(m):
                c.update(
                    score=s["score"],
                    rounds=m["metadata"]["rounds_played"],
                    hs=s["headshots"],
                    shots=s["headshots"] + s["bodyshots"] + s["legshots"],
                )
            team = (m.get("teams") or {}).get(p["team"].lower())
            if team and team.get("has_won") is not None:
                c.update(decided=1, wins=int(team["has_won"]))
            self.total.update(c)
            self.agents.setdefault(p["character"] or "?", Counter()).update(c)
            self.form.append(match_result(m, p)[0])


def fmt_kd(c: Counter) -> str:
    return f"{c['kills'] / max(c['deaths'], 1):.2f}"


def fmt_kda(c: Counter) -> str:
    return f"{(c['kills'] + c['assists']) / max(c['deaths'], 1):.2f}"


def fmt_wr(c: Counter) -> str:
    return f"{c['wins'] / c['decided'] * 100:.0f}%" if c["decided"] else "—"


def fmt_acs(c: Counter) -> str:
    return str(round(c["score"] / c["rounds"])) if c["rounds"] else "—"


def fmt_hs(c: Counter) -> str:
    return f"{c['hs'] / c['shots'] * 100:.1f}%" if c["shots"] else "—"


# ------------------------------------------------------------------ halaman

LOADING_STEPS = ["Menghubungi server", "Mengambil data pemain", "Menghitung statistik", "Hampir selesai"]


def loading_embed(frame: int) -> discord.Embed:
    # Bar jalan pelan dan berhenti sebelum penuh, karena kita nggak tahu pasti kapan data datang
    filled = min(frame + 1, 9)
    bar = "■" * filled + "□" * (10 - filled)
    step = LOADING_STEPS[min(frame // 3, len(LOADING_STEPS) - 1)]
    return discord.Embed(
        title="Memuat data" + "." * (frame % 3 + 1),
        description=f"`{bar}`\n{step}",
        color=VAL_RED,
    )


def _base_embed(account: dict, title: str) -> discord.Embed:
    name, tag = account["name"], account["tag"]
    embed = discord.Embed(title=title, url=tracker_url(name, tag), color=VAL_RED)
    embed.set_author(name=f"{name}#{tag}", icon_url=account["card"]["small"])
    return embed


def overview_embed(
    account: dict, mmr: dict | None, matches: list[dict], mode_label: str
) -> discord.Embed:
    embed = _base_embed(account, f"{account['name']}#{account['tag']}")
    embed.description = f"Region {account['region'].upper()} · Level {account['account_level']}"
    embed.set_image(url=account["card"]["wide"])

    if mmr and mmr["current"]["tier"]["id"]:
        current, peak = mmr["current"], mmr.get("peak")
        change = current.get("last_change") or 0
        embed.set_thumbnail(url=RANK_ICON_URL.format(tier=current["tier"]["id"]))
        embed.add_field(
            name="Rank",
            value=f"**{current['tier']['name']}**\n{current['rr']} RR ({change:+d})",
        )
        if peak:
            embed.add_field(
                name="Peak Rank",
                value=f"**{peak['tier']['name']}**\n{peak['season']['short'].upper()}",
            )
    else:
        embed.add_field(name="Rank", value="**Unranked**")

    summary = Summary(matches, account["name"], account["tag"])
    c = summary.total
    if not c["games"]:
        embed.add_field(
            name=f"Performa {mode_label}", value="Belum ada match yang ditemukan.", inline=False
        )
    else:
        embed.add_field(
            name=f"Form {c['games']} match terakhir ({mode_label})",
            value="`" + " ".join(summary.form) + "`"
            if c["decided"]
            else "Mode ini nggak punya hasil menang/kalah",
            inline=False,
        )
        embed.add_field(name="K/D", value=fmt_kd(c))
        embed.add_field(name="Win Rate", value=fmt_wr(c))
        embed.add_field(name="KDA", value=fmt_kda(c))
        if c["rounds"]:
            embed.add_field(name="ACS", value=fmt_acs(c))
            embed.add_field(name="HS%", value=fmt_hs(c))
        embed.add_field(name="Kills/Match", value=f"{c['kills'] / c['games']:.1f}")
        top = sorted(summary.agents.items(), key=lambda kv: kv[1]["games"], reverse=True)[:3]
        embed.add_field(
            name="Top Agents",
            value=" · ".join(f"**{a}** ({ac['games']})" for a, ac in top),
            inline=False,
        )

    embed.set_footer(text="Pakai tombol & menu di bawah buat lihat detail")
    return embed


def agents_embed(account: dict, matches: list[dict], mode_label: str) -> discord.Embed:
    embed = _base_embed(account, "Agents")
    summary = Summary(matches, account["name"], account["tag"])
    if not summary.agents:
        embed.description = f"Belum ada match **{mode_label}** yang ditemukan."
        return embed

    ranked = sorted(summary.agents.items(), key=lambda kv: kv[1]["games"], reverse=True)
    for agent, c in ranked[:10]:
        parts = [f"{c['games']} match", f"WR {fmt_wr(c)}", f"K/D {fmt_kd(c)}"]
        if c["rounds"]:
            parts += [f"ACS {fmt_acs(c)}", f"HS {fmt_hs(c)}"]
        embed.add_field(name=agent, value=" · ".join(parts), inline=False)
    embed.set_footer(text=f"Dari {summary.total['games']} match {mode_label} terakhir")
    return embed


def history_embed(account: dict, matches: list[dict], mode_label: str) -> discord.Embed:
    embed = _base_embed(account, "Match History")
    lines = []
    for i, m in enumerate(matches, 1):
        p = find_player(m, account["name"], account["tag"])
        result, score = match_result(m, p)
        meta = m["metadata"]
        lines.append(
            f"`{i:>2}. {result}` **{meta['map'] or '?'}** · {score} · {p['character'] or '?'} · "
            f"{meta['mode'] or '?'}\n└ {stat_line(p, m)} · <t:{meta['game_start']}:R>"
        )
    embed.description = "\n".join(lines) or f"Belum ada match **{mode_label}** yang ditemukan."
    embed.set_footer(text=f"Mode: {mode_label} · Pilih match di menu bawah buat lihat scoreboard")
    return embed


def match_embed(match: dict, name: str, tag: str) -> discord.Embed:
    meta = match["metadata"]
    me = find_player(match, name, tag)
    result, score = match_result(match, me) if me else ("-", "-")
    label = {"W": "Menang", "L": "Kalah", "D": "Seri"}.get(result)
    embed = discord.Embed(
        title=f"{meta['map'] or '?'} · {meta['mode'] or '?'}"
        + (f" · {label} {score}" if label else ""),
        description=f"<t:{meta['game_start']}:f>",
        color=RESULT_COLORS[result],
    )
    if me:
        embed.set_thumbnail(url=me["assets"]["agent"]["small"])

    def row(p: dict, prefix: str = "") -> str:
        text = f"{prefix}{p['character'] or '?'} · {p['name']}#{p['tag']} — {stat_line(p, match)}"
        return f"**{text}**" if p is me else text

    players = match["players"]["all_players"]
    if not has_rounds(match):
        # Deathmatch: tiap pemain jadi "tim" sendiri, jadi tampilkan satu leaderboard
        ranked = sorted(players, key=lambda p: p["stats"]["kills"], reverse=True)
        rows = [row(p, f"{i}. ") for i, p in enumerate(ranked, 1)]
        embed.add_field(name="Leaderboard", value="\n".join(rows)[:1024], inline=False)
        return embed

    embed.description += f" · {meta['rounds_played']} ronde"
    by_team: dict[str, list[dict]] = {}
    for p in players:
        by_team.setdefault(p["team"], []).append(p)

    my_team = me["team"] if me else None
    teams = match.get("teams") or {}
    # Tim sendiri ditampilkan duluan
    for team, members in sorted(by_team.items(), key=lambda kv: (kv[0] != my_team, kv[0])):
        info = teams.get(team.lower()) or {}
        won, lost = info.get("rounds_won"), info.get("rounds_lost")
        label = f"Team {team}" if won is None else f"Team {team} — {won}"
        if won is not None and won != lost:
            label += " (menang)" if info.get("has_won") else " (kalah)"
        if team == my_team:
            label += " · tim kamu"
        rows = [row(p) for p in sorted(members, key=lambda p: p["stats"]["score"], reverse=True)]
        embed.add_field(name=label, value="\n".join(rows)[:1024], inline=False)
    return embed
