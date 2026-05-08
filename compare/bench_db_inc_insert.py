#!/usr/bin/env python3
"""
TiDB vs Aurora DSQL vs Aurora MySQL Performance Benchmark
(Multi-threaded INSERT, No Connection Pool)
=========================================================
Each thread creates its own connection (no pool).

Usage:
  # DSQL - parallel INSERT with 8 threads:
  python3 bench_db_inc_insert.py --db dsql --host ... --user admin --database postgres --aws-region us-east-1 --threads 8

  # TiDB:
  python3 bench_db_inc_insert.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --threads 8

  # Aurora MySQL:
  python3 bench_db_inc_insert.py --db aurora-mysql --host ... --port 3306 --user admin --password "password" --database test --threads 8

Requirements:
  pip3 install pymysql psycopg boto3
"""

import argparse
import time
import statistics
import sys
import uuid
import random
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BATCH_SIZE = 500


def get_connection(args, autocommit=True):
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
        token = client.generate_db_connect_admin_auth_token(args.host, args.aws_region)
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


def parallel_insert(args, num_rows):
    """Multi-threaded INSERT — each thread creates its own connection (no pool)."""
    batch = args.batch_size
    threads = args.threads

    chunk_size = num_rows // threads
    ranges = []
    for t in range(threads):
        start_i = t * chunk_size
        end_i = start_i + chunk_size if t < threads - 1 else num_rows
        ranges.append((start_i, end_i))

    def insert_worker(table, start_i, end_i, gen_func, cols, col_count):
        conn = get_connection(args, autocommit=(args.db != "dsql"))
        cur = conn.cursor()
        if args.db == "dsql":
            conn.autocommit = False
        placeholders_single = "(" + ",".join(["%s"] * col_count) + ")"
        inserted = 0
        for offset in range(start_i, end_i, batch):
            end = min(offset + batch, end_i)
            rows = [gen_func(i) for i in range(offset, end)]
            placeholders = ",".join([placeholders_single] * len(rows))
            flat = [v for row in rows for v in row]
            cur.execute(f"INSERT INTO {table} {cols} VALUES {placeholders}", flat)
            if args.db == "dsql":
                conn.commit()
            inserted += len(rows)
        cur.close()
        conn.close()
        return inserted

    # INSERT employees
    print(f"[INSERT] Loading {num_rows} employees (batch={batch}, threads={threads})...")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(insert_worker, "employees", s, e,
                                   generate_employee_row,
                                   "(id,emp_no,first_name,last_name,birth_date,hire_date)", 6)
                   for s, e in ranges]
        total_emp = sum(f.result() for f in as_completed(futures))
    emp_time = time.perf_counter() - start
    print(f"  ... {total_emp:,} employees in {emp_time:.1f}s")

    # INSERT salaries
    print(f"[INSERT] Loading {num_rows} salaries (batch={batch}, threads={threads})...")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(insert_worker, "salaries", s, e,
                                   generate_salary_row,
                                   "(id,emp_no,salary,from_date,to_date)", 5)
                   for s, e in ranges]
        total_sal = sum(f.result() for f in as_completed(futures))
    sal_time = time.perf_counter() - start
    print(f"  ... {total_sal:,} salaries in {sal_time:.1f}s")

    total = emp_time + sal_time
    print(f"[INSERT] Done. employees={emp_time:.1f}s, salaries={sal_time:.1f}s, total={total:.1f}s")
    print(f"[INSERT] Throughput: {num_rows*2/total:.0f} rows/sec")
    return total


def bench_pk_lookup(conn, args, iterations=200):
    """Benchmark: SELECT * FROM employees WHERE id = <pk>"""
    cur = conn.cursor()
    cur.execute("SELECT id FROM employees ORDER BY id LIMIT %d" % (iterations * 10))
    all_pks = [row[0] for row in cur.fetchall()]
    pks = random.sample(all_pks, min(iterations, len(all_pks)))
    cur.close()

    threads = args.threads
    if threads == 1:
        cur = conn.cursor()
        for pk in pks[:10]:
            cur.execute("SELECT * FROM employees WHERE id = %s", (str(pk),))
            cur.fetchall()
        latencies = []
        for pk in pks:
            start = time.perf_counter()
            cur.execute("SELECT * FROM employees WHERE id = %s", (str(pk),))
            cur.fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        cur.close()
    else:
        # NOTE: No warmup in multi-thread mode. Each worker's first query includes
        # connection establishment overhead (IAM token gen + SSL handshake for DSQL).
        chunks = [pks[i::threads] for i in range(threads)]
        def worker(chunk):
            c = get_connection(args, autocommit=True)
            cur = c.cursor()
            lats = []
            for pk in chunk:
                start = time.perf_counter()
                cur.execute("SELECT * FROM employees WHERE id = %s", (str(pk),))
                cur.fetchall()
                elapsed = (time.perf_counter() - start) * 1000
                lats.append(elapsed)
            cur.close()
            c.close()
            return lats
        latencies = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, chunk) for chunk in chunks]
            for f in as_completed(futures):
                latencies.extend(f.result())
    return latencies


