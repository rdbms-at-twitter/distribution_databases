### Sample Insert for Aurora DSQL


- Reference document:

https://docs.aws.amazon.com/ja_jp/aurora-dsql/latest/userguide/SECTION_program-with-psycopg3.html


#### Prepare Environment

- Install uv

https://docs.astral.sh/uv/

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```
uv init dsql -p 3.13
cd dsql
uv add boto3 "psycopg[binary]>=3"
```



#### Run Script


```
[ec2-user@ip-172-31-8-156 dsql]$ uv run dsql_loop_insert.py

Table structure:
Column: id, Type: uuid
Column: name, Type: character varying
Column: city, Type: character varying
Column: telephone, Type: character varying
Column: created_at, Type: timestamp without time zone
--------------------------------------------------

Inserted and verified record 1/100 at 2025-01-20 23:31:23.222109:
ID: 4e4bd8e6-3751-4e13-bf24-038e83dbb18d
Name: John Doe 0
City: London
Telephone: 555-902-5618
Created at: 2025-01-20 23:31:23.174012
--------------------------------------------------

Inserted and verified record 2/100 at 2025-01-20 23:31:23.246825:
ID: b2bae954-1203-4437-b218-ffae8fff3e8b
Name: John Doe 1
City: New York
Telephone: 555-971-3039
Created at: 2025-01-20 23:31:23.221360
--------------------------------------------------

```



