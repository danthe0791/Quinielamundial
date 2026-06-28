from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Date, Text, Float
from sqlalchemy.orm import relationship
from datetime import datetime, date

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    display_name = Column(String(100), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    bets = relationship("Bet", back_populates="user", cascade="all, delete-orphan")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    openligadb_match_id = Column(Integer, unique=True, nullable=True)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    home_short = Column(String(10))
    away_short = Column(String(10))
    home_icon = Column(String(500))
    away_icon = Column(String(500))
    match_date = Column(DateTime, nullable=False)
    match_date_utc = Column(DateTime, nullable=False)
    group_name = Column(String(100))
    group_order = Column(Integer)
    stage = Column(String(50), default="Grupos")
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    home_cards = Column(Integer, nullable=True)   # Tarjetas local (real)
    away_cards = Column(Integer, nullable=True)   # Tarjetas visitante (real)
    home_corners = Column(Integer, nullable=True)  # Corners local (real)
    away_corners = Column(Integer, nullable=True)  # Corners visitante (real)
    cards_line = Column(Float, default=3.5)        # Línea Over/Under tarjetas totales
    corners_line = Column(Float, default=7.5)      # Línea Over/Under corners totales
    is_friendly = Column(Boolean, default=False)   # Partido amistoso (pruebas, no puntúa)
    is_finished = Column(Boolean, default=False)
    had_penalties = Column(Boolean, nullable=True) # ¿Hubo penales? (fase KO)
    winner_is_home = Column(Boolean, nullable=True) # True=Local avanza, False=Visita (KO, manual si empate)
    last_updated = Column(DateTime)

    bets = relationship("Bet", back_populates="match", cascade="all, delete-orphan")


class Bet(Base):
    __tablename__ = "bets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    home_score_pred = Column(Integer, nullable=True)
    away_score_pred = Column(Integer, nullable=True)
    cards_over = Column(Boolean, nullable=True)    # True=Over, False=Under
    corners_over = Column(Boolean, nullable=True)  # True=Over, False=Under
    both_score = Column(Boolean, nullable=True)    # True=Sí, False=No (ambos anotan)
    advances_home = Column(Boolean, nullable=True) # True=Local avanza, False=Visita avanza (fase KO)
    penalties_yes = Column(Boolean, nullable=True) # True=Sí habrá penales, False=No (fase KO)
    points_result = Column(Integer, default=0)
    points_score = Column(Integer, default=0)
    points_cards = Column(Integer, default=0)
    points_corners = Column(Integer, default=0)
    points_both_score = Column(Integer, default=0)
    points_advances = Column(Integer, default=0)
    points_penalties = Column(Integer, default=0)
    points_total = Column(Integer, default=0)
    archived = Column(Boolean, default=False)     # Archived bets won't be recalculated
    scored_on = Column(Date, nullable=True)     # Date when points were awarded
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="bets")
    match = relationship("Match", back_populates="bets")

    class Config:
        unique_together = ("user_id", "match_id")


class DailyClosure(Base):
    __tablename__ = "daily_closures"

    id = Column(Integer, primary_key=True, index=True)
    closure_date = Column(Date, nullable=False, unique=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    matches_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    class Config:
        unique_together = ("closure_date",)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(Text, nullable=False)


class StageHistory(Base):
    __tablename__ = "stage_history"

    id = Column(Integer, primary_key=True, index=True)
    stage_name = Column(String(100), nullable=False)
    closed_at = Column(DateTime, default=datetime.utcnow)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    standings_json = Column(Text, nullable=False)  # JSON blob of standings
