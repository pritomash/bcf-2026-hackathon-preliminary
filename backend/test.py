import psycopg2
from db_reflector import fetch_dynamic_schema
import os

if __name__ == "__main__":
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5433),
        dbname=os.getenv("DB_NAME", "bcf_db"),
        user=os.getenv("DB_USER", "bcf"),
        password=os.getenv("DB_PASSWORD", "bcf2026"),
        connect_timeout=5
    )
    schema = fetch_dynamic_schema(conn)
    print(schema)
    conn.close()
