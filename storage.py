"""Penyimpanan link akun Discord -> Riot ID di file JSON."""

import json
import os
from pathlib import Path


class LinkStorage:
    def __init__(self, path: str = "links.json"):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, user_id: int) -> dict | None:
        return self._data.get(str(user_id))

    def set(self, user_id: int, name: str, tag: str, region: str) -> None:
        self._data[str(user_id)] = {"name": name, "tag": tag, "region": region}
        self._save()

    def remove(self, user_id: int) -> bool:
        if self._data.pop(str(user_id), None) is None:
            return False
        self._save()
        return True
