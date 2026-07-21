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
