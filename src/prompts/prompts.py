import yaml


def load_prompts(path: str = 'prompts.yaml') -> dict[str, dict[str, str]]:
    """Load named assistant prompts from a YAML file

    Args:
        path (str): Path to the YAML file containing prompts
    Returns:
        dict[str, dict[str, str]]: Mapping of prompt key to
            a dict with 'label' and 'instructions'
    """
    with open(path, encoding = 'utf-8') as f:
        return yaml.safe_load(f)
