from fastapi import APIRouter, HTTPException

from src.prompts import load_prompts
from src.realtime.config import MODELS, VOICES

router = APIRouter()


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
