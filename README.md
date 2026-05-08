# distribution_databases
kb for distribution databases


### Aurora DSQL

https://docs.aws.amazon.com/ja_jp/aurora-dsql/

https://brooker.co.za/blog/2024/12/03/aurora-dsql.html

```
Amazon Aurora DSQL is a serverless distributed SQL database with virtually unlimited scale, high availability, 
and zero infrastructure management. Aurora DSQL offers fast distributed SQL reads and writes with optimal price performance. 
```


### TiDB

https://docs.pingcap.com/ja/tidbcloud/basic-sql-operations/

### MySQL Cluster

https://www.mysql.com/jp/products/cluster/features.html

---

### Simple Bench (bench_db.py):

#### Pre-Require 

``` pip3 install pymysql psycopg boto3 ``` 

#### Create Table and Data and Benchmark with PK Lookup and JOIN Condition 

- DSQL
```
python3 bench_db.py --db dsql --host <cluster-id>.dsql.us-east-1.on.aws --user admin --database postgres --aws-region us-east-1
```

- TiDB
```
python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "<password>" --database test
```


##### Option : If you need more data (load_data.py): 

- DSQL
```
python3 load_data.py --db dsql --host <cluster-id>.dsql.us-east-1.on.aws --user admin --database postgres --aws-region us-east-1 --rows 1000000 --threads 8
```

- TiDB
```
python3 load_data.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "<password>" --database test --rows 1000000 --threads 8
```

##### NOTE : IF you use load_data.py, it will create table and data. Please use --skip-insert option for pk and join performance check.

- DSQL
```
python3 bench_db.py --db dsql --host <cluster-id>.dsql.us-east-1.on.aws --user admin --database postgres --aws-region us-east-1 --skip-insert
```

- TiDB
```
python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 --user admin --password "<password>" --database test --skip-insert
```

#### Option for additional Index : 

- DSQL
```
  CREATE INDEX ASYNC idx_employees_emp_no ON employees (emp_no);
  CREATE INDEX ASYNC idx_salaries_emp_no ON salaries (emp_no);
```

- TiDB
```
  CREATE INDEX idx_employees_emp_no ON employees (emp_no);
  CREATE INDEX idx_salaries_emp_no ON salaries (emp_no);
```


#### More Details and options:

https://github.com/rdbms-at-twitter/distribution_databases/tree/main/compare
