"""
Database connectivity module for Microsoft SQL Server (MSSQL).
Uses SQLAlchemy and pyodbc with ODBC Driver 18 for SQL Server.
Supports Windows Authentication and SQL Server Authentication.
Enables fast_executemany for high-throughput batch operations.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, Engine
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def create_mssql_engine() -> Engine:
    """
    Create and configure the SQLAlchemy engine for Microsoft SQL Server.
    Supports Windows Authentication (Trusted_Connection=yes) or SQL User/Password auth.
    Configures fast_executemany=True for high-performance bulk inserts.
    """
    server = os.getenv("DB_SERVER", "localhost")
    database = os.getenv("DB_NAME", "EntityResolutionDB")
    driver = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    trust_cert = os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")

    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if db_user and db_password:
        auth_segment = f"UID={db_user};PWD={db_password};"
    else:
        auth_segment = "Trusted_Connection=yes;"

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"{auth_segment}"
        "Encrypt=yes;"
        f"TrustServerCertificate={trust_cert};"
    )

    connection_url = URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": connection_string}
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
        fast_executemany=True
    )


# Primary engine instance
engine = create_mssql_engine()


def init_db(target_engine: Optional[Engine] = None):
    """
    Execute database/schema.sql batches to ensure all tables, constraints,
    and indexes are aligned in Microsoft SQL Server.
    Each batch is executed and committed independently.
    """
    eng = target_engine or engine
    schema_path = BASE_DIR / "database" / "schema.sql"

    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at: {schema_path}")

    content = schema_path.read_text(encoding="utf-8")
    batches = [b.strip() for b in re.split(r"^\s*GO\s*$", content, flags=re.MULTILINE) if b.strip()]

    with eng.connect() as conn:
        for batch in batches:
            clean_batch = batch.strip()
            if not clean_batch:
                continue
            # Skip standalone USE database statements if connected directly to target database
            if re.match(r"^\s*USE\s+", clean_batch, re.IGNORECASE):
                continue
            with conn.begin():
                conn.execute(text(clean_batch))

    logger.info("Microsoft SQL Server schema verified and aligned from schema.sql.")


def ensure_schema_aligned(target_engine: Optional[Engine] = None):
    """
    Auto-detect and align schema:
    Checks if required columns (source_file, source_file_hash) and tables exist.
    If missing, runs init_db to upgrade the database non-destructively.
    """
    eng = target_engine or engine
    try:
        with eng.connect() as conn:
            missing_source_file = conn.execute(
                text("SELECT COL_LENGTH('dbo.pipeline_runs', 'source_file')")
            ).scalar() is None

            missing_hash = conn.execute(
                text("SELECT COL_LENGTH('dbo.pipeline_runs', 'source_file_hash')")
            ).scalar() is None

            missing_val_table = conn.execute(
                text("SELECT OBJECT_ID('dbo.record_validation_results', 'U')")
            ).scalar() is None

        if missing_source_file or missing_hash or missing_val_table:
            logger.info("Database schema requires alignment. Applying updates from schema.sql...")
            init_db(eng)
            logger.info("Schema alignment complete.")
    except Exception as e:
        logger.warning("Auto-alignment check encountered: %s. Executing full init_db...", e)
        init_db(eng)


def test_connection(target_engine: Optional[Engine] = None):
    """Test and display active Microsoft SQL Server connection details."""
    eng = target_engine or engine
    with eng.connect() as connection:
        result = connection.execute(
            text("""
                SELECT
                    DB_NAME() AS database_name,
                    @@SERVERNAME AS server_name,
                    @@VERSION AS server_version
            """)
        ).fetchone()

        print("Connection successful!")
        print(f"Database: {result[0]}")
        print(f"Server:   {result[1]}")
        print(f"Version:  {result[2]}")


if __name__ == "__main__":
    test_connection()
