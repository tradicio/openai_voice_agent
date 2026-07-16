def hash_by_code(obj) -> int:
    """Hash function to detect code changes
    """
    import inspect
    return hash(inspect.getsource(obj))
