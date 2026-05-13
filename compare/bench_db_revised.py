#!/usr/bin/env python3
"""
TiDB vs Aurora DSQL vs Aurora MySQL Performance Benchmark (Large Scale)
=======================================================================
Usage:
  # TiDB:
  python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --rows 1000000

  # Aurora DSQL:
  python3 bench_db.py --db dsql --host lmabug6a7xcqjqohrppfncdfsa.dsql.us-east-1.on.aws --user admin --database postgres --aws-region us-east-1 --rows 1000000

  # Aurora MySQL:
  python3 bench_db.py --db aurora-mysql --host mycluster.cluster-xxxx.us-east-1.rds.amazonaws.com --port 3306 --user admin --password "password" --database test --rows 1000000

  # SELECT tests only (skip INSERT if data already loaded):
  python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --skip-insert

Requirements:
  pip3 install pymysql psycopg boto3
"""

import argparse
import time
import statistics
import sys
import uuid
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BATCH_SIZE = 500    # rows per INSERT statement (multi-value)


def measure_network_latency(host, port, attempts=5):
    """Measure TCP connection latency (RTT) to the target host.
    MySQL/PostgreSQL use STARTTLS (upgrade after protocol handshake), so pure
    TLS socket probes fail with WRONG_VERSION_NUMBER. TCP RTT is the fair
    baseline comparison across Aurora MySQL, TiDB, and DSQL.
    """
    import socket
    latencies = []
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            start = time.perf_counter()
            sock.connect((host, port))
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            sock.close()
        except Exception as e:
            print(f"  [WARN] TCP probe failed: {e}")
            sock.close()
    return latencies

def get_connection(args, autocommit=True):
    """Create a new DB connection.

    NOTE: For DSQL, each call generates a new IAM auth token and establishes a new
    SSL connection. In single-thread mode, main() calls this once and reuses the
    connection for all iterations. In multi-thread mode, each worker calls this once
    (i.e., connections = threads + 1, NOT connections = iterations).
    """
    if args.db in ("tidb", "aurora-mysql"):
        import pymysql
        return pymysql.connect(
            host=args.host, port=args.port,
            user=args.user, password=args.password,
            database=args.database, charset="utf8mb4",
            autocommit=autocommit
        )
    elif args.db == "dsql":
        import boto3, psycopg
        session = boto3.Session(region_name=args.aws_region)
        client = session.client("dsql")
        token = client.generate_db_connect_admin_auth_token(args.host, args.aws_region, ExpiresIn=3600)
        conn = psycopg.connect(
            host=args.host, port=args.port, user=args.user,
            password=token, dbname=args.database, sslmode="require",
            autocommit=autocommit
        )
        return conn

def setup_tables(conn, args):
    """Drop and recreate tables."""
    cur = conn.cursor()
    print("[SETUP] Dropping existing tables...")

    if args.db in ("tidb", "aurora-mysql"):
        cur.execute("DROP TABLE IF EXISTS salaries")
        cur.execute("DROP TABLE IF EXISTS employees")
        cur.execute("""
            CREATE TABLE employees (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                emp_no INT NOT NULL,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                birth_date DATE,
                hire_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE salaries (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                emp_no INT NOT NULL,
                salary INT NOT NULL,
                from_date DATE,
                to_date DATE
            )
        """)
    else:
        cur.execute("DROP TABLE IF EXISTS salaries")
        cur.execute("DROP TABLE IF EXISTS employees")
        conn.commit()
        cur.execute("""
            CREATE TABLE employees (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                emp_no INT NOT NULL,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                birth_date DATE,
                hire_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE salaries (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                emp_no INT NOT NULL,
                salary INT NOT NULL,
                from_date DATE,
                to_date DATE
            )
        """)
        conn.commit()

    print("[SETUP] Tables created.")
    cur.close()

def generate_employee_row(i):
    first_names = ["James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda","David","Elizabeth",
                   "William","Barbara","Richard","Susan","Joseph","Jessica","Thomas","Sarah","Christopher","Karen"]
    last_names = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
                  "Wilson","Anderson","Taylor","Thomas","Moore","Jackson","Martin","Lee","Thompson","White"]
    uid = str(uuid.uuid4())
    emp_no = 10001 + i
    fn = first_names[i % len(first_names)]
    ln = last_names[i % len(last_names)]
    bd = datetime.date(1960 + (i % 35), (i % 12) + 1, (i % 28) + 1)
    hd = datetime.date(2010 + (i % 15), (i % 12) + 1, (i % 28) + 1)
    return (uid, emp_no, fn, ln, bd, hd)

