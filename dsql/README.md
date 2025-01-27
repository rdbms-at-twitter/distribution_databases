### Sample Insert for Aurora DSQL


- Reference document:

https://docs.aws.amazon.com/ja_jp/aurora-dsql/latest/userguide/SECTION_program-with-psycopg3.html


#### Prepare Environment

- Install uv

```
[ec2-user@ip-172-31-8-156 dsql]$ uvx pycowsay 'hello world!'

  ------------
< hello world! >
  ------------
   \   ^__^
    \  (oo)\_______
       (__)\       )\/\
           ||----w |
           ||     ||

[ec2-user@ip-172-31-8-156 dsql]$
```

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

- dsql_loop_insert.py

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


- sample_w_retry.py

```
[ec2-user@ip-172-31-8-156 dsql]$ uv run sample_w_retry.py
Inserted row 1: ('John Doe 0', 'Sydney', '555-378-4845')
Inserted row 2: ('John Doe 1', 'Tokyo', '555-238-1502')
Inserted row 3: ('John Doe 2', 'Sydney', '555-302-1648')
Inserted row 4: ('John Doe 3', 'Sydney', '555-591-9521')
Inserted row 5: ('John Doe 4', 'Sydney', '555-584-8596')
Inserted row 6: ('John Doe 5', 'London', '555-220-9422')
Inserted row 7: ('John Doe 6', 'New York', '555-612-5747')
Inserted row 8: ('John Doe 7', 'Tokyo', '555-895-7045')
Inserted row 9: ('John Doe 8', 'Tokyo', '555-965-8332')
Inserted row 10: ('John Doe 9', 'Tokyo', '555-868-5182')
Total records in table: 814

Sample records:
(UUID('00359fda-a15d-49ac-9ae6-faa7a854e86b'), 'John Doe 95', 'New York', '555-360-7800')
(UUID('00569984-3706-4ab3-a666-89bf074f0134'), 'John Doe 12', 'Sydney', '555-378-6178')
(UUID('00755056-fc0b-4548-a51c-1b2797b75c5a'), 'John Doe 85', 'Paris', '555-386-4893')
(UUID('009d0a08-ef97-4c2d-80d3-d6d297160cdf'), 'John Doe 65', 'New York', '555-334-7627')
(UUID('00f90e47-e8bd-49f2-a2ed-8c33c22a35d3'), 'John Doe 17', 'London', '555-707-9441')
(UUID('011139fc-cf31-4498-a10b-f7d9d8934294'), 'John Doe 92', 'London', '555-899-3309')
(UUID('01b1ffa4-da44-4a02-ad6f-59f30a67e5a6'), 'John Doe 34', 'Sydney', '555-340-3718')
(UUID('0233f548-4479-4998-ac3c-44fe4cae3ce5'), 'John Doe 15', 'Tokyo', '555-402-8077')
(UUID('025078dd-2bd3-4bba-83fd-5abba4e59921'), 'John Doe 24', 'London', '555-610-5542')
(UUID('0282651c-3b99-4997-84f1-c5a1e7d8fdb8'), 'John Doe 89', 'Sydney', '555-443-3581')
[ec2-user@ip-172-31-8-156 dsql]$

```


- Table Definition
  
![image](https://github.com/user-attachments/assets/f5a1d8ea-a6b7-400c-a93d-6b0c7ef7e7e4)


- Multi Region Act/Act Cluster
  
![image](https://github.com/user-attachments/assets/d4515fc1-5bbf-4014-857a-8605e7999b0a)



### Additional Sample with Serial Numbers

- sample_w_serial.py

Create a function before running this script.

```
create function sample_serial_generator() RETURNS bigint AS $$ select coalesce(max(id)+1,1)::bigint from sample_serial $$ LANGUAGE sql;
```


- Output

```
[ec2-user@ip-172-31-8-156 dsql]$ uv run sample_w_serial.py
Inserted row 1: ('John Doe 0', 'Paris', '555-889-3058')
Inserted row 2: ('John Doe 1', 'New York', '555-517-2824')
Inserted row 3: ('John Doe 2', 'Paris', '555-650-7147')
Inserted row 4: ('John Doe 3', 'New York', '555-452-7337')
Inserted row 5: ('John Doe 4', 'Tokyo', '555-455-7189')
Inserted row 6: ('John Doe 5', 'London', '555-855-8284')
Inserted row 7: ('John Doe 6', 'London', '555-687-5898')
Inserted row 8: ('John Doe 7', 'London', '555-804-1127')
Inserted row 9: ('John Doe 8', 'Tokyo', '555-307-8149')
Inserted row 10: ('John Doe 9', 'Sydney', '555-166-3292')
Inserted row 11: ('John Doe 10', 'New York', '555-900-4665')
Inserted row 12: ('John Doe 11', 'New York', '555-652-4544')
Inserted row 13: ('John Doe 12', 'Paris', '555-375-8174')
```

![image](https://github.com/user-attachments/assets/5c8fb4e3-2c10-4462-b01d-35fbd78be16c)


### Inserting simultaneously from Virginia and Ohio


![image](https://github.com/user-attachments/assets/65f77c0d-b593-4e2f-906a-a027ddba0f95)

