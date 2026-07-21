import logging


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """Get or create a logger"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
