from pydantic import BaseModel, Field


class RoomRequest(BaseModel):
    guildId: str = Field(min_length=1)
    channelId: str = Field(min_length=1)


class MultiRoomRequest(BaseModel):
    rooms: list[RoomRequest] = Field(default_factory=list)
    replace: bool = False


class LiveJoinRequest(BaseModel):
    guildId: str = Field(min_length=1)
    channelId: str | None = None
    streamerId: str | None = None
    timeout: float = Field(default=10.0, ge=0.5, le=30.0)
