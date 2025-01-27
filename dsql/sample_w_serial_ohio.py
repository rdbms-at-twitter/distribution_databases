import psycopg
import boto3
import os, sys
import time
from typing import Optional
import random

def retry_operation(operation, max_attempts=10, delay=1):
    """Retry an operation with exponential backoff"""
    last_exception = None
    for attempt in range(max_attempts):
        try:
            return operation()
        except Exception as e:
            last_exception = e
            if attempt == max_attempts - 1:  # Last attempt
                print(f"Failed after {max_attempts} attempts. Last error: {str(e)}")
                raise last_exception
            print(f"Attempt {attempt + 1} failed. Retrying in {delay} seconds...")
            print(f"Error: {str(e)}")
            time.sleep(delay)

def generate_sample_data(index: int) -> tuple:
    """Generate sample data for insertion"""
    cities = ["New York", "Tokyo", "London", "Paris", "Sydney"]
    return (
        f"John Doe {index}",
        cities[random.randint(0, len(cities)-1)],
        f"555-{random.randint(100,999)}-{random.randint(1000,9999)}"
    )

def establish_connection(cluster_endpoint, region):
    """Establish database connection with retry logic"""
    def connect():
        # Generate a password token
        client = boto3.client("dsql", region_name=region)
        password_token = client.generate_db_connect_admin_auth_token(cluster_endpoint, region)

        # connection parameters
        params = {
            "dbname": "postgres",
            "user": "admin",  # Replace with your username
            "host": cluster_endpoint,
            "password": password_token,
            "sslmode": "require"
        }

        return psycopg.connect(**params)

    return retry_operation(connect)

def main(cluster_endpoint):
    region = 'us-east-2'

    try:
        # Establish connection with retry logic
        conn = establish_connection(cluster_endpoint, region)
        conn.set_autocommit(True)
        cur = conn.cursor()

        # Create table with retry
        def create_table():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sample_serial(
                    id bigint NOT NULL DEFAULT sample_serial_generator(),
                    name varchar(30) NOT NULL,
                    city varchar(80) NOT NULL,
                    telephone varchar(20) DEFAULT NULL,
                    PRIMARY KEY (id))"""
                )

        retry_operation(create_table)

        # Insert 10000 rows with retry
        for i in range(1000):
            data = generate_sample_data(i)

            def insert_data():
                cur.execute(
                    "INSERT INTO sample_serial(name, city, telephone) VALUES(%s, %s, %s)",
                    data
                )
                print(f"Inserted row {i+1}: {data}")
                time.sleep(0.5) # 0.5 second delay.

            retry_operation(insert_data)

        # Verify some data
        def verify_data():
            cur.execute("SELECT COUNT(*) FROM sample_serial")
            count = cur.fetchone()[0]
            print(f"Total records in table: {count}")

            # Sample verification
            cur.execute("SELECT * FROM sample_serial LIMIT 10")
            rows = cur.fetchall()
            print("\nSample records:")
            for row in rows:
                print(row)

        retry_operation(verify_data)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise
    finally:
        # Close connections in finally block
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    try:
        # Replace with your own cluster's endpoint
        cluster_endpoint = "<DSQL Ohio Endpoint>"
        main(cluster_endpoint)
    except Exception as e:
        print(f"Application failed: {str(e)}")
        sys.exit(1)
      
