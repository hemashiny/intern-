"""
Database connector for ML prediction service.
Handles MySQL connections and data fetching.
"""

import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'jewelry_sales_predictor'),
    'port': int(os.getenv('DB_PORT', 3306)),
}

connection_pool = pooling.MySQLConnectionPool(
    pool_name='jewelry_pool',
    pool_size=5,
    **DB_CONFIG
)


def get_connection():
    """Get a connection from the pool."""
    return connection_pool.get_connection()


def execute_query(query, params=None, fetch=True):
    """Execute a SQL query and return results."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params or ())
        if fetch:
            return cursor.fetchall()
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def execute_many(query, params_list):
    """Execute a SQL query with multiple parameter sets."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()
