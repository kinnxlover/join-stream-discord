from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from multiguild_bot import MultiGuildSelfBot


class FakeVoiceState:
    def __init__(self, streaming: bool):
        self.self_stream = streaming


class FakeMember:
    def __init__(self, member_id: int, name: str, streaming: bool):
        self.id = member_id
        self.name = name
        self.display_name = name
        self.voice = FakeVoiceState(streaming)


class FakeStreamClient:
    def __init__(self, stream=None):
        self.connected = True
        self.disconnects = 0
        self.cleanups = 0
        self.stream = stream

    def is_connected(self):
        return self.connected

    async def disconnect(self, force=False):
        self.connected = False
        self.disconnects += 1

    def cleanup(self):
        self.cleanups += 1


class FakeStream:
    def __init__(self, owner_id: int, channel_id: int):
        self.owner_id = owner_id
        self.channel_id = channel_id
        self.unavailable = False
        self.watch_calls = []
        self.client = None
        self.deletes = 0

    async def watch(self, *, cls, timeout=30.0, reconnect=True):
        self.watch_calls.append({"cls": cls, "timeout": timeout, "reconnect": reconnect})
        self.client = FakeStreamClient(self)
        return self.client

    async def delete(self):
        self.deletes += 1
        if self.client is not None:
            self.client.connected = False


class FakeVoice:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.moves = []
        self.disconnects = 0
        self.streams = []
        self.watch_stream_calls = []

    def is_connected(self):
        return self.connected

    async def move_to(self, channel):
        self.channel = channel
        self.moves.append(channel.id)

    async def disconnect(self, force=False):
        self.connected = False
        self.disconnects += 1

    def get_stream(self, owner):
        for stream in self.streams:
            if stream.owner_id == owner.id:
                return stream
        return None

    async def watch_stream(self, stream_key, *, cls, timeout=30.0, reconnect=True):
        self.watch_stream_calls.append({
            "stream_key": stream_key, "cls": cls, "timeout": timeout, "reconnect": reconnect
        })
        return FakeStreamClient()


class FakeChannel:
    def __init__(self, cid: int, guild, name: str):
        self.id = cid
        self.guild = guild
        self.name = name
        self.members = []
        self.connect_calls = []
        self.voice = None

    async def connect(self, **kwargs):
        self.connect_calls.append(kwargs)
        self.voice = FakeVoice(self)
        return self.voice


class FakeGuild:
    def __init__(self, gid: int, name: str):
        self.id = gid
        self.name = name
        self.channels = {}
        self.members = {}

    def get_channel(self, cid: int):
        return self.channels.get(cid)

    def get_member(self, mid: int):
        return self.members.get(mid)


class FakeClient:
    def __init__(self, guild):
        self.guild = guild
        self.user = types.SimpleNamespace(id=999)

    def is_ready(self):
        return True

    def get_guild(self, gid: int):
        return self.guild if gid == self.guild.id else None

    def get_channel(self, cid: int):
        return self.guild.get_channel(cid)

    def get_user(self, uid: int):
        return self.guild.get_member(uid)

    async def fetch_channel(self, cid: int):
        return self.guild.get_channel(cid)

    def is_closed(self):
        return False

    async def close(self):
        pass


def make_bot():
    guild = FakeGuild(100, "Guild")
    one = FakeChannel(200, guild, "One")
    two = FakeChannel(201, guild, "Two")
    guild.channels[one.id] = one
    guild.channels[two.id] = two
    live_member = FakeMember(1, "live", True)
    idle_member = FakeMember(2, "idle", False)
    guild.members[live_member.id] = live_member
    guild.members[idle_member.id] = idle_member
    one.members = [live_member, idle_member]

    bot = MultiGuildSelfBot("fixture-token", auto_delete_response_delay=0.0, auto_watch_all_lives=False)
    class FakeStreamKey:
        @classmethod
        def from_guild(cls, *, guild_id, channel_id, owner_id):
            return ("guild", guild_id, channel_id, owner_id)

    bot.discord = types.SimpleNamespace(StreamKey=FakeStreamKey)
    bot.VoiceClient = object
    bot.StreamClient = object
    bot.client = FakeClient(guild)
    return bot, guild, one, two


