#!/usr/bin/env python3
"""
Fast Data Loader (Multi-threaded)
=================================
Usage:
  # TiDB (8 threads):
  python3 load_data.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --rows 1000000 --threads 8

  # DSQL (16 threads):
  python3 load_data.py --db dsql --host jqohrppfncdfsa.dsql.us-east-1.on.aws --user admin --database postgres --aws-region us-east-1 --rows 1000000 --threads 16

Then run bench_db.py with --skip-insert to test SELECT only.
"""

import argparse
import time
import uuid
import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_connection(args):
    if args.db == "tidb":
        import pymysql
        return pymysql.connect(
            host=args.host, port=args.port,
            user=args.user, password=args.password,
            database=args.database, charset="utf8mb4",
            autocommit=True
        )
    elif args.db == "dsql":
        import boto3, psycopg
        session = boto3.Session(region_name=args.aws_region)
        client = session.client("dsql")
        token = client.generate_db_connect_admin_auth_token(args.host, args.aws_region)
        return psycopg.connect(
            host=args.host, port=args.port, user=args.user,
            password=token, dbname=args.database, sslmode="require",
            autocommit=False
        )

def setup_tables(args):
    conn = get_connection(args)
    if args.db == "dsql":
        conn.autocommit = True
    cur = conn.cursor()
    print("[SETUP] Dropping and creating tables...")
    if args.db == "tidb":
        cur.execute("DROP TABLE IF EXISTS salaries")
        cur.execute("DROP TABLE IF EXISTS employees")
        cur.execute("""CREATE TABLE employees (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            emp_no INT NOT NULL,
            first_name VARCHAR(50) NOT NULL,
            last_name VARCHAR(50) NOT NULL,
            birth_date DATE, hire_date DATE)""")
        cur.execute("""CREATE TABLE salaries (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            emp_no INT NOT NULL,
            salary INT NOT NULL,
            from_date DATE, to_date DATE)""")
    else:
        cur.execute("DROP TABLE IF EXISTS salaries")
        cur.execute("DROP TABLE IF EXISTS employees")
        cur.execute("""CREATE TABLE employees (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            emp_no INT NOT NULL,
            first_name VARCHAR(50) NOT NULL,
            last_name VARCHAR(50) NOT NULL,
            birth_date DATE, hire_date DATE)""")
        cur.execute("""CREATE TABLE salaries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            emp_no INT NOT NULL,
            salary INT NOT NULL,
            from_date DATE, to_date DATE)""")
    cur.close()
    conn.close()
    if args.db == "dsql":
        print("[SETUP] Waiting 5s for schema propagation...")
        time.sleep(5)
    print("[SETUP] Done.")

FIRST_NAMES = ["James","Mary","John","Patricia","Robert","Jennifer","Michael","Linda","David","Elizabeth",
               "William","Barbara","Richard","Susan","Joseph","Jessica","Thomas","Sarah","Christopher","Karen"]
LAST_NAMES = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
              "Wilson","Anderson","Taylor","Thomas","Moore","Jackson","Martin","Lee","Thompson","White"]

def insert_chunk_tidb(args, start_idx, end_idx, table):
    """Insert a chunk of rows into TiDB using multi-value INSERT."""
    conn = get_connection(args)
    cur = conn.cursor()
    batch = 500
    for offset in range(start_idx, end_idx, batch):
        batch_end = min(offset + batch, end_idx)
        if table == "employees":
            rows = []
            for i in range(offset, batch_end):
                rows.append((str(uuid.uuid4()), 10001+i, FIRST_NAMES[i%20], LAST_NAMES[i%20],
                    datetime.date(1960+(i%35), (i%12)+1, (i%28)+1),
                    datetime.date(2010+(i%15), (i%12)+1, (i%28)+1)))
            ph = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(rows))
            flat = [v for r in rows for v in r]
            cur.execute(f"INSERT INTO employees (id,emp_no,first_name,last_name,birth_date,hire_date) VALUES {ph}", flat)
        else:
            rows = []
            for i in range(offset, batch_end):
                rows.append((str(uuid.uuid4()), 10001+i, 30000+(i*13)%120000,
                    datetime.date(2020,1,1), datetime.date(2024,12,31)))
            ph = ",".join(["(%s,%s,%s,%s,%s)"] * len(rows))
            flat = [v for r in rows for v in r]
            cur.execute(f"INSERT INTO salaries (id,emp_no,salary,from_date,to_date) VALUES {ph}", flat)
    cur.close()
    conn.close()
    return end_idx - start_idx

