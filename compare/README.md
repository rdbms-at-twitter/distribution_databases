# Three Engine Benchmark Suite

TiDB / Aurora MySQL / Aurora DSQL のパフォーマンス比較ベンチマークツール群。

## スクリプト一覧

| ファイル | INSERT | SELECT | Pool | 用途 |
|---------|--------|--------|------|------|
| `bench_db.py` | 1T | 1T/MT | ❌ | 基本ベンチマーク（シングルスレッドINSERT + マルチスレッドSELECT） |
| `bench_db_inc_insert.py` | **MT** | 1T/MT | ❌ | マルチスレッドINSERT版（Pool不使用） |
| `connection_pool/bench_db_pool.py` | 1T | 1T/MT | ✅ | Connection Pool版（SELECTのみPool利用） |
| `connection_pool/bench_db_pool_inc_insert.py` | **MT** | 1T/MT | ✅ | Connection Pool + マルチスレッドINSERT版 |
| `load_data.py` | **MT** | — | ❌ | データロード専用（INSERT後に `bench_db.py --skip-insert` で使用） |

- 1T = シングルスレッド、MT = マルチスレッド（`--threads` で指定）

## 必要モジュール

### 全スクリプト共通
```bash
pip install pymysql psycopg boto3
```

### Connection Pool版（`connection_pool/` 配下）追加
```bash
pip install psycopg_pool DBUtils
```

## 使い方

### 基本ベンチマーク（bench_db.py）

```bash
# TiDB — INSERT + SELECT（シングルスレッド）
python3 bench_db.py --db tidb --host 127.0.0.1 --port 3306 \
  --user admin --password "password" --database test --rows 1000000

# Aurora MySQL
python3 bench_db.py --db aurora-mysql --host mycluster.cluster-xxx.us-east-1.rds.amazonaws.com \
  --port 3306 --user admin --password "password" --database test --rows 1000000

# Aurora DSQL
python3 bench_db.py --db dsql --host xxx.dsql.us-east-1.on.aws \
  --user admin --database postgres --aws-region us-east-1 --rows 1000000

# SELECTのみ（データ投入済み）、8スレッド
python3 bench_db.py --db dsql --host ... --skip-insert --threads 8
```

### マルチスレッドINSERT（bench_db_inc_insert.py）

```bash
# 8スレッド並列INSERT + 8スレッドSELECT
python3 bench_db_inc_insert.py --db dsql --host ... \
  --user admin --database postgres --aws-region us-east-1 --threads 8
```

### Connection Pool版（bench_db_pool.py）

```bash
# 8スレッド、プールサイズ8
python3 bench_db_pool.py --db dsql --host ... \
  --user admin --database postgres --aws-region us-east-1 \
  --skip-insert --threads 8 --pool-size 8
```

### Connection Pool + マルチスレッドINSERT（bench_db_pool_inc_insert.py）

```bash
# INSERT/SELECT共に8スレッド、プールサイズ8
python3 bench_db_pool_inc_insert.py --db dsql --host ... \
  --user admin --database postgres --aws-region us-east-1 \
  --threads 8 --pool-size 8
```

### データロード専用（load_data.py）

```bash
# 16スレッドで高速データロード
python3 load_data.py --db dsql --host ... \
  --user admin --database postgres --aws-region us-east-1 \
  --rows 1000000 --threads 16

# その後SELECTテストのみ実行
python3 bench_db.py --db dsql --host ... --skip-insert --threads 8
```

## 共通オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--db` | (必須) | `tidb`, `aurora-mysql`, `dsql` |
| `--host` | (必須) | DBホスト |
| `--port` | 3306/5432 | ポート（DSQLは5432、他は3306） |
| `--user` | root | DBユーザー |
| `--password` | "" | パスワード（DSQL不要） |
| `--database` | test | データベース名 |
| `--rows` | 1,000,000 | テーブルあたりの行数 |
| `--batch-size` | 500 | INSERT文あたりの行数 |
| `--iterations` | 200 | SELECTテストの実行回数 |
| `--threads` | 1 | 並列スレッド数 |
| `--skip-insert` | false | INSERT/テーブル作成をスキップ |
| `--aws-region` | us-east-1 | AWSリージョン（DSQL用） |
| `--pool-size` | 8 | Connection Poolサイズ（Pool版のみ） |

## テスト内容

1. **INSERT**: employees + salaries テーブルに各N行をmulti-value INSERTで投入
2. **PK Lookup**: `SELECT * FROM employees WHERE id = <uuid>` をiterations回実行
3. **JOIN**: `SELECT ... FROM employees e JOIN salaries s ON e.emp_no = s.emp_no WHERE e.emp_no = ?` をiterations回実行


## 注意事項

- DSQL は `--password` 不要（IAM認証を使用）
- DSQL のConnection Pool版は IAMトークンを1週間有効で生成（`ExpiresIn=604800`）
- DSQL のセッション有効期限は最大1時間（Pool内接続のリフレッシュが必要）
- TiDB (HAProxy構成) ではConnection Pool使用時にJOIN性能が悪化する事象あり（原因未特定）
- Aurora MySQL db.r8g.large (2vCPU) では8スレッド以上でvCPU飽和が発生

