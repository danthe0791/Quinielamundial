"""
Scoring system for the World Cup betting pool.

Rules:
- Correct result (win/draw/lose): 2 points
- Correct exact score: +3 additional points (5 total)
- Correct cards Over/Under: 1 point
- Correct corners Over/Under: 1 point
"""

from sqlalchemy.orm import Session
from datetime import date

from .models import Match, Bet, User, DailyClosure, AppSettings


def calculate_bet_points(match: Match, bet: Bet) -> dict:
    """Calculate all points for a single bet. Returns dict of points."""
    result = {
        "points_result": 0,
        "points_score": 0,
        "points_cards": 0,
        "points_corners": 0,
        "points_total": 0,
    }

    if not match.is_finished or match.home_score is None or match.away_score is None:
        return result

    if bet.home_score_pred is None or bet.away_score_pred is None:
        return result

    # --- SCORE RESULT ---
    if match.home_score > match.away_score:
        actual_result = "home"
    elif match.home_score < match.away_score:
        actual_result = "away"
    else:
        actual_result = "draw"

    if bet.home_score_pred > bet.away_score_pred:
        pred_result = "home"
    elif bet.home_score_pred < bet.away_score_pred:
        pred_result = "away"
    else:
        pred_result = "draw"

    if actual_result == pred_result:
        result["points_result"] = 2
        if bet.home_score_pred == match.home_score and bet.away_score_pred == match.away_score:
            result["points_score"] = 3

    # --- CARDS (Over/Under) ---
    if match.home_cards is not None and match.away_cards is not None and bet.cards_over is not None:
        total_cards = match.home_cards + match.away_cards
        line = match.cards_line or 3.5
        actual_over = total_cards > line
        if bet.cards_over == actual_over:
            result["points_cards"] = 1

    # --- CORNERS (Over/Under) ---
    if match.home_corners is not None and match.away_corners is not None and bet.corners_over is not None:
        total_corners = match.home_corners + match.away_corners
        line = match.corners_line or 7.5
        actual_over = total_corners > line
        if bet.corners_over == actual_over:
            result["points_corners"] = 1

    result["points_total"] = (
        result["points_result"] + result["points_score"] +
        result["points_cards"] + result["points_corners"]
    )
    return result


def recalculate_all_bets(db: Session):
    """Recalculate points for all bets based on finished matches."""
    finished_matches = db.query(Match).filter(
        Match.is_finished == True
    ).all()

    match_ids = [m.id for m in finished_matches]
    bets = db.query(Bet).filter(Bet.match_id.in_(match_ids)).all()

    for bet in bets:
        match = next((m for m in finished_matches if m.id == bet.match_id), None)
        if match:
            pts = calculate_bet_points(match, bet)
            bet.points_result = pts["points_result"]
            bet.points_score = pts["points_score"]
            bet.points_cards = pts["points_cards"]
            bet.points_corners = pts["points_corners"]
            bet.points_total = pts["points_total"]

    db.commit()


def get_user_standings(db: Session) -> list[dict]:
    """Get standings for all users sorted by total points."""
    recalculate_all_bets(db)

    users = db.query(User).order_by(User.id).all()
    standings = []

    for user in users:
        total_points = sum(
            (bet.points_result or 0) + (bet.points_score or 0) +
            (bet.points_cards or 0) + (bet.points_corners or 0)
            for bet in user.bets
        )

        exact_scores = sum(1 for bet in user.bets if bet.points_score > 0)
        correct_results = sum(1 for bet in user.bets if bet.points_result > 0)
        correct_cards = sum(1 for bet in user.bets if bet.points_cards > 0)
        correct_corners = sum(1 for bet in user.bets if bet.points_corners > 0)
        total_bets = sum(1 for bet in user.bets if bet.match.is_finished)

        standings.append({
            "user_id": user.id,
            "username": user.display_name,
            "total_points": total_points,
            "correct_results": correct_results,
            "exact_scores": exact_scores,
            "correct_cards": correct_cards,
            "correct_corners": correct_corners,
            "total_bets": total_bets,
        })

    standings.sort(key=lambda x: x["total_points"], reverse=True)
    for i, s in enumerate(standings):
        s["rank"] = i + 1

    return standings


def get_user_stats(db: Session, user_id: int) -> dict:
    """Get detailed statistics for a specific user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}

    bets = db.query(Bet).filter(
        Bet.user_id == user_id,
        Bet.match.has(is_finished=True)
    ).all()

    total = len(bets)
    correct_results = sum(1 for b in bets if b.points_result > 0)
    exact_scores = sum(1 for b in bets if b.points_score > 0)
    cards_correct = sum(1 for b in bets if b.points_cards > 0)
    corners_correct = sum(1 for b in bets if b.points_corners > 0)
    total_points = sum(
        (b.points_result or 0) + (b.points_score or 0) +
        (b.points_cards or 0) + (b.points_corners or 0)
        for b in bets
    )

    return {
        "total_bets": total,
        "correct_results": correct_results,
        "exact_scores": exact_scores,
        "cards_correct": cards_correct,
        "corners_correct": corners_correct,
        "total_points": total_points,
        "accuracy": round((correct_results / total * 100), 1) if total > 0 else 0,
    }


def get_settings_value(db: Session, key: str, default: str = "0") -> str:
    """Get a setting value from the database."""
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()
    return setting.value if setting else default


def set_settings_value(db: Session, key: str, value: str):
    """Set a setting value in the database."""
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()


def close_daily_results(db: Session, closed_by: int) -> dict:
    """Close results for today and calculate daily standings."""
    today = date.today()

    existing = db.query(DailyClosure).filter(DailyClosure.closure_date == today).first()
    if existing:
        return {"error": "Ya se realizó el cierre de hoy"}

    # Recalculate all bets first
    recalculate_all_bets(db)

    # Get all finished matches
    finished = db.query(Match).filter(Match.is_finished == True).count()

    closure = DailyClosure(
        closure_date=today,
        closed_by=closed_by,
        matches_count=finished,
    )
    db.add(closure)
    db.commit()

    standings = get_user_standings(db)
    return {
        "success": True,
        "date": today.isoformat(),
        "standings": standings,
    }