def bench_join_query(conn, args, iterations=200):
    """Benchmark: JOIN on emp_no"""
    cur = conn.cursor()
    cur.execute("SELECT emp_no FROM employees ORDER BY emp_no LIMIT %d" % (iterations * 10))
    all_enos = [row[0] for row in cur.fetchall()]
    emp_nos = random.sample(all_enos, min(iterations, len(all_enos)))
    cur.close()

    threads = args.threads
    if threads == 1:
        cur = conn.cursor()
        for eno in emp_nos[:5]:
            cur.execute("""
                SELECT e.emp_no, e.first_name, e.last_name, s.salary
                FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
                WHERE e.emp_no = %s
            """, (eno,))
            cur.fetchall()
        latencies = []
        for eno in emp_nos:
            start = time.perf_counter()
            cur.execute("""
                SELECT e.emp_no, e.first_name, e.last_name, s.salary
                FROM employees e JOIN salaries s ON e.emp_no = s.emp_no
                WHERE e.emp_no = %s
            """, (eno,))
            cur.fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        cur.close()
    else:
        # NOTE: No warmup in multi-thread mode (same as PK lookup above).
        chunks = [emp_nos[i::threads] for i in range(threads)]
        def worker(chunk):
            c = get_connection(args, autocommit=True)
            cur = c.cursor()
            lats = []
            for eno in chunk:
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
            return lats
        latencies = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, chunk) for chunk in chunks]
            for f in as_completed(futures):
                latencies.extend(f.result())
    return latencies


def print_results(name, latencies, elapsed_sec=None):
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
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="DB Benchmark - Multi-threaded INSERT (No Pool)")
    parser.add_argument("--db", required=True, choices=["tidb", "dsql", "aurora-mysql"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--database", default="test")
    parser.add_argument("--rows", type=int, default=1000000, help="Rows per table (default: 1M)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Rows per INSERT statement (default: 500)")
    parser.add_argument("--iterations", type=int, default=200, help="SELECT test iterations")
    parser.add_argument("--threads", type=int, default=1, help="Concurrent threads (default: 1)")
    parser.add_argument("--skip-insert", action="store_true", help="Skip table setup and INSERT")
    parser.add_argument("--aws-region", default="us-east-1")

    args = parser.parse_args()
    if args.port is None:
        args.port = 5432 if args.db == "dsql" else 3306

    print(f"{'='*60}")
    print(f"  DB Benchmark (Parallel INSERT, No Pool): {args.db.upper()}")
    print(f"  Host: {args.host}:{args.port}")
    print(f"  Rows: {args.rows:,} per table | Batch: {args.batch_size} | Threads: {args.threads} | Iterations: {args.iterations}")
    print(f"{'='*60}")

    if not args.skip_insert:
        conn = get_connection(args, autocommit=True)
        setup_tables(conn, args)
        conn.close()

        print(f"\n[TEST 1] Parallel INSERT Benchmark ({args.threads} threads, no pool)")
        parallel_insert(args, args.rows)
    else:
        print("\n[SKIP] INSERT skipped (--skip-insert)")

    # SELECT tests
    conn = get_connection(args, autocommit=True)

    print(f"\n[TEST 2] PK Lookup (x{args.iterations}): SELECT * FROM employees WHERE id = <uuid>")
    t0 = time.perf_counter()
    pk_latencies = bench_pk_lookup(conn, args, args.iterations)
    pk_elapsed = time.perf_counter() - t0
    print_results(f"PK Lookup ({args.db.upper()}) - {args.rows:,} rows", pk_latencies, pk_elapsed)

    print(f"\n[TEST 3] JOIN (x{args.iterations}): employees JOIN salaries ON emp_no")
    t0 = time.perf_counter()
    join_latencies = bench_join_query(conn, args, args.iterations)
    join_elapsed = time.perf_counter() - t0
    print_results(f"JOIN Query ({args.db.upper()}) - {args.rows:,} rows", join_latencies, join_elapsed)

    conn.close()
    print("\n[DONE] Benchmark complete.")


if __name__ == "__main__":
    main()
