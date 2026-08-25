from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from logging import getLogger, INFO
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any
import sys


@dataclass(slots=True)
class RoomState:
    guild_id: int
    channel_id: int
    guild_name: str | None = None
    channel_name: str | None = None
    connected_at: float | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        return {
            "guildId": str(raw["guild_id"]),
            "channelId": str(raw["channel_id"]),
            "guildName": raw["guild_name"],
            "channelName": raw["channel_name"],
            "connectedAt": raw["connected_at"],
            "lastError": raw["last_error"],
        }


def snowflake(value: str | int, name: str) -> int:
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"{name} phải là Discord ID dạng số.")
    return int(text)


def connected(obj: Any) -> bool:
    if obj is None:
        return False
    check = getattr(obj, "is_connected", None)
    return bool(check()) if callable(check) else True


def _clean_value(key: str, value: Any) -> str:
    sensitive = ("token", "secret", "cookie", "password", "authorization", "api_key", "apikey")
    if any(part in key.lower() for part in sensitive):
        return "<redacted>"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 500:
        text = text[:497] + "..."
    return text


class ActivityLog:
    """Thread-safe, rotating UTF-8 activity log for command/voice/live diagnostics."""

    def __init__(
        self,
        path: str = "_support/logs/bot.log",
        *,
        to_terminal: bool = False,
        max_bytes: int = 2_097_152,
        backup_count: int = 3,
    ) -> None:
        self.path = Path(path).expanduser()
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.to_terminal = bool(to_terminal)
        self._lock = Lock()
        self._logger = getLogger(f"discord_voice_selfbot.activity.{id(self)}")
        self._logger.setLevel(INFO)
        self._logger.propagate = False
        self._logger.handlers.clear()
        handler = RotatingFileHandler(
            self.path,
            maxBytes=max(64_000, int(max_bytes)),
            backupCount=max(0, int(backup_count)),
            encoding="utf-8",
        )
        handler.setFormatter(__import__("logging").Formatter("%(message)s"))
        self._logger.addHandler(handler)
        self.write("INFO", "Logger ready", file=str(self.path))

    def write(self, level: str, action: str, **fields: Any) -> None:
        level = str(level or "INFO").upper()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        parts = [f"[{ts}]", f"[{level}]", str(action)]
        clean_fields = []
        for key, value in fields.items():
            if value is None or value == "":
                continue
            clean_fields.append(f"{key}={_clean_value(key, value)}")
        if clean_fields:
            parts.append(" | " + " | ".join(clean_fields))
        line = "".join(parts)
        with self._lock:
            self._logger.info(line)
            for handler in self._logger.handlers:
                with __import__("contextlib").suppress(Exception):
                    handler.flush()
        if self.to_terminal:
            stream = sys.stderr if level in {"ERROR", "WHY"} else sys.stdout
            print(line, file=stream, flush=True)

    def close(self) -> None:
        with self._lock:
            for handler in list(self._logger.handlers):
                with __import__("contextlib").suppress(Exception):
                    handler.flush()
                    handler.close()
                self._logger.removeHandler(handler)
