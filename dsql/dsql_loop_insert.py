import psycopg
import boto3
import os, sys
import time
from typing import Optional
import random
from datetime import datetime

class DatabaseRetryStrategy:
    def __init__(self, max_attempts=5, initial_delay=1, max_delay=32):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay

    def retry_connection(self, operation):
        """Connection retry with exponential backoff"""
        delay = self.initial_delay
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                return operation()
            except (psycopg.OperationalError, boto3.exceptions.Boto3Error) as e:
                last_exception = e
                if attempt == self.max_attempts - 1:
                    print(f"Connection failed after {self.max_attempts} attempts.")
                    raise last_exception

                print(f"Connection attempt {attempt + 1} failed. Retrying in {delay} seconds...")
                print(f"Error: {str(e)}")
                time.sleep(delay)
                delay = min(delay * 2, self.max_delay)

    def retry_operation(self, operation):
        """Database operation retry with fixed delay"""
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except psycopg.Error as e:
                if attempt == self.max_attempts - 1:
                    print(f"Operation failed after {self.max_attempts} attempts.")
                    raise e

                print(f"Operation attempt {attempt + 1} failed. Retrying in {self.initial_delay} seconds...")
                print(f"Error: {str(e)}")
                time.sleep(self.initial_delay)

def establish_connection(cluster_endpoint, region, retry_strategy):
    """Establish database connection with retry logic"""
    def connect():
        client = boto3.client("dsql", region_name=region)
        password_token = client.generate_db_connect_admin_auth_token(cluster_endpoint, region)

        params = {
            "dbname": "postgres",
            "user": "admin",
            "host": cluster_endpoint,
            "password": password_token,
            "sslmode": "require"
        }

        return psycopg.connect(**params)

    return retry_strategy.retry_connection(connect)

def main(cluster_endpoint):
    region = 'us-east-1'
    retry_strategy = DatabaseRetryStrategy(
        max_attempts=5,
        initial_delay=1,
        max_delay=32
    )

    try:
        conn = establish_connection(cluster_endpoint, region, retry_strategy)
        conn.set_autocommit(True)
        cur = conn.cursor()

        def create_table():
            # Drop existing table if exists
            cur.execute("DROP TABLE IF EXISTS t_john")

            # Create new table
            cur.execute("""
                CREATE TABLE t_john(
                    id uuid NOT NULL DEFAULT gen_random_uuid(),
                    name varchar(30) NOT NULL,
                    city varchar(80) NOT NULL,
                    telephone varchar(20) DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id))"""
            )

            # Verify table structure
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 't_john'
                ORDER BY ordinal_position;
            """)
            columns = cur.fetchall()
            print("\nTable structure:")
            for col in columns:
                print(f"Column: {col[0]}, Type: {col[1]}")
            print("-" * 50)

        retry_strategy.retry_operation(create_table)

        for i in range(100):
            def insert_and_verify():
                try:
                    # Generate sample data
                    data = (
                        f"John Doe {i}",
                        ["New York", "Tokyo", "London", "Paris", "Sydney"][random.randint(0, 4)],
                        f"555-{random.randint(100,999)}-{random.randint(1000,9999)}"
                    )

                    # Insert with RETURNING
                    cur.execute(
                        "INSERT INTO t_john(name, city, telephone) VALUES(%s, %s, %s) RETURNING *",
                        data
                    )
                    record = cur.fetchone()

                    print(f"\nInserted and verified record {i+1}/100 at {datetime.now()}:")
                    print(f"ID: {record[0]}")
                    print(f"Name: {record[1]}")
                    print(f"City: {record[2]}")
                    print(f"Telephone: {record[3]}")
                    print(f"Created at: {record[4]}")
                    print("-" * 50)

                    return record

                except Exception as e:
                    print(f"Error in insert_and_verify: {str(e)}")
                    raise

            retry_strategy.retry_operation(insert_and_verify)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    try:
        cluster_endpoint = "<put your aurora dsql endpoint>"
        main(cluster_endpoint)
    except Exception as e:
        print(f"Application failed: {str(e)}")
        sys.exit(1)
