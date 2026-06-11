from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os

# ─── DATABASE_URL env var ────────────────────────────────
# SQLite (local dev):  sqlite:///data/quiniela.db
# MySQL (production):  mysql+pymysql://user:pass@host:3306/dbname
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    # Production: use explicit DATABASE_URL (MySQL, etc.)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
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

# ─── Engine ──────────────────────────────────────────────
_connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=_connect_args, echo=False,
    pool_pre_ping=True,
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
    Base.metadata.create_all(bind=engine)
