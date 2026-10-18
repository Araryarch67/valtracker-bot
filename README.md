# ValTracker Bot

Bot Discord buat ngecek stats Valorant, mirip tracker.gg. Cukup ketik Riot ID (`Nama#TAG`), region otomatis terdeteksi.

## Command

Tiap command bisa dipanggil 3 cara:

- Slash: `/track Nama#TAG`
- Prefix: `valtrack!track Nama#TAG` (singkatnya `vt!t Nama#TAG`, nggak peka huruf besar/kecil)
- Mention: `@ValTracker track Nama#TAG`

| Command | Alias prefix | Fungsi |
|---|---|---|
| `track [Nama#TAG] [region]` | `t`, `stats`, `profile` | Buka tracker interaktif pemain |
| `link <Nama#TAG>` | `l` | Simpan Riot ID, nanti cukup ketik `track` |
| `unlink` | | Hapus Riot ID yang tersimpan |
| `help [command]` | `h`, `commands`, `docs` | Panduan lengkap, atau detail satu command |

Lewat prefix, Riot ID boleh pakai spasi tanpa tanda kutip, dan region bisa ditaruh di akhir:
`valtrack!track Moon blade#AKA ap`.

`/track` langsung menampilkan **Overview**: rank, peak, form 10 match terakhir, K/D, win rate, ACS, HS% dan top agent.
Dari situ user tinggal klik:

- **Agents**: stats per agent
- **Matches**: riwayat 10 match, pilih satu dari menu untuk lihat scoreboard (bisa geser Sebelumnya/Berikutnya)
- **Refresh**: ambil data terbaru
- Menu **Mode**: Competitive / Unrated / Swiftplay / Deathmatch / Premier / Semua mode

Tombolnya bisa dipakai siapa aja di channel (pesan tracker-nya dipakai bareng), dan nonaktif setelah 15 menit.

## Setup

1. **Bikin bot Discord**: buka https://discord.com/developers/applications → New Application → tab *Bot* → *Reset Token*, lalu copy token-nya.
   Di tab yang sama, nyalakan **Message Content Intent** (wajib buat command `valtrack!`).
2. **Invite bot**: tab *OAuth2 → URL Generator*, centang scope `bot` dan `applications.commands`, permission `Send Messages`, `Embed Links` dan `Read Message History` (buat reply). Buka URL-nya dan pilih server kamu.
3. **API key Valorant**: login di https://api.henrikdev.xyz/dashboard pakai Discord, lalu generate API key (gratis).
4. **Isi config**: copy `.env.example` jadi `.env`, lalu isi `DISCORD_TOKEN` dan `HENRIK_API_KEY`.
   Isi juga `DEV_GUILD_ID` (klik kanan server → Copy Server ID) biar slash command langsung muncul pas testing.
5. **Install dependency** (sekali aja):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   ```
6. **Jalankan**:
   ```powershell
   python dev.py        # mode development: restart otomatis tiap file disimpan
   .\.venv\Scripts\python bot.py   # mode biasa, buat dijalanin terus
   ```
   Tekan `Ctrl+C` buat berhenti. Jangan jalanin dua bot sekaligus pakai token yang sama, nanti tiap command dibalas dua kali.

## Deploy ke Render

Cara cepat: di https://dashboard.render.com → **New** → **Blueprint** → pilih repo ini. Semua setting diambil
dari `render.yaml` (Web Service free, region Singapore), tinggal isi `DISCORD_TOKEN` & `HENRIK_API_KEY`, lalu lanjut ke langkah 4.

Cara manual:

1. Upload project ke GitHub (repo private). `.env`, `.venv` dan `links.json` sudah di-ignore, jangan di-upload manual.
2. Di https://dashboard.render.com → **New** → pilih **Background Worker** (berbayar, paling stabil)
   atau **Web Service** (ada free tier, tapi tidur kalau 15 menit nggak ada request HTTP masuk).
3. Isi:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
   - Environment: `DISCORD_TOKEN`, `HENRIK_API_KEY`. `DEV_GUILD_ID` dikosongkan biar slash command muncul di semua server.
4. Kalau pakai Web Service, bot otomatis buka health check di port `PORT` dari Render.
   Biar nggak tidur, ping URL `https://<nama-app>.onrender.com/` tiap 5 menit pakai UptimeRobot / cron-job.org.
5. File di Render hilang tiap deploy/restart, jadi akun yang di-`link` ikut hilang.
   Biar awet, tambah **Persistent Disk** (berbayar) di `/data` lalu set `LINKS_PATH=/data/links.json`.

## Catatan

- Data dari [HenrikDev API](https://docs.henrikdev.xyz) (unofficial). Rate limit API key basic 30 request/menit.
  Biar hemat, response di-cache 60 detik (data akun 1 jam) dan pindah tab nggak fetch ulang.
  Kalau kuota habis, bot nampilin animasi loading lalu otomatis fetch lagi setelah limit reset.
- Filter mode Spike Rush dan Team Deathmatch nggak didukung API (malah balikin match Deathmatch), jadi nggak ada di menu.
- Akun yang di-link disimpan di `links.json`.