def generate_salary_row(i):
    uid = str(uuid.uuid4())
    emp_no = 10001 + i
    salary = 30000 + (i * 13) % 120000
    fd = datetime.date(2020, 1, 1)
    td = datetime.date(2024, 12, 31)
    return (uid, emp_no, salary, fd, td)

def bulk_insert_tidb(conn, args, num_rows):
    """Batch INSERT for TiDB using multi-value INSERT."""
    cur = conn.cursor()
    batch = args.batch_size

    print(f"[INSERT] Loading {num_rows} employees (batch={batch})...")
    start = time.perf_counter()
    for offset in range(0, num_rows, batch):
        end = min(offset + batch, num_rows)
        rows = [generate_employee_row(i) for i in range(offset, end)]
        placeholders = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(rows))
        flat = [v for row in rows for v in row]
        cur.execute(f"INSERT INTO employees (id,emp_no,first_name,last_name,birth_date,hire_date) VALUES {placeholders}", flat)
        if (offset + batch) % 100000 == 0 or end == num_rows:
            print(f"  ... {end:,} employees")
    emp_time = time.perf_counter() - start

    print(f"[INSERT] Loading {num_rows} salaries (batch={batch})...")
    start = time.perf_counter()
    for offset in range(0, num_rows, batch):
        end = min(offset + batch, num_rows)
        rows = [generate_salary_row(i) for i in range(offset, end)]
        placeholders = ",".join(["(%s,%s,%s,%s,%s)"] * len(rows))
        flat = [v for row in rows for v in row]
        cur.execute(f"INSERT INTO salaries (id,emp_no,salary,from_date,to_date) VALUES {placeholders}", flat)
        if (offset + batch) % 100000 == 0 or end == num_rows:
            print(f"  ... {end:,} salaries")
    sal_time = time.perf_counter() - start

    cur.close()
    total = emp_time + sal_time
    print(f"[INSERT] Done. employees={emp_time:.1f}s, salaries={sal_time:.1f}s, total={total:.1f}s")
    print(f"[INSERT] Throughput: {num_rows*2/total:.0f} rows/sec")
    return total

def bulk_insert_dsql(conn, args, num_rows):
    """Batch INSERT for DSQL using multi-value INSERT (same as TiDB)."""
    cur = conn.cursor()
    batch = args.batch_size

    print(f"[INSERT] Loading {num_rows} employees (batch={batch})...")
    conn.autocommit = False
    start = time.perf_counter()
    for offset in range(0, num_rows, batch):
        end = min(offset + batch, num_rows)
        rows = [generate_employee_row(i) for i in range(offset, end)]
        placeholders = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(rows))
        flat = [v for row in rows for v in row]
        cur.execute(f"INSERT INTO employees (id,emp_no,first_name,last_name,birth_date,hire_date) VALUES {placeholders}", flat)
        conn.commit()
        if (offset + batch) % 100000 == 0 or end == num_rows:
            print(f"  ... {end:,} employees")
    emp_time = time.perf_counter() - start

    print(f"[INSERT] Loading {num_rows} salaries (batch={batch})...")
    start = time.perf_counter()
    for offset in range(0, num_rows, batch):
        end = min(offset + batch, num_rows)
        rows = [generate_salary_row(i) for i in range(offset, end)]
        placeholders = ",".join(["(%s,%s,%s,%s,%s)"] * len(rows))
        flat = [v for row in rows for v in row]
        cur.execute(f"INSERT INTO salaries (id,emp_no,salary,from_date,to_date) VALUES {placeholders}", flat)
        conn.commit()
        if (offset + batch) % 100000 == 0 or end == num_rows:
            print(f"  ... {end:,} salaries")
    sal_time = time.perf_counter() - start

    conn.autocommit = True
    cur.close()
    total = emp_time + sal_time
    print(f"[INSERT] Done. employees={emp_time:.1f}s, salaries={sal_time:.1f}s, total={total:.1f}s")
    print(f"[INSERT] Throughput: {num_rows*2/total:.0f} rows/sec")
    return total

