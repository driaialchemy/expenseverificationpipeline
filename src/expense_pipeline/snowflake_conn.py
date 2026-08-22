"""Snowflake connection management."""

import os
from typing import Optional

import snowflake.connector


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    """
    Create and return a Snowflake connection.

    Reads credentials from environment variables only (never hardcoded):
    - SNOWFLAKE_ACCOUNT
    - SNOWFLAKE_USER
    - SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH
    - SNOWFLAKE_WAREHOUSE
    - SNOWFLAKE_DATABASE
    - SNOWFLAKE_SCHEMA
    - SNOWFLAKE_ROLE
    """
    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE")
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema = os.getenv("SNOWFLAKE_SCHEMA")
    role = os.getenv("SNOWFLAKE_ROLE")

    if not all([account, user, warehouse, database, schema, role]):
        raise ValueError(
            "Missing required Snowflake environment variables. "
            "See .env.example for required vars."
        )

    auth_kwargs = {}
    password = os.getenv("SNOWFLAKE_PASSWORD")
    private_key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")

    if password:
        auth_kwargs["password"] = password
    elif private_key_path:
        with open(private_key_path, "rb") as f:
            auth_kwargs["private_key"] = f.read()
    else:
        raise ValueError(
            "Must provide either SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH"
        )

    conn = snowflake.connector.connect(
        account=account,
        user=user,
        warehouse=warehouse,
        database=database,
        schema=schema,
        role=role,
        **auth_kwargs,
    )

    return conn


def get_snowpark_session():
    """
    Get a Snowpark session for use in Streamlit-in-Snowflake context.

    Returns the built-in Snowpark session if running in Streamlit-in-Snowflake,
    otherwise None.
    """
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        return None
