import logging
from pathlib import Path
from typing import Dict, List

import yaml
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


def load_prompts() -> Dict[str, Dict[str, str]]:
    """Load prompts from prompts.yaml"""
    prompts_path = Path(__file__).parent.parent.parent / "src" / "prompts" / "prompts.yaml"

    if not prompts_path.exists():
        logger.warning(f"Prompts file not found at {prompts_path}")
        return {}

    try:
        with open(prompts_path, 'r', encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        return prompts or {}
    except Exception as e:
        logger.error(f"Failed to load prompts: {e}")
        return {}


@router.get("/api/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {"status": "ok"}


@router.get("/api/prompts")
async def get_prompts() -> Dict:
    """Get list of available prompts"""
    prompts = load_prompts()
    if not prompts:
        raise HTTPException(
            status_code=404,
            detail="No prompts found"
        )
    return {"prompts": [{"key": k, "label": v["label"]} for k, v in prompts.items()]}


@router.post("/api/session/timeout")
async def update_session_timeout(timeout: int = 300) -> Dict:
    """Update session timeout (60-300 seconds)"""
    if timeout < 60 or timeout > 300:
        raise HTTPException(
            status_code=400,
            detail="Session timeout must be between 60 and 300 seconds"
        )

    logger.info(f"Session timeout updated to {timeout} seconds")
    return {"status": "ok", "timeout": timeout}