def bench_pk_lookup(conn, args, iterations=200):
    """Benchmark: SELECT * FROM employees WHERE id = <pk>"""
    cur = conn.cursor()

    # Get random PKs uniformly distributed across the table (NOT included in measurement)
    fetch_start = time.perf_counter()
    if args.db in ("tidb", "aurora-mysql"):
        cur.execute("SELECT id FROM employees ORDER BY RAND() LIMIT %d" % iterations)
    else:
        cur.execute("SELECT id FROM employees ORDER BY random() LIMIT %d" % iterations)
    pks = [row[0] for row in cur.fetchall()]
    fetch_elapsed = (time.perf_counter() - fetch_start) * 1000
    print(f"  [PREP] Random PK fetch: {fetch_elapsed:.1f} ms ({len(pks)} rows)")
    cur.close()

    WARMUP_QUERIES = 1  # first query per worker recorded as cold-start

    threads = args.threads
    if threads == 1:
        # Single-thread path
        cur = conn.cursor()
        # Warmup (measured separately)
        warmup_latencies = []
        start = time.perf_counter()
        cur.execute("SELECT * FROM employees WHERE id = %s", (str(pks[0]),))
        cur.fetchall()
        warmup_latencies.append((time.perf_counter() - start) * 1000)
        # Measurement
        latencies = []
        measure_start = time.perf_counter()
        for pk in pks[WARMUP_QUERIES:]:
            start = time.perf_counter()
            cur.execute("SELECT * FROM employees WHERE id = %s", (str(pk),))
            cur.fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        measure_elapsed = time.perf_counter() - measure_start
        cur.close()
    else:
        # Multi-thread path: first query per worker is cold-start (includes connection setup)
        chunks = [pks[i::threads] for i in range(threads)]

        def worker(chunk):
            c = get_connection(args, autocommit=True)
            cur = c.cursor()
            # Cold-start query (measured separately)
            warmup = []
            start = time.perf_counter()
            cur.execute("SELECT * FROM employees WHERE id = %s", (str(chunk[0]),))
            cur.fetchall()
            warmup.append((time.perf_counter() - start) * 1000)
            # Steady-state measurement
            lats = []
            for pk in chunk[WARMUP_QUERIES:]:
                start = time.perf_counter()
                cur.execute("SELECT * FROM employees WHERE id = %s", (str(pk),))
                cur.fetchall()
                elapsed = (time.perf_counter() - start) * 1000
                lats.append(elapsed)
            cur.close()
            c.close()
            return lats, warmup

        latencies = []
        warmup_latencies = []
        measure_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, chunk) for chunk in chunks]
            for f in as_completed(futures):
                lats, warmup = f.result()
                latencies.extend(lats)
                warmup_latencies.extend(warmup)
        measure_elapsed = time.perf_counter() - measure_start

    return latencies, warmup_latencies, measure_elapsed

def bench_join_query(conn, args, iterations=200):
    """Benchmark: JOIN on emp_no (no index)"""
    cur = conn.cursor()

    # Get random emp_no values uniformly distributed across the table (NOT included in measurement)
    fetch_start = time.perf_counter()
    if args.db in ("tidb", "aurora-mysql"):
        cur.execute("SELECT emp_no FROM employees ORDER BY RAND() LIMIT %d" % iterations)
    else:
        cur.execute("SELECT emp_no FROM employees ORDER BY random() LIMIT %d" % iterations)
    emp_nos = [row[0] for row in cur.fetchall()]
    fetch_elapsed = (time.perf_counter() - fetch_start) * 1000
    print(f"  [PREP] Random emp_no fetch: {fetch_elapsed:.1f} ms ({len(emp_nos)} rows)")
    cur.close()

    WARMUP_QUERIES = 1  # first query per worker recorded as cold-start

    threads = args.threads
    if threads == 1:
        cur = conn.cursor()
        # Warmup (measured separately)
        warmup_latencies = []
        start = time.perf_counter()
        cur.execute("""
            SELECT e.emp_no, e.first_name, e.last_name, s.salary
            FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
            WHERE e.emp_no = %s
        """, (emp_nos[0],))
        cur.fetchall()
        warmup_latencies.append((time.perf_counter() - start) * 1000)
        # Measurement
        latencies = []
        measure_start = time.perf_counter()
        for eno in emp_nos[WARMUP_QUERIES:]:
            start = time.perf_counter()
            cur.execute("""
                SELECT e.emp_no, e.first_name, e.last_name, s.salary
                FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
                WHERE e.emp_no = %s
            """, (eno,))
            cur.fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        measure_elapsed = time.perf_counter() - measure_start
        cur.close()
    else:
        # Multi-thread path: first query per worker is cold-start
        chunks = [emp_nos[i::threads] for i in range(threads)]

        def worker(chunk):
            c = get_connection(args, autocommit=True)
            cur = c.cursor()
            # Cold-start query (measured separately)
            warmup = []
            start = time.perf_counter()
            cur.execute("""
                SELECT e.emp_no, e.first_name, e.last_name, s.salary
                FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
                WHERE e.emp_no = %s
            """, (chunk[0],))
            cur.fetchall()
            warmup.append((time.perf_counter() - start) * 1000)
            # Steady-state measurement
            lats = []
            for eno in chunk[WARMUP_QUERIES:]:
                start = time.perf_counter()
                cur.execute("""
                    SELECT e.emp_no, e.first_name, e.last_name, s.salary
                    FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
                    WHERE e.emp_no = %s
                """, (eno,))
                cur.fetchall()
                elapsed = (time.perf_counter() - start) * 1000
                lats.append(elapsed)
            cur.close()
            c.close()
            return lats, warmup

        latencies = []
        warmup_latencies = []
        measure_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, chunk) for chunk in chunks]
            for f in as_completed(futures):
                lats, warmup = f.result()
                latencies.extend(lats)
                warmup_latencies.extend(warmup)
        measure_elapsed = time.perf_counter() - measure_start

    return latencies, warmup_latencies, measure_elapsed

