# CommercePulse Data Dictionary

Every dataset the pipeline reads or writes, with types, definitions, and how each derived field is calculated.

- [Source datasets](#source-datasets) — read from Mandera's PostgreSQL staging schema
- [Analytics datasets](#analytics-datasets) — written to the `analytics` schema
- [Monday CRM board](#monday-crm-board) — the reverse ETL destination
- [Business rules](#business-rules) — the logic behind every derived classification
- [Worked example](#worked-example)

---

## Source datasets

Read-only. Produced by the Mandera batch pipeline (MongoDB Atlas → MinIO → PostgreSQL). CommercePulse never writes here.

### `staging.customers`

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | TEXT | No | Unique customer identifier. Join key across all datasets. |
| `name` | TEXT | No | Customer full name. Becomes the Monday item title. |
| `email` | TEXT | Yes | Contact email. |
| `phone` | TEXT | Yes | Contact number. |
| `city` | TEXT | Yes | Customer city. |
| `batch_id` | TEXT | Yes | Mandera ingestion batch. Not carried into analytics. |
| `created_at` | TIMESTAMP | No | When the *record* was created, not the first purchase. Tenure is derived from orders, not from this. |

### `staging.products`

| Column | Type | Null | Description |
|---|---|---|---|
| `product_id` | TEXT | No | Unique product identifier. |
| `product_name` | TEXT | No | Product name. |
| `category` | TEXT | No | Product category. Source of `preferred_category`. |
| `price` | NUMERIC(10,2) | No | List price. Not used for revenue; `orders.amount` is authoritative. |
| `batch_id` | TEXT | Yes | Mandera ingestion batch. |
| `created_at` | TIMESTAMP | No | Record creation time. |

### `staging.orders`

| Column | Type | Null | Description |
|---|---|---|---|
| `order_id` | TEXT | No | Unique order identifier. Counted for `total_orders`. |
| `customer_id` | TEXT | No | FK to `staging.customers`. |
| `product_id` | TEXT | No | FK to `staging.products`. |
| `amount` | NUMERIC(10,2) | No | Transaction value. Summed for `lifetime_value` and `total_spend`. |
| `payment_status` | TEXT | No | **Filter field.** Only `completed` orders count toward any metric, so failed and pending orders never overstate revenue. |
| `region` | TEXT | Yes | Transaction region. Not carried into analytics. |
| `created_at` | TIMESTAMP | No | Order timestamp. Drives every recency and tenure calculation. |

---

## Analytics datasets

Written by the pipeline to the `analytics` schema. Fully rebuilt each run, so the pipeline is idempotent.

### `analytics.customer_segmentation`

One row per customer. Every customer appears, including those with no orders.

| Column | Type | Null | Derivation |
|---|---|---|---|
| `customer_id` | TEXT | No | From `staging.customers`. Primary key. |
| `customer_name` | TEXT | No | From `staging.customers.name`. |
| `total_orders` | INTEGER | No | `COUNT(order_id)` over completed orders. `0` if none. |
| `total_spend` | NUMERIC(12,2) | No | `SUM(amount)` over completed orders. `0.00` if none. |
| `segment` | TEXT | No | `New Customer`, `Returning Customer`, `VIP Customer`, or `At-Risk Customer`. See [segmentation](#segmentation). |

### `analytics.customer_360`

One row per customer. The unified profile.

| Column | Type | Null | Derivation |
|---|---|---|---|
| `customer_id` | TEXT | No | Primary key. |
| `lifetime_value` | NUMERIC(12,2) | No | `SUM(amount)` over completed orders. The same figure as `total_spend`, named for its analytical meaning here. |
| `total_orders` | INTEGER | No | `COUNT(order_id)` over completed orders. A **count**. |
| `purchase_frequency` | NUMERIC(8,2) | No | A **rate**: `total_orders / max(months since first purchase, 1)`. Separates four orders last month from four orders over three years, which a count cannot. Tenure is floored at one month so a same-day first purchase does not report an absurd rate. |
| `last_purchase_date` | TIMESTAMP | Yes | `MAX(created_at)` over completed orders. `NULL` if never ordered. |
| `preferred_category` | TEXT | No | The category ordered from most often, resolved by joining orders to products. `'None'` if no orders. Ties broken by first occurrence. |
| `churn_risk` | TEXT | No | `Low`, `Medium`, or `High`, from days since last purchase. See [churn risk](#churn-risk). |

### `analytics.campaign_recommendations`

One row per customer. The actionable output, and the dataset synced to Monday.

| Column | Type | Null | Derivation |
|---|---|---|---|
| `customer_id` | TEXT | No | Join key. |
| `segment` | TEXT | No | From `customer_segmentation`. |
| `churn_risk` | TEXT | No | From `customer_360`. **Feeds the rules**, not merely displayed. |
| `lifetime_value` | NUMERIC(12,2) | No | From `customer_360`. **Feeds the rules** as an override. |
| `holiday_name` | TEXT | No | The selected upcoming holiday, or `'No upcoming holiday'` if none clears the filters. |
| `days_until_holiday` | INTEGER | No | Days from today to that holiday. Always at least `HOLIDAY_MIN_LEAD_DAYS` unless no holiday was found. |
| `recommended_campaign` | TEXT | No | One of six campaigns. See [campaign recommendations](#campaign-recommendations). |
| `priority` | INTEGER | No | `1` (act now) to `4` (routine). Rows sort by priority, then by descending lifetime value, so the CRM can be worked top-down by urgency. |

---

## Monday CRM board

Columns are created automatically by `ensure_columns()` on first sync. Monday assigns its own internal column IDs, resolved at runtime rather than hardcoded.

| Board column | Monday type | Source field |
|---|---|---|
| *(item name)* | — | `customer_name` |
| Customer ID | text | `customer_id` |
| Priority | numbers | `priority` |
| Segment | **status** | `segment` |
| Recommended Campaign | text | `recommended_campaign` |
| Holiday | text | `holiday_name` |
| Days Until Holiday | numbers | `days_until_holiday` |
| Churn Risk | **status** | `churn_risk` |
| Lifetime Value | numbers | `lifetime_value` |
| Total Orders | numbers | `total_orders` |
| Orders / Month | numbers | `purchase_frequency` |

Segment and Churn Risk are **status** columns so the board can be filtered and grouped by them. Monday cannot change a column's type after creation, so `ensure_columns()` raises rather than silently mismatching if a column exists with the wrong type.

---

## Business rules

### Segmentation

Evaluated in order; first match wins.

| Order | Condition | Segment |
|---|---|---|
| 1 | Days since last purchase > `CHURN_DAYS_THRESHOLD` (90) | **At-Risk Customer** |
| 2 | `total_spend` ≥ `VIP_SPEND_THRESHOLD` (5,000) **or** `total_orders` ≥ `VIP_ORDER_THRESHOLD` (10) | **VIP Customer** |
| 3 | `total_orders` ≥ `RETURNING_ORDER_THRESHOLD` (2) | **Returning Customer** |
| 4 | Otherwise | **New Customer** |

**At-Risk deliberately outranks VIP.** A lapsed high-value customer is the most urgent case in the book, and burying them under a VIP label would hide exactly what needs seeing. The consequence is that a lapsed VIP can never appear in the VIP segment, which is precisely why lifetime value must feed the campaign rules separately.

### Churn risk

Days since last completed purchase, against `CHURN_DAYS_THRESHOLD` (90).

| Days since last purchase | Churn risk |
|---|---|
| > 90, or never ordered | **High** |
| 46 – 90 | **Medium** |
| ≤ 45 | **Low** |

### Campaign recommendations

The primary rule is a **segment × churn risk** matrix. Priority in parentheses.

| Segment | Churn: High | Churn: Medium | Churn: Low |
|---|---|---|---|
| **VIP** | Premium Win-Back `(1)` | Premium Retention `(2)` | Premium Loyalty `(3)` |
| **Returning** | Win-Back `(1)` | Re-engagement `(2)` | Seasonal Discount `(3)` |
| **New** | Onboarding Rescue `(2)` | Second Purchase Nudge `(3)` | Welcome Offer `(4)` |
| **At-Risk** | Win-Back `(1)` | Win-Back `(2)` | Re-engagement `(3)` |

**Lifetime value then overrides the matrix in two cases:**

| Condition | Result | Why |
|---|---|---|
| `lifetime_value` ≥ `VIP_SPEND_THRESHOLD`, churn is High or Medium, and segment is At-Risk or Returning | **Premium Win-Back**, priority 1 | Segmentation flattens every lapsed customer into At-Risk regardless of worth, so someone worth £14,400 and someone worth £90 land in the same bucket. Only lifetime value separates them. |
| Segment is Returning, `lifetime_value` ≥ 60% of `VIP_SPEND_THRESHOLD`, and churn is Low | **VIP Upgrade Offer**, priority 2 | Someone spending like a VIP is behaving like one. Recognising it early is the difference between growing the account and letting a competitor grow it. |

### Holiday selection

The nearest upcoming holiday is not necessarily a useful one.

| Filter | Default | Rationale |
|---|---|---|
| `HOLIDAY_MIN_LEAD_DAYS` | 14 | A holiday two days out cannot be planned around. There is no time to brief, build, and ship, so a recommendation pegged to it is accurate and worthless. |
| `HOLIDAY_NATIONWIDE_ONLY` | true | A UK query returns regional dates (Battle of the Boyne is Northern Ireland only; St Andrew's Day is Scotland only). Anchoring a nationwide campaign to a holiday most customers do not observe is a business error, not a cosmetic one. |

The lookup spans the configured year and the following one, so a December run still finds an actionable holiday rather than falling off the end of the calendar.

---

## Configuration reference

| Variable | Default | Affects |
|---|---|---|
| `VIP_SPEND_THRESHOLD` | 5000 | VIP segment; both lifetime-value overrides |
| `VIP_ORDER_THRESHOLD` | 10 | VIP segment |
| `RETURNING_ORDER_THRESHOLD` | 2 | Returning segment |
| `CHURN_DAYS_THRESHOLD` | 90 | At-Risk segment; all three churn bands |
| `HOLIDAY_MIN_LEAD_DAYS` | 14 | Holiday selection |
| `HOLIDAY_NATIONWIDE_ONLY` | true | Holiday selection |
| `HOLIDAY_COUNTRY` | GB | Holiday lookup |
| `HOLIDAY_YEAR` | 2026 | Holiday lookup, plus the following year |

---

## Worked example

The seeded dataset, run end to end.

| Customer | Segment | Churn | LTV | Campaign | Priority |
|---|---|---|---|---|---|
| Barbara Liskov | At-Risk | High | £14,400 | **Premium Win-Back** | 1 |
| Edsger Dijkstra | At-Risk | High | £90 | Win-Back | 1 |
| Alonzo Church | Returning | Low | £3,810 | **VIP Upgrade Offer** | 2 |
| Katherine Johnson | VIP | Low | £7,200 | Premium Loyalty | 3 |
| Ada Lovelace | Returning | Low | £2,600 | Seasonal Discount | 3 |
| Grace Hopper | New | Low | £200 | Welcome Offer | 4 |
| Alan Turing | New | Low | £90 | Welcome Offer | 4 |

Rows 1 and 2 are the point: **identical segment, identical churn risk, different campaign.** A segment-only engine cannot tell Barbara from Edsger. Lifetime value can, and that distinction is the entire reason Customer 360 feeds the rule engine rather than merely decorating the board.

A sales rep opens the board, sorts by Priority, and works down. Barbara surfaces first: a £14,400 customer who has gone quiet, and the most expensive person in the list to lose.