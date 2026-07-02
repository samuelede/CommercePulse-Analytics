-- Analytics schema and output tables for CommercePulse.
-- Run automatically by the loader, provided here for manual setup.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.customer_segmentation (
    customer_id   TEXT PRIMARY KEY,
    customer_name TEXT,
    total_orders  INTEGER,
    total_spend   NUMERIC(12, 2),
    segment       TEXT
);

CREATE TABLE IF NOT EXISTS analytics.customer_360 (
    customer_id        TEXT PRIMARY KEY,
    lifetime_value     NUMERIC(12, 2),
    purchase_frequency INTEGER,
    last_purchase_date TIMESTAMP,
    preferred_category TEXT,
    churn_risk         TEXT
);

CREATE TABLE IF NOT EXISTS analytics.campaign_recommendations (
    customer_id          TEXT,
    segment              TEXT,
    holiday_name         TEXT,
    days_until_holiday   INTEGER,
    recommended_campaign TEXT
);
