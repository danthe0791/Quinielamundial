from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os
import sys

# ─── DATABASE_URL env var ────────────────────────────────
# SQLite (local dev):  sqlite:///data/quiniela.db
# MySQL (production):  mysql+pymysql://user:pass@host:3306/dbname
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Production: use explicit DATABASE_URL (MySQL, etc.)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    # Hide password in logs
    safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    print(f"[DB] Usando DATABASE_URL → ...@{safe_url}", flush=True)
else:
    # Local dev: SQLite
    DB_PATH = os.environ.get("DATABASE_PATH", None)
    if DB_PATH is None:
        DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(DB_DIR, exist_ok=True)
        DB_PATH = os.path.join(DB_DIR, "quiniela.db")
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    print(f"[DB] Usando SQLite → {DB_PATH}", flush=True)

# ─── Engine ──────────────────────────────────────────────
is_sqlite = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

if is_sqlite:
    _connect_args = {"check_same_thread": False}
    _engine_kwargs = {}
else:
    # MySQL: enable SSL, auto-reconnect
    _connect_args = {
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }
    _engine_kwargs = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 300,
    }

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
    pool_pre_ping=True,
    **_engine_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        # Verify connection
        db = SessionLocal()
        from sqlalchemy import text
        result = db.execute(text("SELECT COUNT(*) FROM users"))
        user_count = result.scalar()
        db.close()
        print(f"[DB] Conexión OK — {user_count} usuarios existentes", flush=True)
    except Exception as e:
        print(f"[DB] ERROR al conectar: {e}", flush=True)
        import traceback
        traceback.print_exc()