def insert_chunk_dsql(args, start_idx, end_idx, table):
    """Insert a chunk of rows into DSQL using multi-value INSERT."""
    conn = get_connection(args)
    cur = conn.cursor()
    batch = 500
    for offset in range(start_idx, end_idx, batch):
        batch_end = min(offset + batch, end_idx)
        retries = 0
        while retries < 5:
            try:
                if table == "employees":
                    rows = []
                    params = []
                    for i in range(offset, batch_end):
                        rows.append("(%s,%s,%s,%s,%s,%s)")
                        params.extend([str(uuid.uuid4()), 10001+i, FIRST_NAMES[i%20], LAST_NAMES[i%20],
                            datetime.date(1960+(i%35), (i%12)+1, (i%28)+1),
                            datetime.date(2010+(i%15), (i%12)+1, (i%28)+1)])
                    sql = "INSERT INTO employees (id,emp_no,first_name,last_name,birth_date,hire_date) VALUES " + ",".join(rows)
                    cur.execute(sql, params)
                else:
                    rows = []
                    params = []
                    for i in range(offset, batch_end):
                        rows.append("(%s,%s,%s,%s,%s)")
                        params.extend([str(uuid.uuid4()), 10001+i, 30000+(i*13)%120000,
                            datetime.date(2020,1,1), datetime.date(2024,12,31)])
                    sql = "INSERT INTO salaries (id,emp_no,salary,from_date,to_date) VALUES " + ",".join(rows)
                    cur.execute(sql, params)
                conn.commit()
                break
            except Exception as e:
                conn.rollback()
                retries += 1
                if retries >= 5:
                    raise
                time.sleep(0.5 * retries)
    cur.close()
    conn.close()
    return end_idx - start_idx

def parallel_load(args, table, num_rows, num_threads):
    chunk_size = num_rows // num_threads
    futures = []

    insert_fn = insert_chunk_tidb if args.db == "tidb" else insert_chunk_dsql

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        for t in range(num_threads):
            start_idx = t * chunk_size
            end_idx = start_idx + chunk_size if t < num_threads - 1 else num_rows
            futures.append(executor.submit(insert_fn, args, start_idx, end_idx, table))

        done = 0
        for f in as_completed(futures):
            done += f.result()
            print(f"  ... {done:,}/{num_rows:,} {table}")

def main():
    parser = argparse.ArgumentParser(description="Fast parallel data loader")
    parser.add_argument("--db", required=True, choices=["tidb", "dsql"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--database", default="test")
    parser.add_argument("--rows", type=int, default=1000000)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--skip-setup", action="store_true", help="Skip DROP/CREATE tables")

    args = parser.parse_args()
    if args.port is None:
        args.port = 3306 if args.db == "tidb" else 5432

    print(f"{'='*60}")
    print(f"  Parallel Data Loader: {args.db.upper()}")
    print(f"  Host: {args.host}:{args.port}")
    print(f"  Rows: {args.rows:,} per table | Threads: {args.threads}")
    print(f"{'='*60}")

    if not args.skip_setup:
        setup_tables(args)

    # Load employees
    print(f"\n[LOAD] employees ({args.rows:,} rows, {args.threads} threads)...")
    start = time.perf_counter()
    parallel_load(args, "employees", args.rows, args.threads)
    emp_time = time.perf_counter() - start
    print(f"  Done: {emp_time:.1f}s ({args.rows/emp_time:.0f} rows/sec)")

    # Load salaries
    print(f"\n[LOAD] salaries ({args.rows:,} rows, {args.threads} threads)...")
    start = time.perf_counter()
    parallel_load(args, "salaries", args.rows, args.threads)
    sal_time = time.perf_counter() - start
    print(f"  Done: {sal_time:.1f}s ({args.rows/sal_time:.0f} rows/sec)")

    total = emp_time + sal_time
    print(f"\n{'='*60}")
    print(f"  TOTAL: {args.rows*2:,} rows in {total:.1f}s")
    print(f"  Throughput: {args.rows*2/total:.0f} rows/sec")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
