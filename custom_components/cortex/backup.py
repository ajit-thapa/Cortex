"""Backup and restore of everything Cortex remembers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .feature import Feature

KEEP = 10
VERSION = 1


class Backup(Feature):
    name = "backup"

    def folder(self) -> Path:
        return Path(self.hass.config.path("cortex_backups"))

    def payload(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "created": dt_util.now().isoformat(timespec="seconds"),
            "data": self.brain.export_data(),
            "options": dict(self.brain.entry.options),
        }

    async def create(self) -> str:
        """Write a timestamped file and prune old ones. Returns the path."""
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
        payload = self.payload()
        folder = self.folder()

        def write() -> str:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"cortex-{stamp}.json"
            path.write_text(json.dumps(payload, indent=2, default=str))
            for old in sorted(folder.glob("cortex-*.json"))[:-KEEP]:
                old.unlink()
            return str(path)

        path = await self.hass.async_add_executor_job(write)
        self.brain.log("backup", f"Backup saved: {Path(path).name}")
        return path

    async def list(self) -> list[str]:
        folder = self.folder()

        def names() -> list[str]:
            return sorted(p.name for p in folder.glob("cortex-*.json")) if folder.exists() else []

        return await self.hass.async_add_executor_job(names)

    async def restore(self, filename: str | None = None, with_options: bool = False) -> str:
        """Restore from ``filename`` (default: the newest backup)."""
        names = await self.list()
        if not names:
            raise HomeAssistantError("No backups found")
        name = filename or names[-1]
        if "/" in name or "\\" in name or name not in names:
            raise HomeAssistantError(f"No backup called {name}")
        path = self.folder() / name
        raw = await self.hass.async_add_executor_job(path.read_text)
        try:
            payload = json.loads(raw)
            data = payload["data"]
        except (ValueError, KeyError) as err:
            raise HomeAssistantError(f"{name} is not a valid Cortex backup") from err
        await self.brain.import_data(data)
        if with_options and payload.get("options"):
            self.hass.config_entries.async_update_entry(
                self.brain.entry, options={**self.brain.entry.options, **payload["options"]}
            )
        self.brain.log("backup", f"Restored {name}")
        return name
