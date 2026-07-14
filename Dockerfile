# Custom Airflow image for CommercePulse.
#
# pandas is held at 2.1.4, the newest release compatible with the SQLAlchemy 1.4
# that Airflow 2.9.3 requires. pandas 2.2.x needs SQLAlchemy 2.x, and SQLAlchemy
# 2.x breaks Airflow's own ORM models. See requirements-airflow.txt.
FROM apache/airflow:2.9.3-python3.11

COPY requirements-airflow.txt /requirements-airflow.txt

USER airflow
RUN pip install --no-cache-dir -r /requirements-airflow.txt

# Fail the build, not the webserver, if the versions drift out of the window
# where Airflow and pandas can coexist.
RUN python -c "\
import sqlalchemy, pandas; \
sa = tuple(int(p) for p in sqlalchemy.__version__.split('.')[:2]); \
pd = tuple(int(p) for p in pandas.__version__.split('.')[:2]); \
assert sa < (2, 0), f'SQLAlchemy {sqlalchemy.__version__} breaks Airflow ORM models'; \
assert pd < (2, 2), f'pandas {pandas.__version__} requires SQLAlchemy 2.x, which Airflow cannot use'; \
print(f'OK: SQLAlchemy {sqlalchemy.__version__} | pandas {pandas.__version__}')"