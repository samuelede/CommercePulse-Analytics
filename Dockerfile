# Custom Airflow image for CommercePulse.
# pandas/pyarrow pinned via requirements-airflow.txt; everything else
# resolves against Airflow's own constraints to avoid SQLAlchemy conflicts.
FROM apache/airflow:2.9.3-python3.11

COPY requirements-airflow.txt /requirements-airflow.txt

USER airflow
RUN pip install --no-cache-dir -r /requirements-airflow.txt