async def exercise_join_move_leave():
    bot, guild, one, two = make_bot()

    first = await bot.join_room("100", "200")
    assert first["connected"] is True
    assert first["channelId"] == "200"
    assert first["streamerCount"] == 1
    assert one.connect_calls[0]["self_deaf"] is True
    voice = bot.voices[100]

    moved = await bot.join_room("100", "201")
    assert moved["connected"] is True
    assert moved["channelId"] == "201"
    assert voice.moves == [201]

    state = await bot.leave_room("100")
    assert state["roomCount"] == 0
    assert voice.disconnects == 1


def test_join_move_leave():
    asyncio.run(exercise_join_move_leave())


async def exercise_live_watch_auto_and_leave():
    bot, guild, one, _ = make_bot()
    await bot.join_room("100", "200")
    voice = bot.voices[100]
    stream = FakeStream(owner_id=1, channel_id=200)
    voice.streams = [stream]

    state = await bot.join_live("100", timeout=0.5)
    assert state["guildId"] == "100"
    assert state["watching"] is True
    assert state["streamerId"] == "1"
    assert stream.watch_calls
    assert stream.watch_calls[0]["cls"] is object
    assert stream.watch_calls[0]["reconnect"] is True
    assert bot.state()["liveViewCount"] == 1
    assert bot.state()["goLiveWatch"] is True

    client = stream.client
    stopped = await bot.leave_live("100")
    assert stopped["guildId"] == "100"
    assert stopped["watching"] is False
    assert stopped["streamerIds"] == []
    assert stream.deletes == 1
    assert client.disconnects == 1
    assert client.cleanups == 1


def test_live_watch_auto_and_leave():
    asyncio.run(exercise_live_watch_auto_and_leave())


async def exercise_live_watch_specific_and_auto_join():
    bot, guild, one, _ = make_bot()
    stream = FakeStream(owner_id=1, channel_id=200)

    # Seed the voice created by connect() with a stream immediately after join.
    original_connect = one.connect

    async def connect_with_stream(**kwargs):
        voice = await original_connect(**kwargs)
        voice.streams = [stream]
        return voice

    one.connect = connect_with_stream
    state = await bot.join_live("100", channel_id="200", streamer_id="1", timeout=0.5)
    assert state["watching"] is True
    assert state["streamerId"] == "1"
    assert bot.rooms[100].channel_id == 200



async def exercise_live_watch_uncached_stream_key_fallback():
    bot, guild, one, _ = make_bot()
    await bot.join_room("100", "200")
    voice = bot.voices[100]
    assert voice.streams == []

    state = await bot.join_live("100", timeout=0.5)
    assert state["guildId"] == "100"
    assert state["watching"] is True
    assert state["streamerId"] == "1"
    assert len(voice.watch_stream_calls) == 1
    call = voice.watch_stream_calls[0]
    assert call["stream_key"] == ("guild", 100, 200, 1)
    assert call["cls"] is object
    assert call["reconnect"] is True
    assert "via stream-key" in bot.last_action


def test_live_watch_uncached_stream_key_fallback():
    asyncio.run(exercise_live_watch_uncached_stream_key_fallback())

def test_live_watch_specific_and_auto_join():
    asyncio.run(exercise_live_watch_specific_and_auto_join())


async def exercise_move_stops_live_view():
    bot, guild, one, two = make_bot()
    await bot.join_room("100", "200")
    voice = bot.voices[100]
    stream = FakeStream(owner_id=1, channel_id=200)
    voice.streams = [stream]
    await bot.join_live("100", timeout=0.5)
    client = stream.client

    await bot.join_room("100", "201")
    assert client.disconnects == 1
    assert bot.live_state(100)["watching"] is False


