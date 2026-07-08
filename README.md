# CommercePulse Analytics

Customer intelligence and Reverse ETL platform for the Mandera Analytics commerce ecosystem. CommercePulse extracts customer, product, and order data from PostgreSQL staging, builds customer segmentation and a Customer 360 view, enriches recommendations with public holiday data, and pushes the results into Monday CRM so marketing, sales, and customer success teams can act on them directly.

## Architecture

```
PostgreSQL staging (Mandera)
        │  extract
        ▼
   Pandas transforms ──► customer_segmentation ─┐
        │                customer_360           │
        │  enrich (Holiday API)                 │
        ▼                                       │
   campaign_recommendations ────────────────────┤
        │                                       │
        │  load                                 │
        ▼                                       ▼
   PostgreSQL analytics schema        Monday CRM (Reverse ETL)
```

Orchestrated by Apache Airflow, containerized with Docker.

## Output datasets (analytics schema)

| Table | Key columns |
|-------|-------------|
| `customer_segmentation` | customer_id, customer_name, total_orders, total_spend, segment |
| `customer_360` | customer_id, lifetime_value, purchase_frequency, last_purchase_date, preferred_category, churn_risk |
| `campaign_recommendations` | customer_id, segment, holiday_name, days_until_holiday, recommended_campaign |

Segments: New Customer, Returning Customer, VIP Customer, At-Risk Customer.

## Repository layout

```
commercepulse/
├── dags/
│   └── commercepulse_dag.py        # Airflow DAG
├── python/
│   ├── pipeline.py                 # Standalone end-to-end entrypoint
│   ├── extract/extract_staging.py  # Pull staging tables
│   ├── transform/
│   │   ├── segmentation.py
│   │   ├── customer_360.py
│   │   └── validation.py
│   ├── enrich/
│   │   ├── holiday_api.py          # Holiday API connector
│   │   └── campaigns.py            # Recommendation engine
│   ├── load/
│   │   ├── load_analytics.py       # Write to analytics schema
│   │   └── monday_crm.py           # Reverse ETL to Monday CRM
│   └── utils/
│       ├── config.py
│       └── db.py
├── sql/
│   ├── 01_create_analytics_schema.sql
│   └── 02_seed_sample_data.sql     # Optional local test data
├── tests/test_pipeline.py
├── requirements.txt
├── requirements-airflow.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Docker and Docker Compose
- Python 3.11+ (only if running the pipeline outside Docker)
- A Monday.com account with an API token and a target board
- Optional: a Calendarific API key (the pipeline falls back to the keyless Nager.Date API if none is supplied)

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/samuelede/CommercePulse-Analytics.git
cd CommercePulse-Analytics
cp .env.example .env
```

Edit `.env` and set at minimum `MONDAY_API_TOKEN` and `MONDAY_BOARD_ID`. Adjust PostgreSQL values to point at your Mandera staging instance, or keep defaults to use the bundled `data-db` service.

### 2. Configure the Monday CRM board

Create a board in Monday with these columns and note each column ID (Monday assigns IDs you can read from the column settings or the API). Map them in `python/load/monday_crm.py` if your IDs differ from the defaults:

| Column purpose | Default ID used | Type |
|----------------|-----------------|------|
| Segment | text_segment | Text |
| Recommended campaign | text_campaign | Text |
| Holiday | text_holiday | Text |
| Days until holiday | numbers_days | Numbers |
| Churn risk | text_churn | Text |
| Lifetime value | numbers_ltv | Numbers |

Put the board ID in `.env` as `MONDAY_BOARD_ID`.

## Run with Docker (recommended)

```bash
# Build the custom Airflow image
docker compose build

# Initialize Airflow metadata DB and admin user
docker compose up airflow-init

# Start the stack
docker compose up -d
```

The bundled `data-db` service auto-loads `sql/01_create_analytics_schema.sql` and `sql/02_seed_sample_data.sql` on first start, giving you a working staging dataset for testing. If you point at a real Mandera staging DB instead, remove `02_seed_sample_data.sql` or skip the seed.

Open the Airflow UI at http://localhost:8080 (login `airflow` / `airflow`), unpause `commercepulse_pipeline`, and trigger it.

Stop the stack:

```bash
docker compose down          # keep data
docker compose down -v        # remove volumes
```

## Run standalone (without Airflow)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # set PG_* to a reachable Postgres
```

Create the analytics schema (only needed if not using Docker seed):

```bash
psql "$DATABASE_URL" -f sql/01_create_analytics_schema.sql
```

Run the full pipeline:

```bash
PYTHONPATH=. python -m python.pipeline
```

Run analytics only, skipping the CRM push:

```bash
PYTHONPATH=. python -m python.pipeline --skip-crm
```

Run individual stages for debugging:

```bash
PYTHONPATH=. python -m python.extract.extract_staging
PYTHONPATH=. python -m python.enrich.holiday_api
```

## Tests

```bash
PYTHONPATH=. pytest tests/ -q
```

## Verifying outputs

After a run, inspect the analytics tables:

```bash
docker compose exec data-db psql -U postgres -d mandera \
  -c "SELECT segment, count(*) FROM analytics.customer_segmentation GROUP BY 1;"
```

Then confirm items appear on your Monday board.

## Configuration reference

All settings come from environment variables (see `.env.example`). Key tunables:

- `VIP_SPEND_THRESHOLD`, `VIP_ORDER_THRESHOLD` — VIP cutoffs
- `RETURNING_ORDER_THRESHOLD` — minimum orders for Returning segment
- `CHURN_DAYS_THRESHOLD` — days of inactivity before At-Risk / High churn
- `HOLIDAY_COUNTRY`, `HOLIDAY_YEAR` — holiday lookup scope

## Notes

- PostgreSQL is mapped to host port 5434 to avoid clashing with the Mandera stack (5433).
- pandas and pyarrow are pinned (2.2.2 / 16.1.0); other Airflow dependencies stay unpinned so pip resolves against Airflow's own SQLAlchemy constraint.
- The Holiday connector uses Calendarific when a key is set and falls back to the keyless Nager.Date API otherwise.
