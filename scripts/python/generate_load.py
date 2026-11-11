"""Generate a realistic, deliberately imperfect workload against sredb for Query Insights.

Three subcommands, meant to be run in order to show a before/after:

  setup  Create dbo.customers (20k rows) and dbo.orders (500k rows). orders has
         NO index on customer_id, so customer lookups scan the whole table.
  run    Run a weighted mix of queries from several concurrent workers for N
         minutes and print per-query latency. Includes a missing-index scan and
         a non-sargable predicate, the two most common real-world culprits.
  index  Add the missing index on orders(customer_id). Run `run` again and
         compare Query Insights before and after.
  drop   Drop the tables.

Usage (from the repo root, values from `terraform output`):
    python scripts/python/generate_load.py setup --connection-name <...> --secret-id <...>
    python scripts/python/generate_load.py run   --connection-name <...> --secret-id <...> --minutes 5
    python scripts/python/generate_load.py index --connection-name <...> --secret-id <...>
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import threading
import time
from collections import defaultdict

from cloudsql_conn import add_connection_args, cloudsql_server

CUSTOMERS = 20_000
ORDERS = 500_000

SETUP_SQL = [
    """
    IF OBJECT_ID('dbo.orders') IS NOT NULL DROP TABLE dbo.orders;
    IF OBJECT_ID('dbo.customers') IS NOT NULL DROP TABLE dbo.customers;
    """,
    """
    CREATE TABLE dbo.customers (
        customer_id int IDENTITY(1,1) PRIMARY KEY,
        region      varchar(20)  NOT NULL,
        email       varchar(100) NOT NULL,
        created_at  datetime2    NOT NULL
    );
    """,
    """
    -- Deliberately no index on customer_id or status: the clustered PK is the only index.
    CREATE TABLE dbo.orders (
        order_id    int IDENTITY(1,1) PRIMARY KEY,
        customer_id int           NOT NULL,
        order_date  datetime2     NOT NULL,
        amount      decimal(10,2) NOT NULL,
        status      varchar(20)   NOT NULL
    );
    """,
    f"""
    WITH n AS (
        SELECT TOP ({CUSTOMERS}) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
        FROM sys.all_objects a CROSS JOIN sys.all_objects b
    )
    INSERT dbo.customers (region, email, created_at)
    SELECT CHOOSE(i % 5 + 1, 'UK', 'EU', 'US', 'APAC', 'LATAM'),
           CONCAT('User', i, '@Example.com'),
           DATEADD(day, -(i % 1000), SYSUTCDATETIME())
    FROM n;
    """,
    f"""
    WITH n AS (
        SELECT TOP ({ORDERS}) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
        FROM sys.all_objects a CROSS JOIN sys.all_objects b
    )
    INSERT dbo.orders (customer_id, order_date, amount, status)
    SELECT ABS(CHECKSUM(NEWID())) % {CUSTOMERS} + 1,
           DATEADD(minute, -(ABS(CHECKSUM(NEWID())) % 525600), SYSUTCDATETIME()),
           CAST(ABS(CHECKSUM(NEWID())) % 50000 / 100.0 AS decimal(10,2)),
           CHOOSE(i % 4 + 1, 'NEW', 'PAID', 'SHIPPED', 'CANCELLED')
    FROM n;
    """,
]

INDEX_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_orders_customer_id')
    CREATE NONCLUSTERED INDEX IX_orders_customer_id
        ON dbo.orders (customer_id) INCLUDE (order_date, amount, status);
"""

DROP_SQL = """
IF OBJECT_ID('dbo.orders') IS NOT NULL DROP TABLE dbo.orders;
IF OBJECT_ID('dbo.customers') IS NOT NULL DROP TABLE dbo.customers;
"""


def rand_customer() -> int:
    return random.randint(1, CUSTOMERS)


def rand_order() -> int:
    return random.randint(1, ORDERS)


