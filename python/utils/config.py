"""Centralized configuration loaded from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Source PostgreSQL (Mandera staging).
    # Defaults target the host-published port. docker-compose overrides these
    # with the internal service address (data-db:5432) for containerized runs.
    PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
    PG_PORT = os.getenv("PG_PORT", "5434")
    PG_DB = os.getenv("PG_DB", "mandera")
    PG_USER = os.getenv("PG_USER", "postgres")
    PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
    PG_STAGING_SCHEMA = os.getenv("PG_STAGING_SCHEMA", "staging")
    PG_ANALYTICS_SCHEMA = os.getenv("PG_ANALYTICS_SCHEMA", "analytics")

    # Holiday API
    HOLIDAY_API_KEY = os.getenv("HOLIDAY_API_KEY", "")
    HOLIDAY_API_BASE = os.getenv(
        "HOLIDAY_API_BASE", "https://calendarific.com/api/v2"
    )
    HOLIDAY_COUNTRY = os.getenv("HOLIDAY_COUNTRY", "GB")
    HOLIDAY_YEAR = os.getenv("HOLIDAY_YEAR", "2026")

    # Minimum lead time before a holiday for it to be worth planning a campaign
    # around. A holiday two days out is accurate but useless: there is no time
    # to brief, build, and ship. 14 days is a realistic floor.
    HOLIDAY_MIN_LEAD_DAYS = int(os.getenv("HOLIDAY_MIN_LEAD_DAYS", "14"))

    # Exclude subdivision-specific holidays (e.g. Battle of the Boyne, which is
    # Northern Ireland only). Anchoring a nationwide campaign to a regional
    # holiday is a business error, not just an odd-looking one.
    HOLIDAY_NATIONWIDE_ONLY = (
        os.getenv("HOLIDAY_NATIONWIDE_ONLY", "true").lower() == "true"
    )

    # Monday CRM
    MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN", "")
    MONDAY_API_URL = os.getenv("MONDAY_API_URL", "https://api.monday.com/v2")
    MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID", "")

    # Segmentation thresholds
    VIP_SPEND_THRESHOLD = float(os.getenv("VIP_SPEND_THRESHOLD", "5000"))
    VIP_ORDER_THRESHOLD = int(os.getenv("VIP_ORDER_THRESHOLD", "10"))
    RETURNING_ORDER_THRESHOLD = int(os.getenv("RETURNING_ORDER_THRESHOLD", "2"))
    CHURN_DAYS_THRESHOLD = int(os.getenv("CHURN_DAYS_THRESHOLD", "90"))

    @classmethod
    def pg_uri(cls):
        return (
            f"postgresql+psycopg2://{cls.PG_USER}:{cls.PG_PASSWORD}"
            f"@{cls.PG_HOST}:{cls.PG_PORT}/{cls.PG_DB}"
        )


config = Config()