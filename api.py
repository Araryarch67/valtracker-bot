"""Client sederhana untuk HenrikDev Valorant API (https://docs.henrikdev.xyz)."""

import asyncio
import logging
import time
from urllib.parse import quote

import aiohttp

log = logging.getLogger("valtracker")

BASE_URL = "https://api.henrikdev.xyz"
REGIONS = ["ap", "eu", "na", "kr", "latam", "br"]
RANK_ICON_URL = (
    "https://media.valorant-api.com/competitivetiers/"
    "03621f52-342b-cf4e-4f86-9350a49c6d04/{tier}/largeicon.png"
)

# Interaction Discord yang sudah di-defer boleh dijawab sampai 15 menit, jadi kalau kena limit
# kita tunggu reset diam-diam (user lihat animasi loading) daripada langsung kasih error.
MAX_RATE_LIMIT_WAIT = 90
STALE_KEEP = 3600  # data kadaluarsa tetap disimpan segini lama buat cadangan saat kena limit


class ValorantAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _error_message(status: int, body: dict | None) -> str:
    if status == 404:
        return "Akun atau data tidak ditemukan. Cek lagi Riot ID dan region-nya."
    if status == 429:
        return "Bot lagi ramai dipakai. Coba lagi dalam 1 menit."
    if status in (401, 403):
        return "API key HenrikDev tidak valid atau belum diisi."
    try:
        return body["errors"][0]["message"]
    except (TypeError, KeyError, IndexError):
        return f"API error (HTTP {status})."


class ValorantAPI:
    def __init__(self, api_key: str, cache_ttl: int = 60):
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        self._cache: dict[tuple, tuple[float, object]] = {}  # key -> (expires_at, data)
        self._inflight: dict[tuple, asyncio.Future] = {}
        self._session: aiohttp.ClientSession | None = None
        self._limit_reset_at = 0.0  # kapan kuota limit kebuka lagi (monotonic), 0 = aman

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            headers={"Authorization": self.api_key},
            timeout=aiohttp.ClientTimeout(total=15),
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def _get(
        self, path: str, params: dict | None = None, ttl: int | None = None, fresh: bool = False
    ):
        key = (path.lower(), tuple(sorted((params or {}).items())))
        hit = self._cache.get(key)
        if hit and time.monotonic() < hit[0] and not fresh:
            return hit[1]

        # Request yang sama lagi jalan (misal 2 orang /track pemain yang sama): tunggu hasilnya aja
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])

        future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            data = await self._fetch(path, params)
        except ValorantAPIError as e:
            # Kena limit tapi punya data lama: lebih baik tampilkan itu daripada error
            if e.status == 429 and hit:
                log.warning("Rate limit, pakai data cache lama untuk %s", path)
                future.set_result(hit[1])
                return hit[1]
            future.set_exception(e)
            future.exception()  # tandai sudah diambil biar nggak muncul warning
            raise
        else:
            future.set_result(data)
            self._store(key, data, ttl or self.cache_ttl)
            return data
        finally:
            del self._inflight[key]

    async def _fetch(self, path: str, params: dict | None):
        for attempt in range(2):
            await self._wait_for_limit()
            try:
                async with self._session.get(BASE_URL + path, params=params) as resp:
                    body = await resp.json(content_type=None)
                    self._track_limit(resp)
                    if resp.status == 200:
                        return body.get("data")
                    if resp.status == 429 and attempt == 0:
                        log.warning("Kena rate limit, tunggu lalu coba lagi: %s", path)
                        continue
                    raise ValorantAPIError(resp.status, _error_message(resp.status, body))
            except (aiohttp.ClientError, TimeoutError) as e:
                raise ValorantAPIError(0, "Gagal terhubung ke API Valorant.") from e

    def _track_limit(self, resp: aiohttp.ClientResponse) -> None:
        try:
            remaining = int(resp.headers["X-RateLimit-Remaining"])
            reset = int(resp.headers["X-RateLimit-Reset"])
        except (KeyError, ValueError):
            return
        if remaining <= 0 or resp.status == 429:
            self._limit_reset_at = time.monotonic() + reset + 1

    async def _wait_for_limit(self) -> None:
        wait = self._limit_reset_at - time.monotonic()
        if wait <= 0:
            return
        if wait > MAX_RATE_LIMIT_WAIT:
            raise ValorantAPIError(429, _error_message(429, None))
        log.info("Kuota API habis, tunggu %.0f detik", wait)
        await asyncio.sleep(wait)

    def _store(self, key: tuple, data, ttl: int) -> None:
        now = time.monotonic()
        if len(self._cache) > 500:
            self._cache = {k: v for k, v in self._cache.items() if now < v[0] + STALE_KEEP}
        self._cache[key] = (now + ttl, data)

    async def get_account(self, name: str, tag: str) -> dict:
        # Data akun (region, level, card) jarang berubah, cache lebih lama biar hemat rate limit
        return await self._get(
            f"/valorant/v1/account/{quote(name, safe='')}/{quote(tag, safe='')}", ttl=3600
        )

    async def get_mmr(self, region: str, name: str, tag: str, fresh: bool = False) -> dict:
        return await self._get(
            f"/valorant/v3/mmr/{region}/pc/{quote(name, safe='')}/{quote(tag, safe='')}",
            fresh=fresh,
        )

    async def get_matches(
        self,
        region: str,
        name: str,
        tag: str,
        mode: str | None = None,
        size: int = 5,
        fresh: bool = False,
    ) -> list[dict]:
        params = {"size": size}
        if mode:
            params["mode"] = mode
        return await self._get(
            f"/valorant/v3/matches/{region}/{quote(name, safe='')}/{quote(tag, safe='')}",
            params,
            fresh=fresh,
        )