def _index_exists(cur, table, index_name):
    """Check if an index exists (MySQL/TiDB)."""
    cur.execute(f"SHOW INDEX FROM {table} WHERE Key_name = %s", (index_name,))
    return cur.fetchone() is not None

def create_indexes(conn, args):
    """Create covering indexes on emp_no for JOIN acceleration."""
    cur = conn.cursor()

    if args.db == "dsql":
        # Check if indexes already exist
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname IN ('idx_emp_empno', 'idx_sal_empno')")
        existing = {row[0] for row in cur.fetchall()}
        if len(existing) == 2:
            print("[INDEX] Indexes already exist, skipping creation.")
            cur.close()
            return 0.0

        print("[INDEX] Creating indexes (ASYNC)...")
        start = time.perf_counter()
        if 'idx_emp_empno' not in existing:
            cur.execute("CREATE INDEX ASYNC idx_emp_empno ON employees (emp_no) INCLUDE (first_name, last_name)")
        if 'idx_sal_empno' not in existing:
            cur.execute("CREATE INDEX ASYNC idx_sal_empno ON salaries (emp_no) INCLUDE (salary)")
        conn.commit()
        print("[INDEX] Waiting for async index jobs to complete...")
        # Poll sys.jobs until both indexes are done
        while True:
            cur.execute("SELECT job_id, status FROM sys.jobs WHERE status NOT IN ('completed', 'failed')")
            pending = cur.fetchall()
            if not pending:
                break
            time.sleep(2)
            print(f"  ... {len(pending)} job(s) still running")
        elapsed = time.perf_counter() - start
        # Check for failures
        cur.execute("SELECT job_id, status FROM sys.jobs WHERE status = 'failed'")
        failed = cur.fetchall()
        if failed:
            print(f"[INDEX] WARNING: {len(failed)} index job(s) FAILED: {failed}")
        else:
            print(f"[INDEX] Done. Elapsed: {elapsed:.1f}s")
    else:
        print("[INDEX] Creating indexes...")
        start = time.perf_counter()
        if _index_exists(cur, 'employees', 'idx_emp_empno'):
            cur.execute("DROP INDEX idx_emp_empno ON employees")
        if _index_exists(cur, 'salaries', 'idx_sal_empno'):
            cur.execute("DROP INDEX idx_sal_empno ON salaries")
        cur.execute("CREATE INDEX idx_emp_empno ON employees (emp_no, first_name, last_name)")
        cur.execute("CREATE INDEX idx_sal_empno ON salaries (emp_no, salary)")
        elapsed = time.perf_counter() - start
        print(f"[INDEX] Done. Elapsed: {elapsed:.1f}s")

    cur.close()
    return elapsed

