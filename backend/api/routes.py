import logging
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

from src.realtime.config import MODELS, VOICES

logger = logging.getLogger(__name__)


router = APIRouter()


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, dict[str, str]]:
    """Load and cache the available assistant prompts.

    The result is cached for the lifetime of the process since
    ``prompts.yaml`` is static configuration, not user data; this avoids
    a blocking disk read and YAML parse on every request and WebSocket
    config update.

    Returns
    -------
    dict[str, dict[str, str]]
        Mapping of prompt key to its fields (e.g. ``label``,
        ``instructions``), or an empty dict if the file is missing or
        fails to parse.
    """
    prompts_path = (
        Path(__file__).parent.parent.parent
        / "src" / "prompts" / "prompts.yaml"
    )

    if not prompts_path.exists():
        logger.warning(f"Prompts file not found at {prompts_path}")
        return {}

    try:
        with open(prompts_path, encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        return prompts or {}
    except Exception as e:
        logger.error(f"Failed to load prompts: {e}")
        return {}


@router.get("/api/health")
async def health_check() -> dict[str, str]:
    """Report service liveness.

    Returns
    -------
    dict[str, str]
        A static ``{"status": "ok"}`` payload.
    """
    return {"status": "ok"}


@router.get("/api/prompts")
async def get_prompts() -> dict:
    """List the assistant prompts available for selection.

    Returns
    -------
    dict
        ``{"prompts": [{"key": ..., "label": ...}, ...]}``.

    Raises
    ------
    HTTPException
        404 if no prompts are configured.
    """
    prompts = load_prompts()
    if not prompts:
        raise HTTPException(
            status_code=404,
            detail="No prompts found"
        )
    return {
        "prompts": [
            {"key": k, "label": v.get("label", k)}
            for k, v in prompts.items()
        ]
    }


@router.get("/api/models")
async def get_models() -> dict:
    """List the realtime models available for selection.

    Returns
    -------
    dict
        ``{"models": [{"key": ..., "label": ...}, ...]}``.
    """
    return {"models": MODELS}


@router.get("/api/voices")
async def get_voices() -> dict:
    """List the assistant voices available for selection.

    Returns
    -------
    dict
        ``{"voices": [{"key": ..., "label": ...}, ...]}``.
    """
    return {"voices": VOICES}
