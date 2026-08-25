from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _owners(value: str) -> set[int]:
    return {int(x.strip()) for x in value.split(",") if x.strip().isdigit()}


@dataclass(slots=True)
class Settings:
    token: str
    host: str = "127.0.0.1"
    port: int = 3030
    api_key: str = ""
    auto_detect_interval: float = 2.0
    auto_watch_all_lives: bool = True
    auto_watch_timeout: float = 5.0
    command_prefix: str = "k"
    command_owner_ids: set[int] | None = None
    auto_delete_command_messages: bool = True
    auto_delete_command_delay: float = 0.0
    auto_delete_command_responses: bool = True
    auto_delete_response_delay: float = 0.0
    log_file: str = "_support/logs/bot.log"
    log_to_terminal: bool = False
    log_max_bytes: int = 2097152
    log_backup_count: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            token=os.getenv("DISCORD_TOKEN", "").strip(),
            host=os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(os.getenv("PORT", "3030")),
            api_key=os.getenv("API_KEY", "").strip(),
            auto_detect_interval=float(os.getenv("AUTO_DETECT_INTERVAL", "2.0")),
            auto_watch_all_lives=_flag("AUTO_WATCH_ALL_LIVES", True),
            auto_watch_timeout=float(os.getenv("AUTO_WATCH_TIMEOUT", "5.0")),
            command_prefix=os.getenv("COMMAND_PREFIX", "k").strip() or "k",
            command_owner_ids=_owners(os.getenv("COMMAND_OWNER_IDS", "")),
            auto_delete_command_messages=_flag("AUTO_DELETE_COMMAND_MESSAGES", True),
            auto_delete_command_delay=float(os.getenv("AUTO_DELETE_COMMAND_DELAY", "0.0")),
            auto_delete_command_responses=_flag("AUTO_DELETE_COMMAND_RESPONSES", True),
            auto_delete_response_delay=float(os.getenv("AUTO_DELETE_RESPONSE_DELAY", "0.0")),
            log_file=os.getenv("LOG_FILE", "_support/logs/bot.log").strip() or "_support/logs/bot.log",
            log_to_terminal=_flag("LOG_TO_TERMINAL", False),
            log_max_bytes=int(os.getenv("LOG_MAX_BYTES", "2097152")),
            log_backup_count=int(os.getenv("LOG_BACKUP_COUNT", "3")),
        )
