import psycopg
import boto3
import os, sys

def main(cluster_endpoint):
    region = 'us-east-1'

    # Generate a password token
    client = boto3.client("dsql", region_name=region)
    password_token = client.generate_db_connect_admin_auth_token(cluster_endpoint, region)

    # connection parameters
    dbname = "dbname=postgres"
    user = "user=admin"
    host = f'host={cluster_endpoint}'
    sslmode = "sslmode=require"
    password = f'password={password_token}'

    # Make a connection to the cluster
    conn = psycopg.connect('%s %s %s %s %s' % (dbname, user, host, sslmode, password))

    conn.set_autocommit(True)

    cur = conn.cursor()

    cur.execute(b"""
        CREATE TABLE IF NOT EXISTS owner(
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            name varchar(30) NOT NULL,
            city varchar(80) NOT NULL,
            telephone varchar(20) DEFAULT NULL,
            PRIMARY KEY (id))"""
        )

    # Insert some rows
    cur.execute("INSERT INTO owner(name, city, telephone) VALUES('John Doe', 'Anytown', '555-555-1999')")

    cur.execute("SELECT * FROM owner WHERE name='John Doe'")
    row = cur.fetchone()
    print(row)

    # Verify that the result we got is what we inserted before
    # assert row[0] != None
    # assert row[1] == "John Doe"
    # assert row[2] == "Anytown"
    # assert row[3] == "555-555-1999"

    # Placing this cleanup the table after the example. If we run the example
    # again we do not have to worry about data inserted by previous runs
    cur.execute("DELETE FROM owner where name = 'John Doe'")

if __name__ == "__main__":
    # Replace with your own cluster's endpoint
    cluster_endpoint = "<put your Aurora DSQL endpint>"
    main(cluster_endpoint)
