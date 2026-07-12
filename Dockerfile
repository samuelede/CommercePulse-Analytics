# Custom Airflow image for CommercePulse.
#
# Installed WITHOUT Airflow's constraint file. The constraints pin
# SQLAlchemy 1.4, but pandas 2.2.x requires SQLAlchemy 2.x (it checks for the
# `Connectable` type, removed in 2.0). Under 1.4 pandas falls back to its raw
# DBAPI path and every read_sql/to_sql fails with:
#     AttributeError: 'Engine' object has no attribute 'cursor'
# Airflow 2.9.3 itself runs correctly on SQLAlchemy 2.x.
FROM apache/airflow:2.9.3-python3.11

COPY requirements-airflow.txt /requirements-airflow.txt

USER airflow
RUN pip install --no-cache-dir -r /requirements-airflow.txt

# Fail the build rather than the DAG if the versions are not what we expect.
RUN python -c "\
import sqlalchemy, pandas; \
major = int(sqlalchemy.__version__.split('.')[0]); \
assert major >= 2, f'SQLAlchemy {sqlalchemy.__version__} < 2.x breaks pandas read_sql'; \
print(f'OK: SQLAlchemy {sqlalchemy.__version__} | pandas {pandas.__version__}')"