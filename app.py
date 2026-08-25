from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from bot import CleanSelfBot
from config import Settings
from models import LiveJoinRequest, MultiRoomRequest, RoomRequest

cfg = Settings.from_env()
bot = CleanSelfBot(
    cfg.token,
    auto_detect_interval=cfg.auto_detect_interval,
    command_prefix=cfg.command_prefix,
    command_owner_ids=cfg.command_owner_ids,
    auto_delete_command_messages=cfg.auto_delete_command_messages,
    auto_delete_command_delay=cfg.auto_delete_command_delay,
    auto_delete_command_responses=cfg.auto_delete_command_responses,
    auto_delete_response_delay=cfg.auto_delete_response_delay,
    auto_watch_all_lives=cfg.auto_watch_all_lives,
    auto_watch_timeout=cfg.auto_watch_timeout,
    log_file=cfg.log_file,
    log_to_terminal=cfg.log_to_terminal,
    log_max_bytes=cfg.log_max_bytes,
    log_backup_count=cfg.log_backup_count,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if cfg.token:
        try:
            await bot.ensure_login()
        except Exception as exc:
            bot.last_error = str(exc)
    yield
    await bot.close()


app = FastAPI(title="Discord Voice Self-Bot V1.2.3", version="1.2.3", lifespan=lifespan)


@app.middleware("http")
async def auth(request: Request, call_next):
    if cfg.api_key and request.url.path.startswith("/api/") and request.headers.get("x-api-key") != cfg.api_key:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized"})
    return await call_next(request)


def ok(state=None, **extra):
    data = {"ok": True, **extra}
    if state is not None:
        data["state"] = state
    return data


def fail(exc: Exception, code: int = 400):
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@app.get("/health")
async def health():
    return ok(
        service="discord-voice-selfbot-v1.2.3",
        selfBot=True,
        officialBot=False,
        multiGuild=True,
        goLiveDetection=True,
        goLiveWatch=True,
        chatCommands=True,
        commandPrefix=cfg.command_prefix,
        commandOwnerCount=len(cfg.command_owner_ids or set()),
        autoDeleteCommandMessages=cfg.auto_delete_command_messages,
        autoDeleteCommandDelay=cfg.auto_delete_command_delay,
        autoDeleteCommandResponses=cfg.auto_delete_command_responses,
        autoDeleteResponseDelay=cfg.auto_delete_response_delay,
        autoWatchAllLives=cfg.auto_watch_all_lives,
        autoWatchTimeout=cfg.auto_watch_timeout,
        logFile=str(bot.activity_log.path),
        logToTerminal=cfg.log_to_terminal,
    )


@app.get("/api/status")
async def status(): return ok(bot.state())


@app.post("/api/auth/login")
async def login():
    try: return ok(await bot.ensure_login())
    except Exception as exc: fail(exc)


@app.post("/api/rooms/join")
async def room_join(body: RoomRequest):
    try: return ok(await bot.join_room(body.guildId, body.channelId))
    except Exception as exc: fail(exc)


@app.post("/api/rooms/join-many")
async def room_join_many(body: MultiRoomRequest):
    try: return ok(**(await bot.join_rooms([x.model_dump() for x in body.rooms], replace=body.replace)))
    except Exception as exc: fail(exc)


@app.get("/api/rooms")
async def rooms(): return ok(rooms=bot.state()["rooms"])


@app.get("/api/rooms/{guild_id}/streamers")
async def streamers(guild_id: str):
    try:
        gid = bot._snowflake(guild_id, "guildId")
        room = bot.rooms.get(gid)
        if not room: raise RuntimeError("Guild này chưa join voice.")
        return ok(streamers=bot.list_streamers(gid, room.channel_id))
    except Exception as exc: fail(exc)


@app.post("/api/live/join")
async def live_join(body: LiveJoinRequest):
    try:
        return ok(await bot.join_live(body.guildId, channel_id=body.channelId, streamer_id=body.streamerId, timeout=body.timeout))
    except Exception as exc: fail(exc)


@app.post("/api/live/{guild_id}/join-all")
async def live_join_all(guild_id: str):
    try: return ok(await bot.join_all_lives(guild_id, timeout=cfg.auto_watch_timeout))
    except Exception as exc: fail(exc)


@app.get("/api/live")
async def live_list(): return ok(liveViews=bot.live_states())


@app.get("/api/live/{guild_id}")
async def live_status(guild_id: str):
    try: return ok(bot.live_state(bot._snowflake(guild_id, "guildId")))
    except Exception as exc: fail(exc)


@app.post("/api/live/{guild_id}/leave")
async def live_leave(guild_id: str):
    try: return ok(await bot.leave_live(guild_id))
    except Exception as exc: fail(exc, 500)


@app.post("/api/rooms/{guild_id}/leave")
async def room_leave(guild_id: str):
    try: return ok(await bot.leave_room(guild_id))
    except Exception as exc: fail(exc, 500)


@app.post("/api/rooms/leave-all")
async def leave_all():
    try: return ok(await bot.leave_all())
    except Exception as exc: fail(exc, 500)


if __name__ == "__main__":
    print("Discord Voice Self-Bot V1.2.3", flush=True)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="critical", access_log=False)
