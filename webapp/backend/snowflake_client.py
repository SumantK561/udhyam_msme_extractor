"""Thread-safe Snowflake connection pool for the public MSME search API.

Uses a fixed-size pool of connections against the read-only
UDYAM_PUBLIC_READER role (see snowflake/part 4.sql) on a dedicated
XSMALL warehouse, isolated from the ETL pipeline's UDYAM_WH.
"""

from __future__ import annotations

import logging
import os
import queue

import snowflake.connector

logger = logging.getLogger("udyam.webapp")

POOL_SIZE = int(os.getenv("UDYAM_WEB_POOL_SIZE", "4"))

_pool: "queue.Queue" = queue.Queue(maxsize=POOL_SIZE)
for _ in range(POOL_SIZE):
    _pool.put(None)  # lazy slots -- real connections opened on first use


def _connect():
    logger.info("Opening new Snowflake connection (public reader)")
    return snowflake.connector.connect(
        account=os.environ["UDYAM_WEB_SNOWFLAKE_ACCOUNT"],
        user=os.environ["UDYAM_WEB_SNOWFLAKE_USER"],
        password=os.environ["UDYAM_WEB_SNOWFLAKE_PASSWORD"],
        role=os.environ["UDYAM_WEB_SNOWFLAKE_ROLE"],
        warehouse=os.environ["UDYAM_WEB_SNOWFLAKE_WAREHOUSE"],
        database=os.environ["UDYAM_WEB_SNOWFLAKE_DATABASE"],
        schema=os.environ["UDYAM_WEB_SNOWFLAKE_SCHEMA"],
        client_session_keep_alive=True,
        login_timeout=10,
        network_timeout=20,
    )


def _is_alive(conn) -> bool:
    try:
        conn.cursor().execute("SELECT 1")
        return True
    except Exception:
        return False


class PooledConnection:
    """Context manager: borrows a live connection, returns it to the pool on exit."""

    def __enter__(self):
        conn = _pool.get(timeout=15)
        if conn is None or conn.is_closed() or not _is_alive(conn):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            conn = _connect()
        self._conn = conn
        return conn

    def __exit__(self, exc_type, exc, tb):
        _pool.put(self._conn)
        return False


def get_connection() -> PooledConnection:
    return PooledConnection()
