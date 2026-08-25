from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from core import RoomState, connected, snowflake


class VoiceManager:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def _channel(self, gid: int, cid: int):
        self.bot.log("ACTION", "Resolve voice channel", guild=gid, channel=cid)
        client = self.bot.client
        guild = client.get_guild(gid)
        if guild is None:
            self.bot.log("WHY", "Guild lookup failed", guild=gid, reason="account cannot see guild")
            raise RuntimeError(f"Tài khoản không thấy server {gid}.")
        channel = guild.get_channel(cid) or client.get_channel(cid)
        if channel is None:
            with suppress(Exception):
                channel = await client.fetch_channel(cid)
        if channel is None:
            self.bot.log("WHY", "Channel lookup failed", guild=gid, channel=cid, reason="channel not found")
            raise RuntimeError(f"Không tìm thấy channel {cid} trong server {gid}.")
        if int(getattr(getattr(channel, "guild", None), "id", 0)) != gid:
            self.bot.log("WHY", "Channel validation failed", guild=gid, channel=cid, reason="channel belongs to another guild")
            raise RuntimeError("channelId không thuộc guildId đã nhập.")
        if not callable(getattr(channel, "connect", None)):
            self.bot.log("WHY", "Channel validation failed", guild=gid, channel=cid, reason="not Voice/Stage")
            raise RuntimeError("channelId không phải Voice/Stage channel.")
        self.bot.log(
            "OK",
            "Voice channel resolved",
            guild=gid,
            channel=cid,
            guildName=getattr(guild, "name", None),
            channelName=getattr(channel, "name", None),
        )
        return guild, channel

    async def join(self, guild_id: str | int, channel_id: str | int) -> dict[str, Any]:
        await self.bot.ensure_login()
        gid, cid = snowflake(guild_id, "guildId"), snowflake(channel_id, "channelId")
        self.bot.log("ACTION", "Join voice requested", guild=gid, channel=cid)
        try:
            guild, channel = await self._channel(gid, cid)

            async with self.bot.rooms_lock:
                voice = self.bot.voices.get(gid)
                if connected(voice):
                    current = getattr(getattr(voice, "channel", None), "id", None)
                    if current != cid:
                        self.bot.log("ACTION", "Move voice connection", guild=gid, fromChannel=current, toChannel=cid)
                        await self.bot.live.leave(gid)
                        await voice.move_to(channel)
                        self.bot.last_action = f"Moved guild {gid} to room {cid}"
                        self.bot.log("OK", "Voice moved", guild=gid, channel=cid)
                    else:
                        self.bot.log("OK", "Voice already connected", guild=gid, channel=cid)
                else:
                    if voice is not None:
                        with suppress(Exception):
                            await voice.disconnect(force=True)
                    self.bot.log("ACTION", "Connect voice", guild=gid, channel=cid, selfDeaf=True)
                    voice = await channel.connect(
                        cls=self.bot.VoiceClient,
                        self_deaf=True,
                        timeout=30.0,
                        reconnect=True,
                    )
                    self.bot.voices[gid] = voice
                    self.bot.last_action = f"Joined guild {gid} room {cid}"
                    self.bot.log("OK", "Voice connected", guild=gid, channel=cid)

                self.bot.rooms[gid] = RoomState(
                    gid, cid, getattr(guild, "name", None), getattr(channel, "name", None), time.time()
                )
                self.bot.live_cache[gid] = self.streamers(gid, cid)
                state = self.state(gid)

            if self.bot.auto_watch_all_lives:
                self.bot.log("ACTION", "Auto-watch active lives after join", guild=gid, channel=cid)
                try:
                    state["autoLive"] = await self.bot.live.join_all(gid, timeout=self.bot.auto_watch_timeout)
                    self.bot.log(
                        "OK",
                        "Auto-watch scan completed",
                        guild=gid,
                        detected=state["autoLive"].get("detectedCount", 0),
                        watching=state["autoLive"].get("watchingCount", 0),
                    )
                except Exception as exc:
                    state["autoLive"] = {
                        "guildId": str(gid),
                        "ok": False,
                        "error": str(exc),
                        "watchingCount": len(self.bot.live.active_ids(gid)),
                    }
                    self.bot.log("ERROR", "Auto-watch after voice join failed", guild=gid, channel=cid)
                    self.bot.log("WHY", "Auto-watch failure reason", guild=gid, reason=exc)
            return state
        except Exception as exc:
            self.bot.last_error = str(exc)
            self.bot.log("ERROR", "Join voice failed", guild=gid, channel=cid)
            self.bot.log("WHY", "Join voice failure reason", guild=gid, channel=cid, reason=exc)
            raise

    async def join_many(self, rooms: list[dict[str, Any]], replace: bool = False) -> dict[str, Any]:
        await self.bot.ensure_login()
        self.bot.log("ACTION", "Join many voice rooms", count=len(rooms), replace=replace)
        if replace:
            await self.leave_all()
        results = []
        for room in rooms:
            try:
                results.append({"ok": True, "room": await self.join(room["guildId"], room["channelId"])})
            except Exception as exc:
                results.append({
                    "ok": False,
                    "guildId": str(room.get("guildId", "")),
                    "channelId": str(room.get("channelId", "")),
                    "error": str(exc),
                })
        self.bot.log("OK", "Join many completed", success=sum(1 for x in results if x["ok"]), failed=sum(1 for x in results if not x["ok"]))
        return {"results": results, "state": self.bot.state()}

    async def leave(self, guild_id: str | int) -> dict[str, Any]:
        gid = snowflake(guild_id, "guildId")
        self.bot.log("ACTION", "Leave voice requested", guild=gid)
        await self.bot.live.leave(gid)
        voice = self.bot.voices.pop(gid, None)
        if voice is not None:
            with suppress(Exception):
                await voice.disconnect(force=True)
        self.bot.rooms.pop(gid, None)
        self.bot.live_cache.pop(gid, None)
        self.bot.last_action = f"Left guild {gid}"
        self.bot.log("OK", "Voice left", guild=gid)
        return self.bot.state()

    async def leave_all(self) -> dict[str, Any]:
        gids = list(set(self.bot.rooms) | set(self.bot.voices))
        self.bot.log("ACTION", "Leave all voice rooms", count=len(gids))
        for gid in gids:
            await self.leave(gid)
        self.bot.last_action = "Left all rooms"
        self.bot.log("OK", "Left all voice rooms", count=len(gids))
        return self.bot.state()

    def streamers(self, guild_id: str | int, channel_id: str | int) -> list[dict[str, Any]]:
        gid, cid = snowflake(guild_id, "guildId"), snowflake(channel_id, "channelId")
        client = self.bot.client
        guild = client.get_guild(gid) if client and client.is_ready() else None
        channel = guild.get_channel(cid) if guild else None
        if channel is None:
            return []
        return [
            {
                "id": str(member.id),
                "username": getattr(member, "name", None),
                "displayName": getattr(member, "display_name", None),
                "streaming": True,
            }
            for member in (getattr(channel, "members", []) or [])
            if bool(getattr(getattr(member, "voice", None), "self_stream", False))
        ]

    def state(self, gid: int) -> dict[str, Any]:
        room = self.bot.rooms.get(gid)
        if room is None:
            return {"guildId": str(gid), "connected": False}
        data = room.to_dict()
        data["connected"] = connected(self.bot.voices.get(gid))
        data["streamers"] = self.bot.live_cache.get(gid, [])
        data["streamerCount"] = len(data["streamers"])
        return data
