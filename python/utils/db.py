"""Database engine factory and shared logger."""
import logging
import sys

from sqlalchemy import create_engine

from python.utils.config import config


def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def get_engine():
    """Return a SQLAlchemy engine for the staging PostgreSQL instance."""
    return create_engine(config.pg_uri(), pool_pre_ping=True)
