from typing import Literal
from pydantic import BaseModel


class AudioMessage(BaseModel):
    """Client→Server audio frame (base64 PCM)"""
    type: Literal["audio"]
    data: str  # base64 encoded audio chunk


class ControlMessage(BaseModel):
    """Client→Server control messages"""
    type: Literal["config"]
    timeout: int | None = None
    prompt_key: str | None = None


class TranscriptDelta(BaseModel):
    """Server→Client transcript update"""
    type: Literal["transcript"]
    role: Literal["user", "assistant"]
    delta: str


class StatusMessage(BaseModel):
    """Server→Client status updates"""
    type: Literal["status"]
    message: str
