from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable


Handler = Callable[[Any, list[str]], Awaitable[str]]


class CommandRouter:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.handlers: dict[str, Handler] = {
            "help": self.help,
            "status": self.status,
            "join": self.join,
            "joinhere": self.joinhere,
            "joinme": self.joinme,
            "rooms": self.rooms,
            "live": self.live,
            "livehere": self.livehere,
            "liveall": self.liveall,
            "liveallhere": self.liveallhere,
            "lives": self.lives,
            "leave": self.leave,
            "leavehere": self.leavehere,
            "leaveall": self.leaveall,
            "autodelete": self.autodelete,
            "replydelete": self.replydelete,
            "stream": self.stream_control,
        }

    def enabled(self) -> bool:
        return bool(self.bot.command_prefix and self.bot.command_owner_ids)

    def allowed(self, message: Any) -> bool:
        try:
            return int(message.author.id) in self.bot.command_owner_ids
        except (AttributeError, TypeError, ValueError):
            return False

    async def _send(self, message: Any, text: str):
        send = getattr(getattr(message, "channel", None), "send", None)
        return await send(text) if callable(send) else None

    async def _delete(self, message: Any, delay: float, counter: str, failures: str) -> bool:
        delete = getattr(message, "delete", None)
        if not callable(delete):
            setattr(self.bot, failures, getattr(self.bot, failures) + 1)
            return False
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await delete()
            setattr(self.bot, counter, getattr(self.bot, counter) + 1)
            return True
        except Exception as exc:
            setattr(self.bot, failures, getattr(self.bot, failures) + 1)
            self.bot.log("ERROR", "Message auto-delete failed", messageType=counter)
            self.bot.log("WHY", "Delete failure reason", reason=exc)
            return False

    async def handle(self, message: Any) -> bool:
        if not self.enabled() or not self.allowed(message):
            return False
        content = str(getattr(message, "content", "") or "").strip()
        if not content.startswith(self.bot.command_prefix):
            return False
        parts = content[len(self.bot.command_prefix):].strip().split()
        if not parts or parts[0].lower() not in self.handlers:
            return False
        name, args = parts[0].lower(), parts[1:]
        delete_command = self.bot.auto_delete_command_messages
        delete_reply = self.bot.auto_delete_command_responses
        self.bot.command_count += 1
        author_id = getattr(getattr(message, "author", None), "id", "?")
        guild_id = getattr(getattr(message, "guild", None), "id", None)
        command = f"{self.bot.command_prefix}{name}"
        self.bot.log("CMD", command, user=author_id, guild=guild_id, args=" ".join(args) or "-")
        try:
            text = await self.handlers[name](message, args)
            self.bot.last_error = None
            self.bot.log("OK", "Command completed", command=command, result=text)
        except Exception as exc:
            self.bot.last_error = str(exc)
            text = f"Lỗi: {exc}"
            self.bot.log("ERROR", "Command failed", command=command, user=author_id, guild=guild_id)
            self.bot.log("WHY", "Command failure reason", reason=exc)
        self.bot.last_action = f"Chat command {command} by {author_id}"
        response = await self._send(message, text)
        if delete_command:
            await self._delete(message, self.bot.auto_delete_command_delay, "command_delete_count", "command_delete_failures")
        if delete_reply and response is not None:
            await self._delete(response, self.bot.auto_delete_response_delay, "response_delete_count", "response_delete_failures")
        elif delete_reply:
            self.bot.response_delete_failures += 1
        return True

    def _usage(self, name: str, args: str = "") -> ValueError:
        tail = f" {args}" if args else ""
        return ValueError(f"Cú pháp: {self.bot.command_prefix}{name}{tail}")

    async def help(self, _m: Any, _a: list[str]) -> str:
        p = self.bot.command_prefix
        return (
            f"{p}status | {p}rooms | {p}lives\n"
            f"{p}join <guild> <room> | {p}joinhere <room> | {p}joinme\n"
            f"{p}live <guild> [user] | {p}liveall <guild> | {p}liveallhere\n"
            f"{p}stream <@user> [on|off|status]\n"
            f"{p}leave <guild> | {p}leavehere | {p}leaveall\n"
            f"{p}autodelete on|off|status | {p}replydelete on|off|status"
        )

    async def status(self, _m: Any, _a: list[str]) -> str:
        s = self.bot.state()
        return f"loggedIn={s['loggedIn']} rooms={s['roomCount']} lives={s['liveViewCount']} last={s['lastAction']}"

    async def join(self, _m: Any, a: list[str]) -> str:
        if len(a) != 2:
            raise self._usage("join", "<guild_id> <voice_channel_id>")
        r = await self.bot.join_room(*a)
        return f"Đã join {r['guildId']} -> {r['channelId']} | auto live={r.get('autoLive', {}).get('watchingCount', 0)}"

    async def joinhere(self, m: Any, a: list[str]) -> str:
        if len(a) != 1:
            raise self._usage("joinhere", "<voice_channel_id>")
        if getattr(m, "guild", None) is None:
            raise RuntimeError("Lệnh joinhere phải gửi trong server Discord.")
        return await self.join(m, [str(m.guild.id), a[0]])

    async def joinme(self, m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("joinme")
        channel = getattr(getattr(getattr(m, "author", None), "voice", None), "channel", None)
        if getattr(m, "guild", None) is None or channel is None:
            raise RuntimeError("Bạn phải đang ở voice channel trong server này.")
        r = await self.bot.join_room(m.guild.id, channel.id)
        return f"Đã join voice của bạn: {r['guildId']} -> {r['channelId']} | auto live={r.get('autoLive', {}).get('watchingCount', 0)}"

    async def rooms(self, _m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("rooms")
        rooms = self.bot.state()["rooms"]
        return "Chưa join voice room nào." if not rooms else "Rooms:\n" + "\n".join(
            f"{x['guildId']} -> {x['channelId']} ({'connected' if x['connected'] else 'disconnected'})" for x in rooms
        )

    async def live(self, _m: Any, a: list[str]) -> str:
        if len(a) not in (1, 2):
            raise self._usage("live", "<guild_id> [streamer_id]")
        s = await self.bot.join_live(a[0], streamer_id=a[1] if len(a) == 2 else None)
        return f"Đang watch live guild {s['guildId']} streamer {s['streamerId']}"

    async def livehere(self, m: Any, a: list[str]) -> str:
        if len(a) > 1:
            raise self._usage("livehere", "[streamer_id]")
        if getattr(m, "guild", None) is None:
            raise RuntimeError("Lệnh livehere phải gửi trong server Discord.")
        return await self.live(m, [str(m.guild.id), *a])

    async def liveall(self, _m: Any, a: list[str]) -> str:
        if len(a) != 1:
            raise self._usage("liveall", "<guild_id>")
        d = await self.bot.join_all_lives(a[0], timeout=self.bot.auto_watch_timeout)
        return f"Live guild {d['guildId']}: {d['watchingCount']}/{d['detectedCount']} đang watch"

    async def liveallhere(self, m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("liveallhere")
        if getattr(m, "guild", None) is None:
            raise RuntimeError("Lệnh liveallhere phải gửi trong server Discord.")
        return await self.liveall(m, [str(m.guild.id)])

    async def lives(self, _m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("lives")
        rows = self.bot.live_states()
        return "Chưa watch live nào." if not rows else "Live views:\n" + "\n".join(
            f"{x['guildId']} -> streamer {x['streamerId']}" for x in rows
        )


    @staticmethod
    def _mention_id(value: str) -> int:
        text = str(value or "").strip()
        match = re.fullmatch(r"<@!?(\d+)>", text)
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        raise ValueError("User phải ở dạng <@id> hoặc Discord user ID.")

    async def stream_control(self, m: Any, a: list[str]) -> str:
        if len(a) not in (1, 2):
            raise self._usage("stream", "<@user> [on|off|status]")
        if getattr(m, "guild", None) is None:
            raise RuntimeError("Lệnh stream phải gửi trong server Discord.")
        gid = int(m.guild.id)
        sid = self._mention_id(a[0])
        mode = a[1].lower() if len(a) == 2 else "toggle"
        if mode not in {"on", "off", "toggle", "status"}:
            raise ValueError("Chế độ chỉ nhận on|off|status; bỏ trống để toggle.")
        state = await self.bot.set_stream_watch(gid, sid, mode)
        status = "ON" if state["enabled"] else "OFF"
        watching = "watching" if state["watching"] else "not-watching"
        return f"Stream <@{sid}>: {status} ({watching})"

    async def leave(self, _m: Any, a: list[str]) -> str:
        if len(a) != 1:
            raise self._usage("leave", "<guild_id>")
        await self.bot.leave_room(a[0])
        return f"Đã rời guild {a[0]}"

    async def leavehere(self, m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("leavehere")
        if getattr(m, "guild", None) is None:
            raise RuntimeError("Lệnh leavehere phải gửi trong server Discord.")
        return await self.leave(m, [str(m.guild.id)])

    async def leaveall(self, _m: Any, a: list[str]) -> str:
        if a:
            raise self._usage("leaveall")
        await self.bot.leave_all()
        return "Đã rời tất cả voice rooms."

    async def _toggle(self, attr: str, label: str, a: list[str]) -> str:
        if len(a) > 1:
            raise ValueError("Chỉ nhận on|off|status")
        mode = a[0].lower() if a else "status"
        if mode in {"on", "1", "true", "yes"}:
            setattr(self.bot, attr, True)
        elif mode in {"off", "0", "false", "no"}:
            setattr(self.bot, attr, False)
        elif mode != "status":
            raise ValueError("Chỉ nhận on|off|status")
        return f"{label}: {'ON' if getattr(self.bot, attr) else 'OFF'}"

    async def autodelete(self, _m: Any, a: list[str]) -> str:
        return await self._toggle("auto_delete_command_messages", "Auto-delete command messages", a)

    async def replydelete(self, _m: Any, a: list[str]) -> str:
        return await self._toggle("auto_delete_command_responses", "Auto-delete bot responses", a)
