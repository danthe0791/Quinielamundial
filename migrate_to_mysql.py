#!/usr/bin/env python3
"""
Migrate data from local SQLite DB to a MySQL database.

Usage:
  1. Set MYSQL_URL env var:
     $env:MYSQL_URL="mysql+pymysql://user:password@host:3306/dbname"   (PowerShell)

  2. Run:
     python migrate_to_mysql.py

  Or pass URL directly:
     python migrate_to_mysql.py "mysql+pymysql://user:password@host:3306/dbname"

The script:
  - Creates MySQL tables via raw SQL (more reliable than SQLAlchemy inspect)
  - Copies ALL data from SQLite (data/quiniela.db)
  - Preserves IDs so foreign keys stay intact
"""
import sys
import os
import sqlite3
import pymysql
from urllib.parse import urlparse

# ─── Source: local SQLite ─────────────────────────────────
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "data", "quiniela.db")
if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
    sys.exit(1)

# ─── Target: MySQL URL ───────────────────────────────────
MYSQL_URL = os.environ.get("MYSQL_URL", sys.argv[1] if len(sys.argv) > 1 else "")
if not MYSQL_URL:
    print("ERROR: Set MYSQL_URL env var or pass as argument.")
    print('Example: python migrate_to_mysql.py "mysql+pymysql://user:pass@host:3306/db"')
    sys.exit(1)

# Parse URL: mysql+pymysql://user:pass@host:3306/dbname
parsed = urlparse(MYSQL_URL)
MYSQL_HOST = parsed.hostname
MYSQL_PORT = parsed.port or 3306
MYSQL_USER = parsed.username
MYSQL_PASS = parsed.password
MYSQL_DB = parsed.path.lstrip("/")

print(f"Conectando a MySQL: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB} como {MYSQL_USER}")

# ─── MySQL CREATE TABLE statements ───────────────────────
CREATE_SQL = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        username VARCHAR(50) NOT NULL UNIQUE,
        password_hash VARCHAR(200) NOT NULL,
        display_name VARCHAR(100) NOT NULL,
        is_admin TINYINT(1) DEFAULT 0,
        created_at DATETIME
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        openligadb_match_id INTEGER UNIQUE,
        home_team VARCHAR(100) NOT NULL,
        away_team VARCHAR(100) NOT NULL,
        home_short VARCHAR(10),
        away_short VARCHAR(10),
        home_icon VARCHAR(500),
        away_icon VARCHAR(500),
        match_date DATETIME NOT NULL,
        match_date_utc DATETIME NOT NULL,
        group_name VARCHAR(100),
        group_order INTEGER,
        stage VARCHAR(50) DEFAULT 'Grupos',
        home_score INTEGER,
        away_score INTEGER,
        home_cards INTEGER,
        away_cards INTEGER,
        home_corners INTEGER,
        away_corners INTEGER,
        cards_line FLOAT DEFAULT 3.5,
        corners_line FLOAT DEFAULT 7.5,
        is_friendly TINYINT(1) DEFAULT 0,
        is_finished TINYINT(1) DEFAULT 0,
        last_updated DATETIME
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        user_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        home_score_pred INTEGER,
        away_score_pred INTEGER,
        cards_over TINYINT(1),
        corners_over TINYINT(1),
        points_result INTEGER DEFAULT 0,
        points_score INTEGER DEFAULT 0,
        points_cards INTEGER DEFAULT 0,
        points_corners INTEGER DEFAULT 0,
        points_total INTEGER DEFAULT 0,
        scored_on DATE,
        created_at DATETIME,
        updated_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        UNIQUE KEY uq_user_match (user_id, match_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS daily_closures (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        closure_date DATE NOT NULL UNIQUE,
        closed_by INTEGER,
        matches_count INTEGER DEFAULT 0,
        created_at DATETIME,
        FOREIGN KEY (closed_by) REFERENCES users(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS app_settings (
        id INTEGER PRIMARY KEY AUTO_INCREMENT,
        `key` VARCHAR(50) NOT NULL UNIQUE,
        `value` TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

# ─── Tables to migrate (dependency order) ────────────────
TABLES = ["users", "matches", "bets", "daily_closures", "app_settings"]


def migrate():
    print(f"\n{'='*60}")
    print(f"Migrating: SQLite → MySQL")
    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}")
    print(f"{'='*60}\n")

    # Connect
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    mysql_conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASS,
        database=MYSQL_DB, charset="utf8mb4",
    )
    cur = mysql_conn.cursor()

    try:
        # 1. Disable FK checks temporarily (to avoid order issues)
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")

        # 2. Create tables
        for sql in CREATE_SQL:
            cur.execute(sql)
        mysql_conn.commit()
        print("✓ Tables created (if not existed)\n")

        # 3. Migrate data table by table
        for table_name in TABLES:
            # Get columns from SQLite
            sqlite_cur = sqlite_conn.cursor()
            sqlite_cur.execute(f"PRAGMA table_info({table_name})")
            src_cols = [r[1] for r in sqlite_cur.fetchall()]

            # Get columns from MySQL
            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            dst_cols = [r[0] for r in cur.fetchall()]

            # Intersection
            common_cols = [c for c in src_cols if c in dst_cols]
            if not common_cols:
                print(f"  {table_name}: no common columns, skipping")
                continue

            col_str = ", ".join([f"`{c}`" for c in common_cols])
            placeholder_str = ", ".join(["%s"] * len(common_cols))

            # Read from SQLite
            sqlite_cur.execute(f"SELECT {', '.join(common_cols)} FROM {table_name} ORDER BY id")
            rows = sqlite_cur.fetchall()

            if not rows:
                print(f"  {table_name}: 0 rows (empty)")
                continue

            # Insert into MySQL
            inserted = 0
            skipped = 0
            for row in rows:
                row_dict = {common_cols[i]: row[i] for i in range(len(common_cols))}
                row_id = row_dict.get("id")

                # Check if already exists
                if row_id:
                    cur.execute(f"SELECT 1 FROM `{table_name}` WHERE id = %s", (row_id,))
                    if cur.fetchone():
                        skipped += 1
                        continue

                values = tuple(row_dict[c] for c in common_cols)
                cur.execute(
                    f"INSERT INTO `{table_name}` ({col_str}) VALUES ({placeholder_str})",
                    values,
                )
                inserted += 1

            mysql_conn.commit()
            msg = f"  {table_name}: {inserted} rows migrated"
            if skipped:
                msg += f" ({skipped} skipped, already exist)"
            print(msg)

        # 4. Re-enable FK checks
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")

        print(f"\n{'='*60}")
        print("Migration complete! ✅")
        print(f"{'='*60}")

    except Exception as e:
        mysql_conn.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        sqlite_conn.close()
        cur.close()
        mysql_conn.close()


if __name__ == "__main__":
    migrate()
