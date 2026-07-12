"""Database engine factory and shared logger."""
import logging
import sys

import sqlalchemy
from sqlalchemy import create_engine

from python.utils.config import config

# pandas 2.2.x checks for the SQLAlchemy `Connectable` type, which was removed
# in SQLAlchemy 2.0. Under SQLAlchemy 1.4 that check fails, pandas silently
# falls back to its raw DBAPI code path, and every read_sql/to_sql dies with a
# misleading "'Engine' object has no attribute 'cursor'". Fail clearly instead.
_SA_MAJOR = int(sqlalchemy.__version__.split(".")[0])
if _SA_MAJOR < 2:
    raise RuntimeError(
        f"SQLAlchemy {sqlalchemy.__version__} is installed, but pandas 2.2.x "
        "requires SQLAlchemy 2.x. Airflow's constraint file pins 1.4; this "
        "image must install SQLAlchemy>=2.0 (see requirements-airflow.txt). "
        "Rebuild with: docker compose build --no-cache"
    )


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