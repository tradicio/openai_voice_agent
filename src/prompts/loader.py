import logging
import os
from functools import lru_cache

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), 'prompts.yaml')


@lru_cache(maxsize=1)
def load_prompts(
    path: str = _DEFAULT_PROMPTS_PATH,
) -> dict[str, dict[str, str]]:
    """Load named assistant prompts from a YAML file.

    The result is cached per `path` for the lifetime of the process,
    since prompts.yaml is static configuration rather than user data;
    this avoids a blocking disk read/parse on every call from the
    async WebSocket handlers. A missing or unparseable file yields an
    empty mapping rather than raising, so callers can degrade gracefully.

    Args:
        path (str): Path to the YAML file containing prompts
    Returns:
        dict[str, dict[str, str]]: Mapping of prompt key to a dict with
            'label' and 'instructions', or an empty dict if the file is
            missing or fails to parse.
    """
    if not os.path.exists(path):
        logger.warning(f"Prompts file not found at {path}")
        return {}

    try:
        with open(path, encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        return prompts or {}
    except Exception as e:
        logger.error(f"Failed to load prompts: {e}")
        return {}
