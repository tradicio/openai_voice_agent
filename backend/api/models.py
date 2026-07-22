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
    """Client -> Server: update the active prompt, model, and/or voice."""

    type: Literal["config"]
    prompt_key: str | None = None
    model: str | None = None
    voice: str | None = None


IncomingMessage = Annotated[
    ControlMessage | AudioMessage | ConfigMessage,
    Field(discriminator="type"),
]