def test_move_stops_live_view():
    asyncio.run(exercise_move_stops_live_view())


async def exercise_join_auto_watches_all_active_lives():
    bot, guild, one, _ = make_bot()
    second = FakeMember(3, "live-two", True)
    guild.members[second.id] = second
    one.members.append(second)
    bot.auto_watch_all_lives = True
    bot.auto_watch_timeout = 0.5

    room = await bot.join_room("100", "200")
    assert room["connected"] is True
    assert room["autoLive"]["detectedCount"] == 2
    assert room["autoLive"]["watchingCount"] == 2
    assert room["autoLive"]["streamerIds"] == ["1", "3"]
    assert bot.live_state(100)["viewCount"] == 2
    assert bot.live_state(100)["streamerIds"] == ["1", "3"]
    assert len(bot.voices[100].watch_stream_calls) == 2

    # Both StreamClients remain active simultaneously.
    states = bot.live_states()
    assert {(x["guildId"], x["streamerId"]) for x in states} == {("100", "1"), ("100", "3")}

    await bot.leave_live("100")
    assert bot.live_state(100)["viewCount"] == 0


def test_join_auto_watches_all_active_lives():
    asyncio.run(exercise_join_auto_watches_all_active_lives())


def test_installer_contract():
    requirements = (ROOT / "_support" / "requirements.txt").read_text(encoding="utf-8")
    requirement_lines = [line.strip() for line in requirements.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    installer = (ROOT / "install-windows.bat").read_text(encoding="utf-8")
    start = (ROOT / "start-windows.bat").read_text(encoding="utf-8")

    assert "python-dotenv" in requirements
    assert not any(line.startswith("discord-native-voice") for line in requirement_lines)
    assert not any(line.startswith("discord.py-self") for line in requirement_lines)
    assert "discord.py-self/archive/refs/heads/master.zip" in installer
    assert "--only-binary=:all: --no-deps" in installer
    assert 'discord-native-voice==0.1.1' in installer
    assert "from dotenv import load_dotenv" in installer
    assert "StreamClient, VoiceClient" in installer
    assert "StreamClient, VoiceClient" in start
    assert "Runtime dependencies are incomplete" in start


def test_fastapi_health_status_and_routes_without_token(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "")
    import importlib
    if "app" in sys.modules:
        del sys.modules["app"]
    app_module = importlib.import_module("app")

    health = asyncio.run(app_module.health())
    status = asyncio.run(app_module.status())
    paths = {route.path for route in app_module.app.routes}
    assert health["ok"] is True
    assert health["service"] == "discord-voice-selfbot-v1.2.3"
    assert health["selfBot"] is True
    assert health["goLiveWatch"] is True
    assert health["chatCommands"] is True
    assert health["commandPrefix"] == "k"
    assert health["autoDeleteCommandMessages"] is True
    assert health["autoDeleteCommandResponses"] is True
    assert health["autoDeleteResponseDelay"] == 0.0
    assert health["autoWatchAllLives"] is True
    assert health["autoWatchTimeout"] == 5.0
    assert status["ok"] is True
    assert status["state"]["loggedIn"] is False
    assert "/api/live/join" in paths
    assert "/api/live" in paths
    assert "/api/live/{guild_id}/join-all" in paths
    assert "/api/live/{guild_id}" in paths
    assert "/api/live/{guild_id}/leave" in paths


class FakeSentMessage:
    def __init__(self, text):
        self.text = text
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeTextChannel:
    def __init__(self):
        self.sent = []
        self.sent_messages = []

    async def send(self, text):
        self.sent.append(text)
        msg = FakeSentMessage(text)
        self.sent_messages.append(msg)
        return msg


class FakeCommandAuthor:
    def __init__(self, uid: int, voice_channel=None):
        self.id = uid
        self.voice = types.SimpleNamespace(channel=voice_channel) if voice_channel else None


class FakeMessage:
    def __init__(self, content: str, author, guild=None, *, delete_error=None):
        self.content = content
        self.author = author
        self.guild = guild
        self.channel = FakeTextChannel()
        self.deleted = False
        self.delete_error = delete_error

    async def delete(self):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


async def exercise_chat_whitelist_and_join():
    bot, guild, one, _ = make_bot()
    bot.command_prefix = "k"
    bot.command_owner_ids = {42}

    denied = FakeMessage("kjoin 100 200", FakeCommandAuthor(7), guild)
    handled = await bot.handle_chat_message(denied)
    assert handled is False
    assert denied.channel.sent == []
    assert bot.state()["roomCount"] == 0

    unknown = FakeMessage("khong phai command", FakeCommandAuthor(42), guild)
    handled = await bot.handle_chat_message(unknown)
    assert handled is False
    assert unknown.channel.sent == []

    allowed = FakeMessage("kjoin 100 200", FakeCommandAuthor(42), guild)
    handled = await bot.handle_chat_message(allowed)
    assert handled is True
    assert bot.state()["roomCount"] == 1
    assert "Đã join 100 -> 200" in allowed.channel.sent[-1]
    assert bot.state()["commandPrefix"] == "k"
    assert bot.state()["commandOwnerCount"] == 1
    assert allowed.deleted is True
    assert allowed.channel.sent_messages[-1].deleted is True
    assert bot.state()["commandDeleteCount"] == 1
    assert bot.state()["responseDeleteCount"] == 1


def test_chat_whitelist_and_join():
    asyncio.run(exercise_chat_whitelist_and_join())


async def exercise_chat_joinme_live_and_leave():
    bot, guild, one, _ = make_bot()
    bot.command_prefix = "k"
    bot.command_owner_ids = {42}
    owner = FakeCommandAuthor(42, voice_channel=one)

    joinme = FakeMessage("kjoinme", owner, guild)
    assert await bot.handle_chat_message(joinme) is True
    assert bot.rooms[100].channel_id == 200

    stream = FakeStream(owner_id=1, channel_id=200)
    bot.voices[100].streams = [stream]
    live = FakeMessage("klivehere", owner, guild)
    assert await bot.handle_chat_message(live) is True
    assert bot.live_state(100)["watching"] is True

    rooms = FakeMessage("krooms", owner, guild)
    assert await bot.handle_chat_message(rooms) is True
    assert "100 -> 200" in rooms.channel.sent[-1]

    leave = FakeMessage("kleavehere", owner, guild)
    assert await bot.handle_chat_message(leave) is True
    assert bot.state()["roomCount"] == 0


def test_chat_joinme_live_and_leave():
    asyncio.run(exercise_chat_joinme_live_and_leave())


def test_env_chat_command_contract():
    env = (ROOT / "_support" / ".env.example").read_text(encoding="utf-8")
    readme = (ROOT / "_support" / "README.md").read_text(encoding="utf-8")
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    config_source = (ROOT / "config.py").read_text(encoding="utf-8")
    assert "COMMAND_PREFIX=k" in env
    assert "COMMAND_OWNER_IDS=" in env
    assert "AUTO_DELETE_COMMAND_MESSAGES=true" in env
    assert "AUTO_DELETE_COMMAND_DELAY=0.0" in env
    assert "AUTO_DELETE_COMMAND_RESPONSES=true" in env
    assert "AUTO_DELETE_RESPONSE_DELAY=0.0" in env
    assert "AUTO_WATCH_ALL_LIVES=true" in env
    assert "AUTO_WATCH_TIMEOUT=5.0" in env
    assert "COMMAND_OWNER_IDS" in config_source
    assert "Settings.from_env()" in app_source
    assert "kjoin <guild_id> <voice_channel_id>" in readme
    assert "kjoin <guild_id> <voice_channel_id>" in readme
    assert "AUTO_WATCH_ALL_LIVES=true" in readme


def test_load_dependencies_registers_chat_message_event(monkeypatch):
    fake_discord = types.ModuleType("discord")

    class FakeDiscordClient:
        def __init__(self):
            self.events = {}

        def event(self, func):
            self.events[func.__name__] = func
            return func

    fake_discord.Client = FakeDiscordClient
    fake_ext = types.ModuleType("discord.ext")
    fake_native = types.ModuleType("discord.ext.native_voice")
    fake_native.StreamClient = object
    fake_native.VoiceClient = object

    monkeypatch.setitem(sys.modules, "discord", fake_discord)
    monkeypatch.setitem(sys.modules, "discord.ext", fake_ext)
    monkeypatch.setitem(sys.modules, "discord.ext.native_voice", fake_native)

    bot = MultiGuildSelfBot("fixture", command_prefix="k", command_owner_ids={42})
    bot._load_dependencies()
    assert "on_message" in bot.client.events


async def exercise_command_autodelete_toggle_and_failure():
    bot, guild, _, _ = make_bot()
    bot.command_prefix = "k"
    bot.command_owner_ids = {42}
    bot.auto_delete_command_messages = True
    owner = FakeCommandAuthor(42)

    status = FakeMessage("kautodelete status", owner, guild)
    assert await bot.handle_chat_message(status) is True
    assert status.deleted is True
    assert "ON" in status.channel.sent[-1]

    off = FakeMessage("kautodelete off", owner, guild)
    assert await bot.handle_chat_message(off) is True
    assert off.deleted is True
    assert bot.auto_delete_command_messages is False

    while_off = FakeMessage("kstatus", owner, guild)
    assert await bot.handle_chat_message(while_off) is True
    assert while_off.deleted is False

    on = FakeMessage("kautodelete on", owner, guild)
    assert await bot.handle_chat_message(on) is True
    assert on.deleted is False
    assert bot.auto_delete_command_messages is True

    failed = FakeMessage("kstatus", owner, guild, delete_error=PermissionError("forbidden"))
    assert await bot.handle_chat_message(failed) is True
    assert failed.deleted is False
    assert bot.command_delete_failures == 1
    assert failed.channel.sent


def test_command_autodelete_toggle_and_failure():
    asyncio.run(exercise_command_autodelete_toggle_and_failure())


async def exercise_response_autodelete_toggle():
    bot, guild, _, _ = make_bot()
    bot.command_prefix = "k"
    bot.command_owner_ids = {42}
    bot.auto_delete_command_messages = False
    bot.auto_delete_command_responses = True
    bot.auto_delete_response_delay = 0.0
    owner = FakeCommandAuthor(42)

    status = FakeMessage("kstatus", owner, guild)
    assert await bot.handle_chat_message(status) is True
    assert status.deleted is False
    assert status.channel.sent_messages[-1].deleted is True
    assert bot.response_delete_count == 1

    off = FakeMessage("kreplydelete off", owner, guild)
    assert await bot.handle_chat_message(off) is True
    assert off.channel.sent_messages[-1].deleted is True
    assert bot.auto_delete_command_responses is False

    while_off = FakeMessage("kstatus", owner, guild)
    assert await bot.handle_chat_message(while_off) is True
    assert while_off.channel.sent_messages[-1].deleted is False

    on = FakeMessage("kreplydelete on", owner, guild)
    assert await bot.handle_chat_message(on) is True
    assert on.channel.sent_messages[-1].deleted is False
    assert bot.auto_delete_command_responses is True

    after_on = FakeMessage("kstatus", owner, guild)
    assert await bot.handle_chat_message(after_on) is True
    assert after_on.channel.sent_messages[-1].deleted is True


def test_response_autodelete_toggle():
    asyncio.run(exercise_response_autodelete_toggle())


async def exercise_stream_toggle_by_mention():
    bot, guild, one, _ = make_bot()
    bot.command_owner_ids = {77}
    bot.auto_delete_command_messages = True
    bot.auto_delete_command_responses = True
    await bot.join_room("100", "200")
    voice = bot.voices[100]
    stream = FakeStream(owner_id=1, channel_id=200)
    voice.streams = [stream]
    await bot.join_live("100", streamer_id="1", timeout=0.5)
    assert bot.live_state(100)["watching"] is True

    author = types.SimpleNamespace(id=77, voice=None)
    msg = FakeMessage("kstream <@1> off", author, guild)
    assert await bot.handle_chat_message(msg) is True
    assert msg.deleted is True
    assert 1 in bot.live_watch_disabled[100]
    assert bot.live_state(100)["watching"] is False

    # Auto-watch-all must respect the disabled user.
    result = await bot.join_all_lives("100", timeout=0.5)
    assert result["watchingCount"] == 0

    msg2 = FakeMessage("kstream <@!1> on", author, guild)
    assert await bot.handle_chat_message(msg2) is True
    assert 1 not in bot.live_watch_disabled.get(100, set())
    assert bot.live_state(100)["watching"] is True


def test_stream_toggle_by_mention():
    asyncio.run(exercise_stream_toggle_by_mention())


async def exercise_command_error_writes_to_file():
    bot, guild, one, _ = make_bot()
    bot.command_owner_ids = {77}
    bot.auto_delete_command_messages = True
    bot.auto_delete_command_responses = True
    author = types.SimpleNamespace(id=77, voice=None)
    msg = FakeMessage("kjoin bad 200", author, guild)
    assert await bot.handle_chat_message(msg) is True
    assert msg.deleted is True
    text = bot.activity_log.path.read_text(encoding="utf-8")
    assert "[CMD]kjoin" in text
    assert "[ERROR]Command failed" in text
    assert "[WHY]Command failure reason" in text
    assert "guildId phải là Discord ID dạng số" in text


def test_command_error_writes_to_file():
    asyncio.run(exercise_command_error_writes_to_file())


async def exercise_stream_off_stops_gateway_and_blocks_rewatch():
    bot, guild, one, _ = make_bot()
    await bot.join_room("100", "200")
    voice = bot.voices[100]
    stream = FakeStream(owner_id=1, channel_id=200)
    voice.streams = [stream]

    state = await bot.join_live("100", streamer_id="1", timeout=0.5)
    assert state["watching"] is True
    client = stream.client

    off = await bot.set_stream_watch("100", "1", "off")
    assert off["enabled"] is False
    assert off["watching"] is False
    assert 1 in bot.live_watch_disabled[100]
    assert stream.deletes == 1
    assert client.disconnects == 1
    assert client.cleanups == 1
    assert 1 not in bot.live_views.get(100, {})

    # Auto-watch scan must ignore the disabled streamer.
    auto = await bot.join_all_lives("100", timeout=0.5)
    assert auto["detectedCount"] == 0
    assert auto["watchingCount"] == 0
    assert stream.watch_calls and len(stream.watch_calls) == 1


def test_stream_off_stops_gateway_and_blocks_rewatch():
    asyncio.run(exercise_stream_off_stops_gateway_and_blocks_rewatch())



def test_activity_log_writes_and_redacts(tmp_path):
    from core import ActivityLog

    path = tmp_path / "bot.log"
    log = ActivityLog(str(path), to_terminal=False, max_bytes=64000, backup_count=1)
    log.write("CMD", "kjoin", guild=100, channel=200, token="should-not-appear")
    log.write("ERROR", "Join voice failed", reason="fixture failure")
    log.close()

    text = path.read_text(encoding="utf-8")
    assert "[CMD]kjoin" in text
    assert "guild=100" in text
    assert "channel=200" in text
    assert "should-not-appear" not in text
    assert "token=<redacted>" in text
    assert "[ERROR]Join voice failed" in text
    assert "reason=fixture failure" in text
