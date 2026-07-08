"""Airflow DAG orchestrating the CommercePulse pipeline."""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from python.enrich.campaigns import build_campaigns
from python.enrich.holiday_api import get_next_holiday
from python.extract.extract_staging import extract_all
from python.load.load_analytics import (
    load_campaigns,
    load_customer_360,
    load_segmentation,
)
from python.load.monday_crm import sync_campaigns
from python.transform.customer_360 import build_customer_360
from python.transform.segmentation import build_segmentation
from python.transform.validation import (
    validate_campaigns,
    validate_customer_360,
    validate_segmentation,
)

default_args = {
    "owner": "data-engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _extract(**ctx):
    data = extract_all()
    # Push as records via XCom-friendly serialization
    for k, v in data.items():
        ctx["ti"].xcom_push(key=k, value=v.to_json(orient="split"))


def _segment(**ctx):
    import pandas as pd

    customers = pd.read_json(ctx["ti"].xcom_pull(key="customers"), orient="split")
    orders = pd.read_json(ctx["ti"].xcom_pull(key="orders"), orient="split")
    seg = build_segmentation(customers, orders)
    validate_segmentation(seg)
    load_segmentation(seg)
    ctx["ti"].xcom_push(key="segmentation", value=seg.to_json(orient="split"))


def _customer_360(**ctx):
    import pandas as pd

    customers = pd.read_json(ctx["ti"].xcom_pull(key="customers"), orient="split")
    products = pd.read_json(ctx["ti"].xcom_pull(key="products"), orient="split")
    orders = pd.read_json(ctx["ti"].xcom_pull(key="orders"), orient="split")
    c360 = build_customer_360(customers, products, orders)
    validate_customer_360(c360)
    load_customer_360(c360)
    ctx["ti"].xcom_push(key="customer_360", value=c360.to_json(orient="split"))


def _campaigns(**ctx):
    import pandas as pd

    seg = pd.read_json(ctx["ti"].xcom_pull(key="segmentation"), orient="split")
    holiday = get_next_holiday()
    camp = build_campaigns(seg, holiday)
    validate_campaigns(camp)
    load_campaigns(camp)
    ctx["ti"].xcom_push(key="campaigns", value=camp.to_json(orient="split"))


def _reverse_etl(**ctx):
    import pandas as pd

    camp = pd.read_json(ctx["ti"].xcom_pull(key="campaigns"), orient="split")
    c360 = pd.read_json(ctx["ti"].xcom_pull(key="customer_360"), orient="split")
    sync_campaigns(camp, c360)


with DAG(
    dag_id="commercepulse_pipeline",
    description="Customer intelligence + reverse ETL to Monday CRM",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["commercepulse", "reverse-etl", "mandera"],
) as dag:

    extract = PythonOperator(task_id="extract_staging", python_callable=_extract)
    segment = PythonOperator(task_id="build_segmentation", python_callable=_segment)
    c360 = PythonOperator(
        task_id="build_customer_360", python_callable=_customer_360
    )
    campaigns = PythonOperator(
        task_id="build_campaigns", python_callable=_campaigns
    )
    reverse_etl = PythonOperator(
        task_id="reverse_etl_monday", python_callable=_reverse_etl
    )

    extract >> [segment, c360]
    segment >> campaigns
    [campaigns, c360] >> reverse_etl
