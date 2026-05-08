#### Basic Bench Result with TiDB on 2026/05/08

- Batch Size Default : 500
```
$ python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test
============================================================
  DB Benchmark (Large Scale): TIDB
  Host: 127.0.0.1:3306
  Rows: 1,000,000 per table | SELECT iterations: 200
============================================================
[SETUP] Dropping existing tables...
[SETUP] Tables created.

[TEST 1] INSERT Benchmark
[INSERT] Loading 1000000 employees (batch=500)...
  ... 100,000 employees
  ... 200,000 employees
  ... 300,000 employees
  ... 400,000 employees
  ... 500,000 employees
  ... 600,000 employees
  ... 700,000 employees
  ... 800,000 employees
  ... 900,000 employees
  ... 1,000,000 employees
[INSERT] Loading 1000000 salaries (batch=500)...
  ... 100,000 salaries
  ... 200,000 salaries
  ... 300,000 salaries
  ... 400,000 salaries
  ... 500,000 salaries
  ... 600,000 salaries
  ... 700,000 salaries
  ... 800,000 salaries
  ... 900,000 salaries
  ... 1,000,000 salaries
[INSERT] Done. employees=65.1s, salaries=61.3s, total=126.4s
[INSERT] Throughput: 15818 rows/sec

[TEST 2] PK Lookup (x200): SELECT * FROM employees WHERE id = <uuid>

============================================================
  PK Lookup (TIDB) - 1,000,000 rows
============================================================
  Iterations : 200
  Avg        : 1.34 ms
  Median     : 1.33 ms
  P95        : 1.47 ms
  P99        : 1.51 ms
  Min        : 1.20 ms
  Max        : 1.54 ms
  Stddev     : 0.08 ms
============================================================

[TEST 3] JOIN (x200): employees JOIN salaries ON emp_no (NO INDEX)

============================================================
  JOIN Query (TIDB) - 1,000,000 rows, no index
============================================================
  Iterations : 200
  Avg        : 683.71 ms
  Median     : 677.46 ms
  P95        : 791.27 ms
  P99        : 937.99 ms
  Min        : 2.59 ms
  Max        : 1168.15 ms
  Stddev     : 111.36 ms
============================================================

[DONE] Benchmark complete.
```

- Batch Size Changed
```
$ python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --batch-size 1000
============================================================
  DB Benchmark (Large Scale): TIDB
  Host: 127.0.0.1:3306
  Rows: 1,000,000 per table | Batch: 1000 | SELECT iterations: 200
============================================================
[SETUP] Dropping existing tables...
[SETUP] Tables created.

[TEST 1] INSERT Benchmark
[INSERT] Loading 1000000 employees (batch=1000)...
  ... 100,000 employees
  ... 200,000 employees
  ... 300,000 employees
  ... 400,000 employees
  ... 500,000 employees
  ... 600,000 employees
  ... 700,000 employees
  ... 800,000 employees
  ... 900,000 employees
  ... 1,000,000 employees
[INSERT] Loading 1000000 salaries (batch=1000)...
  ... 100,000 salaries
  ... 200,000 salaries
  ... 300,000 salaries
  ... 400,000 salaries
  ... 500,000 salaries
  ... 600,000 salaries
  ... 700,000 salaries
  ... 800,000 salaries
  ... 900,000 salaries
  ... 1,000,000 salaries
[INSERT] Done. employees=52.4s, salaries=47.6s, total=100.1s
[INSERT] Throughput: 19988 rows/sec

[TEST 2] PK Lookup (x200): SELECT * FROM employees WHERE id = <uuid>

============================================================
  PK Lookup (TIDB) - 1,000,000 rows
============================================================
  Iterations : 200
  Avg        : 1.33 ms
  Median     : 1.27 ms
  P95        : 1.48 ms
  P99        : 3.29 ms
  Min        : 1.19 ms
  Max        : 4.35 ms
  Stddev     : 0.31 ms
============================================================

[TEST 3] JOIN (x200): employees JOIN salaries ON emp_no (NO INDEX)

============================================================
  JOIN Query (TIDB) - 1,000,000 rows, no index
============================================================
  Iterations : 200
  Avg        : 663.34 ms
  Median     : 660.96 ms
  P95        : 781.08 ms
  P99        : 894.07 ms
  Min        : 2.54 ms
  Max        : 1139.89 ms
  Stddev     : 118.86 ms
============================================================

[DONE] Benchmark complete.
```

