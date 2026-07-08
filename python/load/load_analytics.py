"""Persist analytical datasets to the PostgreSQL analytics schema."""
from sqlalchemy import text

from python.utils.config import config
from python.utils.db import get_engine, get_logger

logger = get_logger(__name__)


def _ensure_schema(engine):
    with engine.begin() as conn:
        conn.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {config.PG_ANALYTICS_SCHEMA};")
        )


def write_table(df, table):
    engine = get_engine()
    _ensure_schema(engine)
    df.to_sql(
        table,
        engine,
        schema=config.PG_ANALYTICS_SCHEMA,
        if_exists="replace",
        index=False,
    )
    logger.info(
        "Wrote %d rows to %s.%s",
        len(df),
        config.PG_ANALYTICS_SCHEMA,
        table,
    )


def load_segmentation(df):
    write_table(df, "customer_segmentation")


def load_customer_360(df):
    write_table(df, "customer_360")


def load_campaigns(df):
    write_table(df, "campaign_recommendations")
