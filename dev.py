"""Mode development: jalankan bot dan restart otomatis tiap ada file yang berubah.

Usage:
    python dev.py

Tekan Ctrl+C buat berhenti.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IGNORE_DIRS = {".venv", "venv", "__pycache__", ".git"}
WATCH_EXT = {".py"}
WATCH_FILES = {".env"}
POLL_INTERVAL = 1.0
DEBOUNCE = 0.5  # editor kadang nyimpen file 2x berturut-turut


def find_python() -> str:
    """Pakai python dari .venv kalau ada, biar nggak salah pakai python global."""
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def snapshot() -> dict[str, float]:
    files = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix in WATCH_EXT or filename in WATCH_FILES:
                try:
                    files[str(path.relative_to(ROOT))] = path.stat().st_mtime
                except FileNotFoundError:
                    pass
    return files


def log(message: str) -> None:
    print(f"\033[95m[dev]\033[0m {message}", flush=True)


def start(python: str) -> subprocess.Popen:
    log("Menjalankan bot...")
    return subprocess.Popen([python, str(ROOT / "bot.py")], cwd=ROOT)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("[dev] File .env belum ada. Copy .env.example jadi .env lalu isi token & API key.")
    values = dict(
        line.split("=", 1) for line in env.read_text(encoding="utf-8-sig").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    if not values.get("DEV_GUILD_ID", "").strip():
        log("Tips: isi DEV_GUILD_ID di .env biar perubahan slash command langsung muncul di server.")


def main() -> None:
    os.system("")  # aktifkan warna ANSI di terminal Windows
    check_env()
    python = find_python()
    log(f"Watching file .py & .env di {ROOT}")
    log("Simpan file = bot restart otomatis. Ctrl+C buat berhenti.\n")

    proc = start(python)
    state = snapshot()
    exit_reported = False
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            current = snapshot()
            if current != state:
                time.sleep(DEBOUNCE)
                current = snapshot()
                changed = sorted(
                    path for path in current.keys() | state.keys()
                    if current.get(path) != state.get(path)
                )
                log(f"Berubah: {', '.join(changed)} -> restart\n")
                stop(proc)
                proc = start(python)
                state = current
                exit_reported = False
            elif proc.poll() is not None and not exit_reported:
                log(f"Bot berhenti (exit code {proc.returncode}). Benerin error-nya lalu simpan file, "
                    "nanti otomatis jalan lagi.")
                exit_reported = True
    except KeyboardInterrupt:
        log("Berhenti.")
        stop(proc)


if __name__ == "__main__":
    main()
