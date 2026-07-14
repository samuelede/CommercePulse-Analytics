"""Database engine factory and shared logger."""
import logging
import sys

import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine

from python.utils.config import config

# pandas and SQLAlchemy must be a compatible pair, and the window is narrow:
#
#   pandas 2.2.x checks for the SQLAlchemy `Connectable` type, removed in
#   SQLAlchemy 2.0. Under 1.4 it degrades to a raw DBAPI path and every query
#   dies with "'Engine' object has no attribute 'cursor'".
#
#   SQLAlchemy 2.x rejects Airflow 2.9's ORM models outright
#   (MappedAnnotationError on TaskInstance), so the webserver crash-loops.
#
# Airflow therefore fixes SQLAlchemy at 1.4, and pandas must stay below 2.2.
# Fail loudly here rather than let either failure surface as something cryptic.
_SA = tuple(int(p) for p in sqlalchemy.__version__.split(".")[:2])
_PD = tuple(int(p) for p in pd.__version__.split(".")[:2])

if _SA < (2, 0) and _PD >= (2, 2):
    raise RuntimeError(
        f"pandas {pd.__version__} requires SQLAlchemy 2.x, but SQLAlchemy "
        f"{sqlalchemy.__version__} is installed. Every read_sql/to_sql will "
        "fail with \"'Engine' object has no attribute 'cursor'\".\n"
        "Airflow 2.9 requires SQLAlchemy 1.4, so pandas must be < 2.2 "
        "(2.1.4 is pinned). Rebuild: docker compose build --no-cache"
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