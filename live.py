from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Any

from core import connected, snowflake


class LiveManager:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @staticmethod
    def owner_id(stream: Any) -> int | None:
        value = getattr(stream, "owner_id", None) or getattr(getattr(stream, "owner", None), "id", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def channel_id(stream: Any) -> int | None:
        value = getattr(stream, "channel_id", None) or getattr(getattr(stream, "channel", None), "id", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _cached_stream(self, gid: int, cid: int, sid: int | None = None):
        voice = self.bot.voices.get(gid)
        if not connected(voice):
            return None
        own_id = getattr(getattr(self.bot.client, "user", None), "id", None)
        for stream in list(getattr(voice, "streams", ()) or ()):
            owner = self.owner_id(stream)
            channel = self.channel_id(stream)
            if owner is None or owner == own_id or bool(getattr(stream, "unavailable", False)):
                continue
            if channel is not None and channel != cid:
                continue
            if sid is None or owner == sid:
                return stream
        if sid is not None and callable(getattr(voice, "get_stream", None)):
            guild = self.bot.client.get_guild(gid)
            owner = guild.get_member(sid) if guild and callable(getattr(guild, "get_member", None)) else None
            owner = owner or self.bot.client.get_user(sid)
            if owner is not None:
                with suppress(Exception):
                    return voice.get_stream(owner)
        return None

    def detected_ids(self, gid: int, cid: int, *, include_disabled: bool = False) -> list[int]:
        ids: list[int] = []
        disabled = self.bot.live_watch_disabled.get(gid, set())
        for item in self.bot.voice.streamers(gid, cid):
            try:
                sid = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if (include_disabled or sid not in disabled) and sid not in ids:
                ids.append(sid)
        voice = self.bot.voices.get(gid)
        for stream in list(getattr(voice, "streams", ()) or ()) if voice else []:
            sid, channel = self.owner_id(stream), self.channel_id(stream)
            if sid is None or bool(getattr(stream, "unavailable", False)):
                continue
            if channel is not None and channel != cid:
                continue
            if (include_disabled or sid not in disabled) and sid not in ids:
                ids.append(sid)
        return ids

    async def _watch_uncached(self, gid: int, cid: int, sid: int, timeout: float):
        voice = self.bot.voices.get(gid)
        watch = getattr(voice, "watch_stream", None)
        key_cls = getattr(self.bot.discord, "StreamKey", None)
        factory = getattr(key_cls, "from_guild", None) if key_cls else None
        if not connected(voice) or not callable(watch) or not callable(factory):
            raise RuntimeError("Runtime không hỗ trợ watch_stream(StreamKey).")
        key = factory(guild_id=gid, channel_id=cid, owner_id=sid)
        self.bot.log("ACTION", "Watch uncached stream", guild=gid, channel=cid, streamer=sid, source="stream-key")
        return await watch(key, cls=self.bot.StreamClient, timeout=timeout, reconnect=True)

    async def _stop_view(self, gid: int, sid: int, view: Any) -> dict[str, Any]:
        """Stop a watched Go Live at both Discord gateway and media-client levels."""
        errors: list[str] = []
        self.bot.log("ACTION", "Stop live view", guild=gid, streamer=sid)
        stream = getattr(view, "stream", None)
        if stream is None:
            room = self.bot.rooms.get(gid)
            if room is not None:
                stream = self._cached_stream(gid, room.channel_id, sid)

        # discord.py-self Stream.delete(): for another user's stream this disconnects
        # the current account from the watched stream at the gateway layer.
        delete = getattr(stream, "delete", None) if stream is not None else None
        if callable(delete):
            try:
                await delete()
                self.bot.log("OK", "Discord stream watch detached", guild=gid, streamer=sid, method="stream.delete")
            except Exception as exc:
                errors.append(f"stream.delete: {exc}")
                self.bot.log("WHY", "Stream.delete failed", guild=gid, streamer=sid, reason=exc)

        disconnect = getattr(view, "disconnect", None)
        if callable(disconnect):
            try:
                await disconnect(force=True)
                self.bot.log("OK", "StreamClient disconnect called", guild=gid, streamer=sid)
            except Exception as exc:
                errors.append(f"view.disconnect: {exc}")
                self.bot.log("WHY", "StreamClient disconnect failed", guild=gid, streamer=sid, reason=exc)

        cleanup = getattr(view, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
                self.bot.log("OK", "StreamClient cleanup called", guild=gid, streamer=sid)
            except Exception as exc:
                errors.append(f"view.cleanup: {exc}")
                self.bot.log("WHY", "StreamClient cleanup failed", guild=gid, streamer=sid, reason=exc)

        # Give the protocol a brief moment to update is_connected/cache state.
        for _ in range(10):
            if not connected(view):
                break
            await asyncio.sleep(0.05)

        stopped = not connected(view)
        if not stopped and not errors:
            errors.append("StreamClient vẫn báo connected sau khi stop")
        if stopped:
            self.bot.log("OK", "Live view stopped", guild=gid, streamer=sid)
        else:
            self.bot.log("ERROR", "Live view stop incomplete", guild=gid, streamer=sid)
            self.bot.log("WHY", "Live view still active", guild=gid, streamer=sid, reason="; ".join(errors))
        return {"stopped": stopped, "errors": errors}

    def active_ids(self, gid: int) -> list[int]:
        return sorted(sid for sid, view in self.bot.live_views.get(gid, {}).items() if connected(view))

    def state(self, gid: int) -> dict[str, Any]:
        ids = self.active_ids(gid)
        return {
            "guildId": str(gid),
            "watching": bool(ids),
            "streamerId": str(ids[0]) if len(ids) == 1 else None,
            "streamerIds": [str(x) for x in ids],
            "viewCount": len(ids),
        }

    def states(self) -> list[dict[str, Any]]:
        return [
            {"guildId": str(gid), "watching": True, "streamerId": str(sid)}
            for gid in sorted(self.bot.live_views)
            for sid in self.active_ids(gid)
        ]

    async def join_one(
        self,
        guild_id: str | int,
        *,
        channel_id: str | int | None = None,
        streamer_id: str | int | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        await self.bot.ensure_login()
        gid = snowflake(guild_id, "guildId")
        self.bot.log("ACTION", "Join live requested", guild=gid, streamer=streamer_id or "auto", channel=channel_id or "current")
        room = self.bot.rooms.get(gid)
        if channel_id is not None:
            cid = snowflake(channel_id, "channelId")
            if room is None or room.channel_id != cid:
                await self.bot.voice.join(gid, cid)
                room = self.bot.rooms.get(gid)
        if room is None:
            raise RuntimeError("Guild này chưa join voice.")

        requested = snowflake(streamer_id, "streamerId") if streamer_id is not None else None
        if requested is not None and requested in self.bot.live_watch_disabled.get(gid, set()):
            raise RuntimeError(f"Stream của user {requested} đang bị tắt bằng kstream.")
        sid, stream = requested, None
        timeout = max(0.5, min(float(timeout), 30.0))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            stream = self._cached_stream(gid, room.channel_id, sid)
            if stream is not None:
                sid = self.owner_id(stream)
                break
            detected = self.detected_ids(gid, room.channel_id)
            if sid is None and detected:
                sid = detected[0]
            if sid is not None:
                break
            await asyncio.sleep(0.25)

        if sid is None:
            voice = self.bot.voices.get(gid)
            self.bot.log(
                "WHY",
                "Go Live detection found nothing",
                guild=gid,
                channel=room.channel_id,
                voiceState=len(self.detected_ids(gid, room.channel_id)),
                streamCache=len(list(getattr(voice, "streams", ()) or ())) if voice else 0,
            )
            raise RuntimeError(
                "Không tìm thấy Go Live stream đang active "
                f"(voiceState={len(self.detected_ids(gid, room.channel_id))}, "
                f"streamCache={len(list(getattr(voice, 'streams', ()) or ())) if voice else 0})."
            )

        # Re-check after detection/waits so a concurrent kstream ... off cannot race
        # with the auto-watch monitor and reopen the stream.
        if sid in self.bot.live_watch_disabled.get(gid, set()):
            raise RuntimeError(f"Stream của user {sid} đang bị tắt bằng kstream.")

        views = self.bot.live_views.setdefault(gid, {})
        if connected(views.get(sid)):
            self.bot.log("OK", "Live already being watched", guild=gid, streamer=sid)
            return {"guildId": str(gid), "watching": True, "streamerId": str(sid)}
        old = views.pop(sid, None)
        if old is not None:
            await self._stop_view(gid, sid, old)

        if stream is not None:
            watch = getattr(stream, "watch", None)
            if not callable(watch):
                raise RuntimeError("Stream object không hỗ trợ watch().")
            self.bot.log("ACTION", "Watch cached stream", guild=gid, streamer=sid, source="cache")
            view = await watch(cls=self.bot.StreamClient, timeout=timeout, reconnect=True)
            source = "cache"
        else:
            view = await self._watch_uncached(gid, room.channel_id, sid, timeout)
            source = "stream-key"

        # A kstream ... off may have arrived while the watch handshake was awaiting.
        # If so, immediately tear down the newly-created view instead of storing it.
        if sid in self.bot.live_watch_disabled.get(gid, set()):
            await self._stop_view(gid, sid, view)
            raise RuntimeError(f"Stream của user {sid} vừa bị tắt trong lúc đang kết nối.")

        views[sid] = view
        self.bot.last_action = f"Watching Go Live {sid} in guild {gid} via {source}"
        self.bot.last_error = None
        self.bot.log("OK", "Watching Go Live", guild=gid, channel=room.channel_id, streamer=sid, source=source)
        return {"guildId": str(gid), "watching": True, "streamerId": str(sid)}

    async def join_all(self, guild_id: str | int, timeout: float = 5.0) -> dict[str, Any]:
        await self.bot.ensure_login()
        gid = snowflake(guild_id, "guildId")
        room = self.bot.rooms.get(gid)
        if room is None:
            raise RuntimeError("Guild này chưa join voice.")
        ids = self.detected_ids(gid, room.channel_id)
        self.bot.log("ACTION", "Scan all active Go Live streams", guild=gid, channel=room.channel_id, detected=len(ids))
        results = []
        for sid in ids:
            try:
                results.append({"ok": True, "state": await self.join_one(gid, streamer_id=sid, timeout=timeout)})
            except Exception as exc:
                results.append({"ok": False, "streamerId": str(sid), "error": str(exc)})
                self.bot.log("ERROR", "Watch detected live failed", guild=gid, streamer=sid)
                self.bot.log("WHY", "Watch detected live failure reason", guild=gid, streamer=sid, reason=exc)
        active = self.active_ids(gid)
        self.bot.last_action = f"Auto-watch guild {gid}: {len(active)}/{len(ids)} active Go Live streams"
        self.bot.log("OK", "Live scan completed", guild=gid, detected=len(ids), watching=len(active))
        return {
            "guildId": str(gid),
            "channelId": str(room.channel_id),
            "detectedCount": len(ids),
            "watchingCount": len(active),
            "streamerIds": [str(x) for x in active],
            "results": results,
        }

    async def set_watch_enabled(self, guild_id: str | int, streamer_id: str | int, mode: str = "toggle") -> dict[str, Any]:
        gid = snowflake(guild_id, "guildId")
        sid = snowflake(streamer_id, "streamerId")
        mode = str(mode or "toggle").lower()
        disabled = self.bot.live_watch_disabled.setdefault(gid, set())
        self.bot.log("ACTION", "Stream watch control", guild=gid, streamer=sid, mode=mode)

        if mode == "status":
            enabled = sid not in disabled
        else:
            if mode == "toggle":
                mode = "on" if sid in disabled else "off"
            if mode == "off":
                # Disable first so the background auto-watch loop cannot reopen
                # this stream while its StreamClient is being torn down.
                disabled.add(sid)
                self.bot.log("ACTION", "Disable and stop selected stream", guild=gid, streamer=sid)
                stopped_state = await self.leave(gid, sid)
                enabled = False
                if connected(self.bot.live_views.get(gid, {}).get(sid)):
                    details = stopped_state.get("stopResults", {}).get(str(sid), {})
                    errors = "; ".join(details.get("errors", [])) or "unknown stop failure"
                    raise RuntimeError(f"Đã nhận OFF nhưng StreamClient chưa dừng: {errors}")
            elif mode == "on":
                disabled.discard(sid)
                self.bot.log("ACTION", "Enable selected stream", guild=gid, streamer=sid)
                if not disabled:
                    self.bot.live_watch_disabled.pop(gid, None)
                enabled = True
                room = self.bot.rooms.get(gid)
                if room is not None and sid in self.detected_ids(gid, room.channel_id, include_disabled=True):
                    try:
                        await self.join_one(gid, streamer_id=sid, timeout=self.bot.auto_watch_timeout)
                    except Exception as exc:
                        self.bot.last_error = str(exc)
            else:
                raise ValueError("mode phải là on|off|toggle|status")

        watching = connected(self.bot.live_views.get(gid, {}).get(sid))
        self.bot.last_action = f"Stream watch {gid}/{sid}: {'ON' if enabled else 'OFF'}"
        self.bot.log("OK", "Stream watch state updated", guild=gid, streamer=sid, enabled=enabled, watching=watching)
        return {
            "guildId": str(gid),
            "streamerId": str(sid),
            "enabled": enabled,
            "watching": watching,
        }

    async def leave(self, guild_id: str | int, streamer_id: str | int | None = None) -> dict[str, Any]:
        gid = snowflake(guild_id, "guildId")
        views = self.bot.live_views.get(gid, {})
        targets = [snowflake(streamer_id, "streamerId")] if streamer_id is not None else list(views)
        self.bot.log("ACTION", "Stop live watch requested", guild=gid, streamer=streamer_id or "all", targets=len(targets))
        stop_results: dict[str, Any] = {}
        for sid in targets:
            view = views.get(sid)
            if view is None:
                continue
            result = await self._stop_view(gid, sid, view)
            stop_results[str(sid)] = result
            # Only remove a view from our state after the underlying protocol
            # actually reports disconnected. This prevents false "OFF" replies.
            if result.get("stopped"):
                views.pop(sid, None)
        if not views:
            self.bot.live_views.pop(gid, None)
        self.bot.last_action = f"Stopped watching Go Live in guild {gid}"
        state = self.state(gid)
        self.bot.log("OK", "Stop live watch completed", guild=gid, remaining=state["viewCount"])
        state["stopResults"] = stop_results
        return state
