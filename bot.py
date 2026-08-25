from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from commands import CommandRouter
from core import ActivityLog, snowflake
from live import LiveManager
from voice import VoiceManager


class CleanSelfBot:
    def __init__(
        self,
        token: str,
        *,
        auto_detect_interval: float = 2.0,
        command_prefix: str = "k",
        command_owner_ids: set[int] | None = None,
        auto_delete_command_messages: bool = True,
        auto_delete_command_delay: float = 0.0,
        auto_delete_command_responses: bool = True,
        auto_delete_response_delay: float = 0.0,
        auto_watch_all_lives: bool = True,
        auto_watch_timeout: float = 5.0,
        log_file: str = "_support/logs/bot.log",
        log_to_terminal: bool = False,
        log_max_bytes: int = 2097152,
        log_backup_count: int = 3,
    ) -> None:
        self.token = str(token or "").strip()
        self.auto_detect_interval = max(0.5, float(auto_detect_interval))
        self.command_prefix = str(command_prefix or "k").strip() or "k"
        self.command_owner_ids = {int(x) for x in (command_owner_ids or set())}
        self.auto_delete_command_messages = bool(auto_delete_command_messages)
        self.auto_delete_command_delay = max(0.0, float(auto_delete_command_delay))
        self.auto_delete_command_responses = bool(auto_delete_command_responses)
        self.auto_delete_response_delay = max(0.0, float(auto_delete_response_delay))
        self.auto_watch_all_lives = bool(auto_watch_all_lives)
        self.auto_watch_timeout = max(0.5, min(float(auto_watch_timeout), 30.0))
        self.activity_log = ActivityLog(
            log_file,
            to_terminal=log_to_terminal,
            max_bytes=log_max_bytes,
            backup_count=log_backup_count,
        )

        self.discord: Any = None
        self.VoiceClient: Any = None
        self.StreamClient: Any = None
        self.client: Any = None
        self.client_task: asyncio.Task[Any] | None = None
        self.monitor_task: asyncio.Task[Any] | None = None
        self.login_lock, self.rooms_lock = asyncio.Lock(), asyncio.Lock()

        self.voices: dict[int, Any] = {}
        self.rooms: dict[int, Any] = {}
        self.live_cache: dict[int, list[dict[str, Any]]] = {}
        self.live_views: dict[int, dict[int, Any]] = {}
        self.live_watch_disabled: dict[int, set[int]] = {}
        self.last_action, self.last_error = "Idle", None
        self.command_count = self.command_delete_count = self.command_delete_failures = 0
        self.response_delete_count = self.response_delete_failures = 0

        self.voice = VoiceManager(self)
        self.live = LiveManager(self)
        self.commands = CommandRouter(self)


    def log(self, level: str, action: str, **fields: Any) -> None:
        self.activity_log.write(level, action, **fields)

    def _load_dependencies(self) -> None:
        if self.discord is not None:
            return
        try:
            import discord
            from discord.ext.native_voice import StreamClient, VoiceClient
        except Exception as exc:
            raise RuntimeError("Thiếu discord.py-self/discord-native-voice. Chạy install-windows.bat.") from exc
        self.discord, self.VoiceClient, self.StreamClient = discord, VoiceClient, StreamClient
        self.client = discord.Client()

        async def on_message(message):
            await self.handle_chat_message(message)

        self.client.event(on_message)

    @staticmethod
    def _snowflake(value: str | int, name: str) -> int:
        return snowflake(value, name)

    async def ensure_login(self, timeout: float = 35.0) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("Thiếu DISCORD_TOKEN trong .env")
        self._load_dependencies()
        if self.client.is_ready():
            self._ensure_monitor()
            return self.state()
        async with self.login_lock:
            if self.client.is_ready():
                self._ensure_monitor()
                return self.state()
            if self.client_task is None or self.client_task.done():
                self.last_action, self.last_error = "Connecting Discord user account", None
                self.log("ACTION", "Discord login", account="user-token")
                self.client_task = asyncio.create_task(self.client.start(self.token), name="discord-selfbot-client")
            ready = asyncio.create_task(self.client.wait_until_ready())
            try:
                done, _ = await asyncio.wait({ready, self.client_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if self.client_task in done and self.client_task.done() and self.client_task.exception():
                    raise RuntimeError(f"Discord login thất bại: {self.client_task.exception()}")
                if not self.client.is_ready():
                    raise TimeoutError("Hết thời gian chờ Discord ready.")
            finally:
                if not ready.done():
                    ready.cancel()
                    with suppress(asyncio.CancelledError):
                        await ready
        self.last_action, self.last_error = "Discord user account ready", None
        user = getattr(self.client, "user", None)
        self.log("OK", "Discord ready", userId=getattr(user, "id", None), user=str(user) if user else None)
        self._ensure_monitor()
        return self.state()

    def _ensure_monitor(self) -> None:
        if self.monitor_task is None or self.monitor_task.done():
            self.monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.auto_detect_interval)
                if not self.client or not self.client.is_ready():
                    continue
                for gid, room in list(self.rooms.items()):
                    try:
                        if not self.voice.state(gid).get("connected"):
                            continue
                        self.live_cache[gid] = self.voice.streamers(gid, room.channel_id)
                        if self.auto_watch_all_lives:
                            await self.live.join_all(gid, timeout=self.auto_watch_timeout)
                    except Exception as exc:
                        room.last_error = str(exc)
                        self.last_error = f"Monitor guild {gid}: {exc}"
                        self.log("ERROR", "Background live monitor failed", guild=gid)
                        self.log("WHY", "Monitor failure reason", reason=exc)
        except asyncio.CancelledError:
            pass

    # Thin public facade: keeps the old API while implementation stays split.
    async def join_room(self, guild_id, channel_id): return await self.voice.join(guild_id, channel_id)
    async def join_rooms(self, rooms, *, replace=False): return await self.voice.join_many(rooms, replace)
    async def leave_room(self, guild_id): return await self.voice.leave(guild_id)
    async def leave_all(self): return await self.voice.leave_all()
    def list_streamers(self, guild_id, channel_id): return self.voice.streamers(guild_id, channel_id)
    def room_state(self, guild_id): return self.voice.state(int(guild_id))
    async def join_live(self, guild_id, **kwargs): return await self.live.join_one(guild_id, **kwargs)
    async def join_all_lives(self, guild_id, *, timeout=5.0): return await self.live.join_all(guild_id, timeout)
    async def leave_live(self, guild_id, streamer_id=None): return await self.live.leave(guild_id, streamer_id)
    async def set_stream_watch(self, guild_id, streamer_id, mode="toggle"):
        return await self.live.set_watch_enabled(guild_id, streamer_id, mode)
    def live_state(self, guild_id): return self.live.state(int(guild_id))
    def live_states(self): return self.live.states()
    async def handle_chat_message(self, message): return await self.commands.handle(message)
    def chat_commands_enabled(self): return self.commands.enabled()

    def state(self) -> dict[str, Any]:
        ready = bool(self.client and self.client.is_ready())
        rooms = [self.voice.state(gid) for gid in sorted(self.rooms)]
        user = self.client.user if ready and self.client else None
        lives = self.live.states()
        return {
            "loggedIn": ready,
            "accountUser": str(user) if user else None,
            "accountUserId": str(user.id) if user else None,
            "roomCount": len(rooms),
            "rooms": rooms,
            "autoDetectInterval": self.auto_detect_interval,
            "selfBot": True,
            "officialBot": False,
            "goLiveDetection": True,
            "goLiveWatch": True,
            "liveViewCount": len(lives),
            "liveViews": lives,
            "disabledLiveWatch": {str(gid): [str(x) for x in sorted(ids)] for gid, ids in self.live_watch_disabled.items() if ids},
            "autoWatchAllLives": self.auto_watch_all_lives,
            "autoWatchTimeout": self.auto_watch_timeout,
            "chatCommands": self.chat_commands_enabled(),
            "commandPrefix": self.command_prefix,
            "commandOwnerCount": len(self.command_owner_ids),
            "commandCount": self.command_count,
            "autoDeleteCommandMessages": self.auto_delete_command_messages,
            "autoDeleteCommandDelay": self.auto_delete_command_delay,
            "commandDeleteCount": self.command_delete_count,
            "commandDeleteFailures": self.command_delete_failures,
            "autoDeleteCommandResponses": self.auto_delete_command_responses,
            "autoDeleteResponseDelay": self.auto_delete_response_delay,
            "responseDeleteCount": self.response_delete_count,
            "responseDeleteFailures": self.response_delete_failures,
            "lastAction": self.last_action,
            "lastError": self.last_error,
            "logFile": str(self.activity_log.path),
        }

    async def close(self) -> None:
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.monitor_task
        await self.leave_all()
        if self.client and not self.client.is_closed():
            with suppress(Exception):
                await self.client.close()
        self.log("INFO", "Bot shutdown complete")
        self.activity_log.close()
        if self.client_task and not self.client_task.done():
            self.client_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.client_task
