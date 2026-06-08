import hashlib
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

from .database import init_db, get_db, SessionLocal
from .models import User, Match, Bet, DailyClosure, AppSettings
from .openligadb import sync_matches_from_api
from .score_calculator import (
    calculate_bet_points,
    recalculate_all_bets,
    get_user_standings,
    get_user_stats,
    close_daily_results,
    get_settings_value,
    set_settings_value,
)

# ─── Timezone ─────────────────────────────────────────────
CST_OFFSET = -6  # Central America = UTC-6

def utc_to_cst(dt: datetime) -> Optional[datetime]:
    if dt is None:
        return None
    return dt + timedelta(hours=CST_OFFSET)

def format_cst(dt: datetime, fmt: str = "%d/%m %H:%M") -> str:
    cst = utc_to_cst(dt)
    if cst is None:
        return ""
    return cst.strftime(fmt)

# ─── App Setup ───────────────────────────────────────────
app = FastAPI(title="Quiniela Mundial 2026")

static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

templates.env.globals["now"] = lambda: datetime.utcnow()
templates.env.globals["utc_to_cst"] = utc_to_cst
templates.env.globals["format_cst"] = format_cst

sessions: dict[str, dict] = {}
SESSION_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"

def verify_password(password: str, stored: str) -> bool:
    salt, pwd_hash = stored.split(":", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == pwd_hash

def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    sessions[token] = {"user_id": user_id, "expires": datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRE_HOURS)}
    return token

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get("session_token")
    if not token or token not in sessions:
        return None
    session = sessions[token]
    if session["expires"] < datetime.now(timezone.utc):
        del sessions[token]
        return None
    return db.query(User).filter(User.id == session["user_id"]).first()


# ─── Background Auto-Sync ────────────────────────────────
last_sync_at: Optional[datetime] = None
_sync_task = None

async def background_sync_loop():
    """Sync matches from API every 5 minutes."""
    global last_sync_at
    await asyncio.sleep(30)  # Wait 30s after startup
    while True:
        try:
            db = SessionLocal()
            count = await sync_matches_from_api(db)
            recalculate_all_bets(db)
            last_sync_at = datetime.utcnow()
            if count > 0:
                print(f"[AutoSync] {count} nuevos partidos sincronizados")
            db.close()
        except Exception as e:
            print(f"[AutoSync] Error: {e}")
        await asyncio.sleep(300)  # Every 5 minutes

@app.on_event("startup")
async def on_startup():
    global _sync_task
    init_db()
    try:
        db = SessionLocal()
        await sync_matches_from_api(db)
        recalculate_all_bets(db)
        if not db.query(AppSettings).filter(AppSettings.key == "min_participants").first():
            db.add(AppSettings(key="min_participants", value="1"))
            db.commit()
        db.close()
    except Exception as e:
        print(f"Startup sync error: {e}")
    # Start background sync loop
    _sync_task = asyncio.create_task(background_sync_loop())


# ─── Auth Routes ─────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "user": None})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": "Usuario o contraseña incorrectos"})
    token = create_session(user.id)
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="session_token", value=token, httponly=True, max_age=SESSION_EXPIRE_HOURS * 3600)
    return resp

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request, "user": None})

@app.post("/register")
def register(request: Request, username: str = Form(...), display_name: str = Form(...),
             password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db)):
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Las contraseñas no coinciden"})
    if len(password) < 4:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Mínimo 4 caracteres"})
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "El usuario ya existe"})
    user_count = db.query(User).count()
    if user_count >= 10:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Ya hay 10 usuarios registrados"})
    user = User(username=username, display_name=display_name, password_hash=hash_password(password), is_admin=(user_count == 0))
    db.add(user); db.commit()
    token = create_session(user.id)
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="session_token", value=token, httponly=True, max_age=SESSION_EXPIRE_HOURS * 3600)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("session_token")
    return resp