# name -> (weight, sql, params factory). Parameterised so Insights groups each
# shape into one normalised query.
WORKLOAD = {
    "pk_lookup": (
        40,
        "SELECT order_id, customer_id, amount, status FROM dbo.orders WHERE order_id = %s",
        lambda: (rand_order(),),
    ),
    "orders_by_customer (missing index)": (
        25,
        "SELECT order_id, order_date, amount, status FROM dbo.orders "
        "WHERE customer_id = %s ORDER BY order_date DESC",
        lambda: (rand_customer(),),
    ),
    "revenue_by_region_30d": (
        10,
        "SELECT c.region, COUNT(*) AS orders, SUM(o.amount) AS revenue "
        "FROM dbo.orders o JOIN dbo.customers c ON c.customer_id = o.customer_id "
        "WHERE o.order_date >= DATEADD(day, -30, SYSUTCDATETIME()) AND o.status <> %s "
        "GROUP BY c.region",
        lambda: ("CANCELLED",),
    ),
    "customer_by_email (non-sargable)": (
        10,
        "SELECT customer_id, region FROM dbo.customers WHERE LOWER(email) = %s",
        lambda: (f"user{rand_customer()}@example.com",),
    ),
    "insert_order": (
        10,
        "INSERT dbo.orders (customer_id, order_date, amount, status) "
        "VALUES (%s, SYSUTCDATETIME(), %s, 'NEW')",
        lambda: (rand_customer(), round(random.uniform(5, 500), 2)),
    ),
    "update_status": (
        5,
        "UPDATE dbo.orders SET status = %s WHERE order_id = %s",
        lambda: (random.choice(["PAID", "SHIPPED"]), rand_order()),
    ),
}


def run_batch(server, statements) -> None:
    conn = server.connect()
    try:
        cur = conn.cursor()
        for sql in statements:
            cur.execute(sql)
    finally:
        conn.close()


def worker(conn, stop_at: float, results: dict, errors: list, lock: threading.Lock) -> None:
    names = list(WORKLOAD)
    weights = [WORKLOAD[n][0] for n in names]
    cur = conn.cursor()
    local = defaultdict(list)
    while time.monotonic() < stop_at:
        name = random.choices(names, weights)[0]
        _, sql, params = WORKLOAD[name]
        start = time.perf_counter()
        try:
            cur.execute(sql, params())
            if cur.description:
                cur.fetchall()
        except Exception as exc:  # keep the load running; report at the end
            with lock:
                errors.append(f"{name}: {exc}")
            continue
        local[name].append((time.perf_counter() - start) * 1000)
    with lock:
        for name, samples in local.items():
            results[name].extend(samples)


def run_load(server, minutes: float, workers: int) -> None:
    conns = [server.connect() for _ in range(workers)]
    results: dict = defaultdict(list)
    errors: list = []
    lock = threading.Lock()
    stop_at = time.monotonic() + minutes * 60
    threads = [
        threading.Thread(target=worker, args=(c, stop_at, results, errors, lock), daemon=True)
        for c in conns
    ]
    print(f"Running {workers} workers for {minutes} min...")
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in conns:
        c.close()

    total = sum(len(v) for v in results.values())
    print(f"\n{'query':<36}{'calls':>8}{'avg ms':>10}{'p95 ms':>10}{'max ms':>10}")
    for name in WORKLOAD:
        s = sorted(results.get(name, []))
        if not s:
            continue
        p95 = s[int(len(s) * 0.95) - 1] if len(s) >= 20 else s[-1]
        print(f"{name:<36}{len(s):>8}{statistics.mean(s):>10.1f}{p95:>10.1f}{s[-1]:>10.1f}")
    print(f"\n{total} queries, {total / (minutes * 60):.1f}/s overall")
    if errors:
        print(f"{len(errors)} errors, first: {errors[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["setup", "run", "index", "drop"])
    add_connection_args(parser)
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    with cloudsql_server(args.connection_name, args.secret_id, args.database, args.user) as server:
        start = time.perf_counter()
        if args.command == "setup":
            print(f"Creating tables and loading {CUSTOMERS:,} customers / {ORDERS:,} orders...")
            run_batch(server, SETUP_SQL)
        elif args.command == "index":
            print("Creating IX_orders_customer_id...")
            run_batch(server, [INDEX_SQL])
        elif args.command == "drop":
            run_batch(server, [DROP_SQL])
        else:
            run_load(server, args.minutes, args.workers)
        print(f"Done in {time.perf_counter() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