def print_results(name, latencies, elapsed_sec=None, warmup_latencies=None):
    p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
    p99_idx = min(int(len(latencies) * 0.99), len(latencies) - 1)
    sorted_lat = sorted(latencies)
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Iterations : {len(latencies)}")
    if elapsed_sec is not None:
        print(f"  Elapsed    : {elapsed_sec:.2f} s")
        print(f"  QPS        : {len(latencies)/elapsed_sec:.1f}")
    print(f"  Avg        : {statistics.mean(latencies):.2f} ms")
    print(f"  Median     : {statistics.median(latencies):.2f} ms")
    print(f"  P95        : {sorted_lat[p95_idx]:.2f} ms")
    print(f"  P99        : {sorted_lat[p99_idx]:.2f} ms")
    print(f"  Min        : {min(latencies):.2f} ms")
    print(f"  Max        : {max(latencies):.2f} ms")
    if len(latencies) > 1:
        print(f"  Stddev     : {statistics.stdev(latencies):.2f} ms")
    if warmup_latencies:
        print(f"  --- Cold Start (1st query per worker) ---")
        print(f"  Workers    : {len(warmup_latencies)}")
        print(f"  Avg        : {statistics.mean(warmup_latencies):.2f} ms")
        print(f"  Max        : {max(warmup_latencies):.2f} ms")
        print(f"  Min        : {min(warmup_latencies):.2f} ms")
    print(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser(description="DB Performance Benchmark - Large Scale")
    parser.add_argument("--db", required=True, choices=["tidb", "dsql", "aurora-mysql"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--database", default="test")
    parser.add_argument("--rows", type=int, default=1000000, help="Rows per table (default: 1M)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Rows per INSERT statement (default: 500)")
    parser.add_argument("--iterations", type=int, default=200, help="SELECT test iterations")
    parser.add_argument("--threads", type=int, default=1, help="Concurrent threads for SELECT tests (default: 1)")
    parser.add_argument("--skip-insert", action="store_true", help="Skip table setup and INSERT")
    parser.add_argument("--with-index", action="store_true", help="Create covering indexes and run indexed JOIN test")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--latency-host", default=None, help="Host for network latency measurement (default: same as --host)")
    parser.add_argument("--latency-port", type=int, default=None, help="Port for network latency measurement (default: same as --port)")

    args = parser.parse_args()
    if args.port is None:
        args.port = 5432 if args.db == "dsql" else 3306

    print(f"{'='*60}")
    print(f"  DB Benchmark (Large Scale): {args.db.upper()}")
    print(f"  Host: {args.host}:{args.port}")
    print(f"  Rows: {args.rows:,} per table | Batch: {args.batch_size} | Threads: {args.threads} | SELECT iterations: {args.iterations} | Index: {args.with_index}")
    print(f"{'='*60}")

    # Measure baseline network latency (TCP RTT)
    latency_host = args.latency_host or args.host
    latency_port = args.latency_port or args.port
    print(f"\n[NET] Measuring TCP connection latency to {latency_host}:{latency_port}...")
    net_latencies = measure_network_latency(latency_host, latency_port)
    if net_latencies:
        print(f"  TCP RTT: Avg={statistics.mean(net_latencies):.1f}ms, "
              f"Min={min(net_latencies):.1f}ms, Max={max(net_latencies):.1f}ms "
              f"({len(net_latencies)} probes)")
    else:
        print("  [WARN] Could not measure network latency")

    if not args.skip_insert:
        conn = get_connection(args, autocommit=True)
        setup_tables(conn, args)
        conn.close()

        conn = get_connection(args, autocommit=True)
        print("\n[TEST 1] INSERT Benchmark")
        if args.db in ("tidb", "aurora-mysql"):
            bulk_insert_tidb(conn, args, args.rows)
        else:
            bulk_insert_dsql(conn, args, args.rows)
        conn.close()
    else:
        print("\n[SKIP] INSERT skipped (--skip-insert)")

    # SELECT tests
    conn = get_connection(args, autocommit=True)

    print(f"\n[TEST 2] PK Lookup (x{args.iterations}): SELECT * FROM employees WHERE id = <uuid>")
    pk_latencies, pk_warmup, pk_elapsed = bench_pk_lookup(conn, args, args.iterations)
    print_results(f"PK Lookup ({args.db.upper()}) - {args.rows:,} rows", pk_latencies, pk_elapsed, pk_warmup)

    print(f"\n[TEST 3] JOIN (x{args.iterations}): employees JOIN salaries ON emp_no (NO INDEX)")
    join_latencies, join_warmup, join_elapsed = bench_join_query(conn, args, args.iterations)
    print_results(f"JOIN Query ({args.db.upper()}) - {args.rows:,} rows, no index", join_latencies, join_elapsed, join_warmup)

    if args.with_index:
        # Create covering indexes
        print(f"\n[TEST 4] Index Creation")
        idx_elapsed = create_indexes(conn, args)
        print_results("Index Creation", [idx_elapsed * 1000])

        # Re-run JOIN with indexes
        print(f"\n[TEST 5] JOIN (x{args.iterations}): employees JOIN salaries ON emp_no (WITH INDEX)")
        join_idx_latencies, join_idx_warmup, join_idx_elapsed = bench_join_query(conn, args, args.iterations)
        print_results(f"JOIN Query ({args.db.upper()}) - {args.rows:,} rows, WITH INDEX", join_idx_latencies, join_idx_elapsed, join_idx_warmup)

    conn.close()
    print("\n[DONE] Benchmark complete.")

if __name__ == "__main__":
    main()
