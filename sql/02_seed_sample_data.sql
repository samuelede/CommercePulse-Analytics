-- Optional sample staging data for local testing without the Mandera pipeline.
-- Skip this if you already have staging populated by Mandera.

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
('C001','Ada Lovelace','ada@x.io','111','London','b1','2026-05-01'),
('C002','Alan Turing','alan@x.io','222','Manchester','b1','2026-01-10'),
('C003','Grace Hopper','grace@x.io','333','Leeds','b1','2026-06-15'),
('C004','Edsger Dijkstra','ed@x.io','444','Bristol','b1','2025-12-01');

INSERT INTO staging.products VALUES
('P001','Laptop','Electronics',1200.00,'b1','2026-01-01'),
('P002','Headphones','Electronics',200.00,'b1','2026-01-01'),
('P003','Coffee Maker','Home',90.00,'b1','2026-01-01');

INSERT INTO staging.orders VALUES
('O001','C001','P001',1200.00,'completed','UK','2026-06-20'),
('O002','C001','P002',200.00,'completed','UK','2026-06-22'),
('O003','C001','P001',1200.00,'completed','UK','2026-06-25'),
('O004','C002','P003',90.00,'completed','UK','2026-06-10'),
('O005','C003','P002',200.00,'completed','UK','2026-06-28'),
('O006','C004','P003',90.00,'completed','UK','2026-01-15');
