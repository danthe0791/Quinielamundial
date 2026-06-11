#!/usr/bin/env python3
"""
Migrate data from local SQLite DB to a MySQL database.

Usage:
  1. Set the MYSQL_URL env var with your MySQL connection string:
     $env:MYSQL_URL="mysql+pymysql://user:password@host:3306/dbname"   (PowerShell)
     export MYSQL_URL="mysql+pymysql://user:password@host:3306/dbname"  (Bash)

  2. Run this script:
     python migrate_to_mysql.py

  Or pass URL directly:
     python migrate_to_mysql.py "mysql+pymysql://user:password@host:3306/dbname"

The script:
  - Reads ALL data from local SQLite (data/quiniela.db)
  - Creates tables in MySQL (if not exist)
  - Inserts: users, matches, bets, daily_closures, app_settings
  - Preserves IDs (so foreign keys stay intact)
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
import sqlalchemy as sa

# ─── Source: local SQLite ─────────────────────────────────
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "data", "quiniela.db")
if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
    sys.exit(1)

sqlite_url = f"sqlite:///{SQLITE_PATH}"
sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
SQLiteSession = sessionmaker(bind=sqlite_engine)

# ─── Target: MySQL ───────────────────────────────────────
MYSQL_URL = os.environ.get("MYSQL_URL", sys.argv[1] if len(sys.argv) > 1 else "")
if not MYSQL_URL:
    print("ERROR: Set MYSQL_URL env var or pass as argument.")
    print('Example: python migrate_to_mysql.py "mysql+pymysql://user:pass@host:3306/db"')
    sys.exit(1)

mysql_engine = create_engine(MYSQL_URL, echo=True, pool_pre_ping=True)
MySQLSession = sessionmaker(bind=mysql_engine)

# ─── Tables to migrate (in dependency order) ─────────────
TABLES = [
    "users",
    "matches",
    "bets",
    "daily_closures",
    "app_settings",
]


def get_columns(engine, table_name):
    """Get column names (excluding auto-generated) for a table."""
    insp = inspect(engine)
    cols = insp.get_columns(table_name)
    return [c["name"] for c in cols]


def migrate():
    print(f"\n{'='*60}")
    print(f"Migrating: SQLite → MySQL")
    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {MYSQL_URL.split('@')[1] if '@' in MYSQL_URL else MYSQL_URL}")
    print(f"{'='*60}\n")

    sqlite_session = SQLiteSession()
    mysql_session = MySQLSession()

    try:
        # 1. Create all tables if not exist
        from app.database import Base
        Base.metadata.create_all(bind=mysql_engine)
        print("✓ Tables created (if not existed)\n")

        # 2. Clear target tables (optional, comment out to keep existing data)
        # for table_name in reversed(TABLES):
        #     mysql_session.execute(text(f"DELETE FROM {table_name}"))
        # mysql_session.commit()

        # 3. Copy data table by table
        for table_name in TABLES:
            src_cols = get_columns(sqlite_engine, table_name)
            dst_cols = get_columns(mysql_engine, table_name)

            # Intersection: only copy columns that exist in both
            common_cols = [c for c in src_cols if c in dst_cols]
            col_str = ", ".join(common_cols)
            placeholder_str = ", ".join([f":{c}" for c in common_cols])

            # Read from SQLite
            rows = sqlite_session.execute(
                text(f"SELECT {col_str} FROM {table_name} ORDER BY id")
            ).fetchall()

            if not rows:
                print(f"  {table_name}: 0 rows (empty)")
                continue

            # Insert into MySQL
            inserted = 0
            for row in rows:
                row_dict = dict(row._mapping)
                # Check if already exists by id
                existing = mysql_session.execute(
                    text(f"SELECT 1 FROM {table_name} WHERE id = :id"),
                    {"id": row_dict["id"]},
                ).first()
                if existing:
                    continue  # skip existing

                mysql_session.execute(
                    text(f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholder_str})"),
                    row_dict,
                )
                inserted += 1

            mysql_session.commit()
            print(f"  {table_name}: {inserted} rows migrated")

        print(f"\n{'='*60}")
        print("Migration complete! ✅")
        print(f"{'='*60}")

    except Exception as e:
        mysql_session.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        sqlite_session.close()
        mysql_session.close()


if __name__ == "__main__":
    migrate()
