-- Sample staging data for local testing without the Mandera pipeline.
-- Loaded automatically by the data-db service on first start.
-- Skip this file if pointing at a real Mandera staging schema.
--
-- The customers below are chosen to exercise every segment and every branch of
-- the campaign rule engine, including the cases that segment alone cannot see:
--
--   C001 Ada       Returning       recent, moderate spend
--   C002 Alan      New             single small order
--   C003 Grace     New             single small order, recent
--   C004 Edsger    At-Risk         lapsed, LOW value    -> generic Win-Back
--   C005 Barbara   At-Risk         lapsed, HIGH value   -> Premium Win-Back
--   C006 Katherine VIP             high spend, active   -> Premium Loyalty
--   C007 Alonzo    Returning       spending like a VIP  -> VIP Upgrade Offer
--
-- C004 and C005 are the point: identical segment and churn risk, wildly
-- different worth. A segment-only engine gives them the same campaign.

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.customers (
    customer_id TEXT, name TEXT, email TEXT, phone TEXT,
    city TEXT, batch_id TEXT, created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staging.products (
    product_id TEXT, product_name TEXT, category TEXT,
    price NUMERIC(10,2), batch_id TEXT, created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staging.orders (
    order_id TEXT, customer_id TEXT, product_id TEXT,
    amount NUMERIC(10,2), payment_status TEXT, region TEXT,
    created_at TIMESTAMP
);

INSERT INTO staging.customers VALUES
('C001','Ada Lovelace','ada@example.com','07700900001','London','b1','2026-05-01'),
('C002','Alan Turing','alan@example.com','07700900002','Manchester','b1','2026-01-10'),
('C003','Grace Hopper','grace@example.com','07700900003','Leeds','b1','2026-06-15'),
('C004','Edsger Dijkstra','edsger@example.com','07700900004','Bristol','b1','2025-12-01'),
('C005','Barbara Liskov','barbara@example.com','07700900005','Edinburgh','b1','2025-09-01'),
('C006','Katherine Johnson','katherine@example.com','07700900006','Cardiff','b1','2025-11-15'),
('C007','Alonzo Church','alonzo@example.com','07700900007','Birmingham','b1','2026-02-20');

INSERT INTO staging.products VALUES
('P001','Laptop','Electronics',1200.00,'b1','2026-01-01'),
('P002','Headphones','Electronics',200.00,'b1','2026-01-01'),
('P003','Coffee Maker','Home',90.00,'b1','2026-01-01'),
('P004','Monitor','Electronics',450.00,'b1','2026-01-01'),
('P005','Desk Lamp','Home',60.00,'b1','2026-01-01');

-- C001 Ada: 3 recent orders, 2,600 total -> Returning, Low churn
INSERT INTO staging.orders VALUES
('O001','C001','P001',1200.00,'completed','UK','2026-06-20'),
('O002','C001','P002',200.00,'completed','UK','2026-06-22'),
('O003','C001','P001',1200.00,'completed','UK','2026-06-25');

-- C002 Alan, C003 Grace: single small orders -> New
INSERT INTO staging.orders VALUES
('O004','C002','P003',90.00,'completed','UK','2026-06-10'),
('O005','C003','P002',200.00,'completed','UK','2026-06-28');

-- C004 Edsger: one small order back in January -> At-Risk, LOW value (90)
INSERT INTO staging.orders VALUES
('O006','C004','P003',90.00,'completed','UK','2026-01-15');

-- C005 Barbara: heavy spender who went silent in February.
-- 12 orders, 14,400 total. Segmentation calls her At-Risk exactly like Edsger;
-- only lifetime value distinguishes them.
INSERT INTO staging.orders VALUES
('O007','C005','P001',1200.00,'completed','UK','2025-10-05'),
('O008','C005','P001',1200.00,'completed','UK','2025-10-28'),
('O009','C005','P001',1200.00,'completed','UK','2025-11-14'),
('O010','C005','P001',1200.00,'completed','UK','2025-11-30'),
('O011','C005','P001',1200.00,'completed','UK','2025-12-09'),
('O012','C005','P001',1200.00,'completed','UK','2025-12-21'),
('O013','C005','P001',1200.00,'completed','UK','2026-01-06'),
('O014','C005','P001',1200.00,'completed','UK','2026-01-18'),
('O015','C005','P001',1200.00,'completed','UK','2026-01-27'),
('O016','C005','P001',1200.00,'completed','UK','2026-02-03'),
('O017','C005','P001',1200.00,'completed','UK','2026-02-10'),
('O018','C005','P001',1200.00,'completed','UK','2026-02-14');

-- C006 Katherine: high spend AND still active -> VIP, Low churn
-- 6 orders, 7,200 total, most recent within the churn window.
INSERT INTO staging.orders VALUES
('O019','C006','P001',1200.00,'completed','UK','2026-05-02'),
('O020','C006','P001',1200.00,'completed','UK','2026-05-19'),
('O021','C006','P001',1200.00,'completed','UK','2026-06-01'),
('O022','C006','P001',1200.00,'completed','UK','2026-06-12'),
('O023','C006','P001',1200.00,'completed','UK','2026-06-24'),
('O024','C006','P001',1200.00,'completed','UK','2026-07-02');

-- C007 Alonzo: 3,600 total. Above 60% of the 5,000 VIP threshold but below it,
-- and still active -> Returning with Low churn -> VIP Upgrade Offer.
INSERT INTO staging.orders VALUES
('O025','C007','P004',450.00,'completed','UK','2026-05-10'),
('O026','C007','P004',450.00,'completed','UK','2026-05-24'),
('O027','C007','P001',1200.00,'completed','UK','2026-06-08'),
('O028','C007','P004',450.00,'completed','UK','2026-06-18'),
('O029','C007','P001',1200.00,'completed','UK','2026-06-30'),
('O030','C007','P005',60.00,'completed','UK','2026-07-05');

-- A failed payment, to exercise the payment_status filter.
INSERT INTO staging.orders VALUES
('O031','C002','P001',1200.00,'failed','UK','2026-06-30');