# ─── Dashboard ───────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    group_order = request.query_params.get("group", None)
    matches_query = db.query(Match).order_by(Match.group_order, Match.match_date_utc)
    if group_order:
        matches_query = matches_query.filter(Match.group_order == int(group_order))
    matches = matches_query.all()

    match_ids = [m.id for m in matches]
    user_bets = db.query(Bet).filter(Bet.user_id == user.id, Bet.match_id.in_(match_ids)).all()
    bets_dict = {b.match_id: b for b in user_bets}

    # All bets grouped by match for visibility
    all_bets_q = db.query(Bet, User).join(User).filter(Bet.match_id.in_(match_ids)).all()
    bets_by_match = {}
    for bet, usr in all_bets_q:
        bets_by_match.setdefault(bet.match_id, []).append({"bet": bet, "user": usr})

    groups = db.query(Match.group_name, Match.group_order, Match.stage).distinct().order_by(Match.group_order).all()
    user_stats = get_user_stats(db, user.id)
    min_part = int(get_settings_value(db, "min_participants", "1"))

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "matches": matches,
        "bets": bets_dict, "all_bets": bets_by_match,
        "groups": groups, "current_group": int(group_order) if group_order else None,
        "stats": user_stats, "min_participants": min_part,
    })


# ─── Place / Update Bet ──────────────────────────────────
@app.post("/api/bet")
def place_bet(
    request: Request,
    match_id: int = Form(...),
    home_score: int = Form(...),
    away_score: int = Form(...),
    cards_over: Optional[str] = Form(None),
    corners_over: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return JSONResponse({"error": "Partido no encontrado"}, status_code=404)

    if match.match_date_utc and datetime.utcnow() > match.match_date_utc:
        return JSONResponse({"error": "El partido ya comenzó, no puedes modificar tu apuesta"}, status_code=400)

    if match.is_finished:
        return JSONResponse({"error": "El partido ya finalizó"}, status_code=400)

    if home_score < 0 or away_score < 0 or home_score > 99 or away_score > 99:
        return JSONResponse({"error": "Marcador inválido"}, status_code=400)

    def parse_bool(v):
        if v is None or v == "":
            return None
        return v.lower() in ("true", "1", "over", "si")

    existing_bet = db.query(Bet).filter(Bet.user_id == user.id, Bet.match_id == match_id).first()

    if existing_bet:
        existing_bet.home_score_pred = home_score
        existing_bet.away_score_pred = away_score
        existing_bet.cards_over = parse_bool(cards_over)
        existing_bet.corners_over = parse_bool(corners_over)
        existing_bet.updated_at = datetime.utcnow()
    else:
        bet = Bet(
            user_id=user.id, match_id=match_id,
            home_score_pred=home_score, away_score_pred=away_score,
            cards_over=parse_bool(cards_over), corners_over=parse_bool(corners_over),
        )
        db.add(bet)

    db.commit()
    return JSONResponse({"success": True, "message": "Apuesta guardada"})


# ─── Match Details (who bet) ─────────────────────────────
@app.get("/api/match-bets/{match_id}")
def match_bets_api(match_id: int, db: Session = Depends(get_db)):
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return JSONResponse({"error": "No encontrado"}, status_code=404)

    bets = db.query(Bet, User).join(User).filter(Bet.match_id == match_id).all()
    data = []
    for bet, usr in bets:
        data.append({
            "user": usr.display_name,
            "home_score": bet.home_score_pred,
            "away_score": bet.away_score_pred,
            "cards": "Over" if bet.cards_over is True else ("Under" if bet.cards_over is False else "-"),
            "corners": "Over" if bet.corners_over is True else ("Under" if bet.corners_over is False else "-"),
            "points": bet.points_total,
        })
    return JSONResponse({
        "match": f"{match.home_team} vs {match.away_team}",
        "home_icon": match.home_icon, "away_icon": match.away_icon,
        "home_score": match.home_score, "away_score": match.away_score,
        "cards_line": match.cards_line,
        "corners_line": match.corners_line,
        "bets": data,
    })


# ─── API Live update ─────────────────────────────────────
@app.get("/api/live-matches")
def api_live_matches(db: Session = Depends(get_db)):
    matches = db.query(Match).order_by(Match.match_date_utc).all()
    return JSONResponse({
        "last_sync": last_sync_at.isoformat() if last_sync_at else None,
        "matches": [{
            "id": m.id, "openligadb_id": m.openligadb_match_id,
            "home_team": m.home_team, "away_team": m.away_team,
            "home_score": m.home_score, "away_score": m.away_score,
            "home_cards": m.home_cards, "away_cards": m.away_cards,
            "home_corners": m.home_corners, "away_corners": m.away_corners,
            "is_finished": m.is_finished,
            "match_date_utc": m.match_date_utc.isoformat() if m.match_date_utc else None,
        } for m in matches],
    })


# ─── Daily Results ───────────────────────────────────────
@app.get("/daily-results", response_class=HTMLResponse)
def daily_results_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    closures = db.query(DailyClosure).order_by(DailyClosure.closure_date.desc()).all()
    standings = get_user_standings(db)
    today_closed = any(c.closure_date == datetime.utcnow().date() for c in closures)

    return templates.TemplateResponse("daily_results.html", {
        "request": request, "user": user, "standings": standings,
        "closures": closures, "today_closed": today_closed,
    })

@app.post("/api/close-day")
def close_day(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    result = close_daily_results(db, user.id)
    return JSONResponse(result)


# ─── Standings ───────────────────────────────────────────
@app.get("/standings", response_class=HTMLResponse)
def standings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    standings = get_user_standings(db)
    return templates.TemplateResponse("standings.html", {"request": request, "user": user, "standings": standings})

@app.get("/api/standings")
def api_standings(db: Session = Depends(get_db)):
    return JSONResponse(get_user_standings(db))


# ─── Admin Routes ────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/dashboard", status_code=302)

    users = db.query(User).all()
    match_count = db.query(Match).count()
    finished = db.query(Match).filter(Match.is_finished == True).count()
    total_bets = db.query(Bet).count()
    min_part = get_settings_value(db, "min_participants", "1")
    closures = db.query(DailyClosure).order_by(DailyClosure.closure_date.desc()).limit(10).all()
    matches = db.query(Match).order_by(Match.match_date_utc).all()

    return templates.TemplateResponse("admin.html", {
        "request": request, "user": user, "users": users,
        "match_count": match_count, "finished_count": finished,
        "total_bets": total_bets, "min_participants": min_part,
        "closures": closures, "matches": matches,
    })

@app.post("/admin/sync-matches")
def admin_sync_matches(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    import asyncio
    try:
        count = asyncio.run(sync_matches_from_api(db))
        return JSONResponse({"success": True, "count": count, "message": f"Sincronizados {count} partidos"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/admin/recalculate")
def admin_recalculate(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    recalculate_all_bets(db)
    return JSONResponse({"success": True, "message": "Puntos recalculados"})

@app.post("/admin/set-min-participants")
def admin_set_min(request: Request, value: int = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    set_settings_value(db, "min_participants", str(max(0, min(10, value))))
    return JSONResponse({"success": True, "message": "Configuración actualizada"})

@app.post("/admin/update-match-stats")
def admin_update_match(
    request: Request, match_id: int = Form(...),
    home_score: Optional[int] = Form(None),
    away_score: Optional[int] = Form(None),
    home_cards: Optional[int] = Form(None),
    away_cards: Optional[int] = Form(None),
    home_corners: Optional[int] = Form(None),
    away_corners: Optional[int] = Form(None),
    cards_line: Optional[str] = Form(None),
    corners_line: Optional[str] = Form(None),
    is_finished: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return JSONResponse({"error": "No encontrado"}, status_code=404)

    def to_float(v):
        if v is None or v == "":
            return None
        try: return float(v)
        except: return None

    if home_score is not None: match.home_score = home_score
    if away_score is not None: match.away_score = away_score
    if home_cards is not None: match.home_cards = home_cards
    if away_cards is not None: match.away_cards = away_cards
    if home_corners is not None: match.home_corners = home_corners
    if away_corners is not None: match.away_corners = away_corners
    cl = to_float(cards_line)
    if cl is not None: match.cards_line = cl
    cl = to_float(corners_line)
    if cl is not None: match.corners_line = cl
    match.is_finished = is_finished
    match.last_updated = datetime.utcnow()
    db.commit()

    bets = db.query(Bet).filter(Bet.match_id == match.id).all()
    for bet in bets:
        pts = calculate_bet_points(match, bet)
        bet.points_result = pts["points_result"]
        bet.points_score = pts["points_score"]
        bet.points_cards = pts["points_cards"]
        bet.points_corners = pts["points_corners"]
        bet.points_total = pts["points_total"]
    db.commit()

    return JSONResponse({"success": True, "message": "Estadísticas actualizadas"})


# ─── Backup / Restore ────────────────────────────────────
@app.get("/admin/backup")
def admin_backup(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "No autorizado"}, status_code=401)

    from fastapi.responses import FileResponse
    from .database import DB_PATH

    if not os.path.exists(DB_PATH):
        return JSONResponse({"error": "Base de datos no encontrada"}, status_code=404)

    return FileResponse(
        DB_PATH,
        media_type="application/octet-stream",
        filename=f"quiniela-backup-{datetime.utcnow().strftime('%Y%m%d')}.db",
    )
