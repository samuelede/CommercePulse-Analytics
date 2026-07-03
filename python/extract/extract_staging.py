"""Extract customer, product, and order data from PostgreSQL staging."""
import pandas as pd

from python.utils.config import config
from python.utils.db import get_engine, get_logger

logger = get_logger(__name__)


def _read_table(table):
    engine = get_engine()
    schema = config.PG_STAGING_SCHEMA
    query = f"SELECT * FROM {schema}.{table};"
    logger.info("Extracting %s.%s", schema, table)
    df = pd.read_sql(query, engine)
    logger.info("Extracted %d rows from %s", len(df), table)
    return df


def extract_customers():
    df = _read_table("customers")
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def extract_products():
    df = _read_table("products")
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def extract_orders():
    df = _read_table("orders")
    df.columns = [c.strip().lower() for c in df.columns]
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df


def extract_all():
    return {
        "customers": extract_customers(),
        "products": extract_products(),
        "orders": extract_orders(),
    }


if __name__ == "__main__":
    data = extract_all()
    for name, frame in data.items():
        logger.info("%s: %d rows, columns=%s", name, len(frame), list(frame.columns))
