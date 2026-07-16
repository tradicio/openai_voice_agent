import os

import yaml


_DEFAULT_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), 'prompts.yaml')


def load_prompts(path: str = _DEFAULT_PROMPTS_PATH) -> dict[str, dict[str, str]]:
    """Load named assistant prompts from a YAML file

    Args:
        path (str): Path to the YAML file containing prompts
    Returns:
        dict[str, dict[str, str]]: Mapping of prompt key to
            a dict with 'label' and 'instructions'
    """
    with open(path, encoding = 'utf-8') as f:
        return yaml.safe_load(f)
