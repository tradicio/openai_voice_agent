from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ControlMessage(BaseModel):
    """Client -> Server: start or stop the conversation."""

    type: Literal["control"]
    action: Literal["start", "stop"]


class AudioMessage(BaseModel):
    """Client -> Server: a base64-encoded PCM audio frame."""

    type: Literal["audio"]
    data: str


class ConfigMessage(BaseModel):
    """Client -> Server: update the session timeout and/or active prompt."""

    type: Literal["config"]
    timeout: int | None = None
    prompt_key: str | None = None


IncomingMessage = Annotated[
    ControlMessage | AudioMessage | ConfigMessage,
    Field(discriminator="type"),
]


class StatusMessage(BaseModel):
    """Server -> Client: a status or error notification."""

    type: Literal["status"] = "status"
    message: str


class TranscriptDeltaMessage(BaseModel):
    """Server -> Client: an incremental transcript update."""

    type: Literal["transcript"] = "transcript"
    role: Literal["user", "assistant"]
    delta: str
    index: int


class AudioResponseMessage(BaseModel):
    """Server -> Client: a base64-encoded PCM audio frame."""

    type: Literal["audio"] = "audio"
    data: str


class ClearAudioMessage(BaseModel):
    """Server -> Client: flush any audio queued for playback (barge-in)."""

    type: Literal["clear_audio"] = "clear_audio"