- skip-insert option
```
$ python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --skip-insert
============================================================
  DB Benchmark (Large Scale): TIDB
  Host: 127.0.0.1:3306
  Rows: 1,000,000 per table | SELECT iterations: 200
============================================================

[SKIP] INSERT skipped (--skip-insert)

[TEST 2] PK Lookup (x200): SELECT * FROM employees WHERE id = <uuid>

============================================================
  PK Lookup (TIDB) - 1,000,000 rows
============================================================
  Iterations : 200
  Avg        : 1.14 ms
  Median     : 1.13 ms
  P95        : 1.30 ms
  P99        : 1.38 ms
  Min        : 1.07 ms
  Max        : 1.39 ms
  Stddev     : 0.05 ms
============================================================

[TEST 3] JOIN (x200): employees JOIN salaries ON emp_no (NO INDEX)

============================================================
  JOIN Query (TIDB) - 1,000,000 rows, no index
============================================================
  Iterations : 200
  Avg        : 668.95 ms
  Median     : 674.54 ms
  P95        : 738.95 ms
  P99        : 785.55 ms
  Min        : 2.21 ms
  Max        : 966.17 ms
  Stddev     : 111.42 ms
============================================================

[DONE] Benchmark complete.
```


#### Additional Note : 

- employees and salaries regions are located in the same leader_store_id. (Default: 256MB)

```
$ mysql -h 127.0.0.1 -P 3306 -u admin -p$pass -e "SHOW TABLE employees REGIONS\G" test
mysql: [Warning] Using a password on the command line interface can be insecure.
*************************** 1. row ***************************
             REGION_ID: 67173
             START_KEY: t_730_
               END_KEY: t_732_
             LEADER_ID: 67176
       LEADER_STORE_ID: 40001
                 PEERS: 67174, 67175, 67176
            SCATTERING: 0
         WRITTEN_BYTES: 0
            READ_BYTES: 0
  APPROXIMATE_SIZE(MB): 173
      APPROXIMATE_KEYS: 980828
SCHEDULING_CONSTRAINTS:
      SCHEDULING_STATE:
$ mysql -h 127.0.0.1 -P 3306 -u admin -p$pass -e "SHOW TABLE salaries REGIONS\G" test
mysql: [Warning] Using a password on the command line interface can be insecure.
*************************** 1. row ***************************
             REGION_ID: 67165
             START_KEY: t_732_
               END_KEY: t_281474976710650_5f6980000000000000020131302e39302e312eff3232323a34303030ff0000000000000000f7
             LEADER_ID: 67168
       LEADER_STORE_ID: 40001
                 PEERS: 67166, 67167, 67168
            SCATTERING: 0
         WRITTEN_BYTES: 0
            READ_BYTES: 119652
  APPROXIMATE_SIZE(MB): 182
      APPROXIMATE_KEYS: 1000024
SCHEDULING_CONSTRAINTS:
      SCHEDULING_STATE:
```

- Split Regions from 1 to 10.

PK Lookup is little bit slow down; however, join performance is improved with no-index columns.

##### Might be TiDB's Coprocessor Advantage? (Full Scans)
- When indexes are unavailable, TiDB's Coprocessor pushdown + parallel Region scanning provides a significant advantage. This matters for:
  - Ad-hoc analytical queries
  -  Missing index scenarios
  - Schema evolution periods


```
8.0.11-TiDB-v8.5.3 [test]> SPLIT TABLE employees BETWEEN ("00000000-0000-0000-0000-000000000000") AND ("ffffffff-ffff-ffff-ffff-ffffffffffff") REGIONS 10;
+--------------------+----------------------+
| TOTAL_SPLIT_REGION | SCATTER_FINISH_RATIO |
+--------------------+----------------------+
|                  9 |                    1 |
+--------------------+----------------------+
1 row in set (0.47 sec)

8.0.11-TiDB-v8.5.3 [test]> SPLIT TABLE salaries BETWEEN ("00000000-0000-0000-0000-000000000000") AND ("ffffffff-ffff-ffff-ffff-ffffffffffff") REGIONS 10;
+--------------------+----------------------+
| TOTAL_SPLIT_REGION | SCATTER_FINISH_RATIO |
+--------------------+----------------------+
|                  9 |                    1 |
+--------------------+----------------------+
1 row in set (0.49 sec)

8.0.11-TiDB-v8.5.3 [test]> \q
Bye

$ python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "password" --database test --skip-insert                                 
============================================================
  DB Benchmark (Large Scale): TIDB
  Host: 127.0.0.1:3306
  Rows: 1,000,000 per table | Batch: 500 | SELECT iterations: 200
============================================================

[SKIP] INSERT skipped (--skip-insert)

[TEST 2] PK Lookup (x200): SELECT * FROM employees WHERE id = <uuid>

============================================================
  PK Lookup (TIDB) - 1,000,000 rows
============================================================
  Iterations : 200
  Avg        : 1.79 ms
  Median     : 1.78 ms
  P95        : 1.89 ms
  P99        : 1.94 ms
  Min        : 1.71 ms
  Max        : 2.03 ms
  Stddev     : 0.05 ms
============================================================

[TEST 3] JOIN (x200): employees JOIN salaries ON emp_no (NO INDEX)

============================================================
  JOIN Query (TIDB) - 1,000,000 rows, no index
============================================================
  Iterations : 200
  Avg        : 330.60 ms
  Median     : 328.15 ms
  P95        : 412.96 ms
  P99        : 472.43 ms
  Min        : 3.37 ms
  Max        : 539.18 ms
  Stddev     : 64.69 ms
============================================================

[DONE] Benchmark complete.

```
