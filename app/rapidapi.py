"""
API-Football (RapidAPI) client - brings REAL stats: cards, corners, live scores.
Replaces OpenLigaDB for World Cup data.
"""
import os
import httpx
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from .models import Match

API_KEY = os.environ.get("RAPIDAPI_KEY", "")
API_HOST = "api-football-v1.p.rapidapi.com"
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HEADERS = {
    "x-rapidapi-host": API_HOST,
    "x-rapidapi-key": API_KEY,
}

# World Cup IDs
WC_LEAGUE_ID = 1          # FIFA World Cup
FRIENDLIES_LEAGUE_ID = 10  # International Friendlies
SEASON = 2026


async def fetch_world_cup_fixtures() -> list[dict]:
    """Fetch World Cup 2026 + international friendlies fixtures."""
    all_fixtures = []
    async with httpx.AsyncClient(timeout=30) as client:
        for league_id, league_name in [(WC_LEAGUE_ID, "World Cup"), (FRIENDLIES_LEAGUE_ID, "Friendlies")]:
            url = f"{BASE_URL}/fixtures"
            params = {
                "league": league_id,
                "season": SEASON,
                "from": "2026-06-01",
                "to": "2026-07-19",
            }
            try:
                response = await client.get(url, headers=HEADERS, params=params)
                response.raise_for_status()
                data = response.json()
                fixtures = data.get("response", [])
                # Tag with league info
                for f in fixtures:
                    f["_league_name"] = league_name
                all_fixtures.extend(fixtures)
            except Exception as e:
                print(f"[RapidAPI] Error fetching {league_name}: {e}")
    return all_fixtures


async def fetch_fixture_stats(fixture_id: int) -> dict:
    """Fetch detailed stats for one fixture (cards, corners, etc.)."""
    url = f"{BASE_URL}/fixtures/statistics"
    params = {"fixture": fixture_id}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("response", [])


async def fetch_standings() -> list[dict]:
    """Fetch World Cup group standings."""
    url = f"{BASE_URL}/standings"
    params = {"league": LEAGUE_ID, "season": SEASON}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("response", [])


def parse_fixture_date(fixture: dict) -> Optional[datetime]:
    """Parse fixture date from API-Football format."""
    try:
        return datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError):
        return None


def extract_stats(stats_data: list, team_id: int) -> dict:
    """Extract cards and corners for a specific team from stats."""
    result = {"cards": None, "corners": None}
    try:
        team_stats = stats_data[0 if stats_data[0]["team"]["id"] == team_id else 1]
        for s in team_stats.get("statistics", []):
            if s["type"] == "Yellow Cards":
                result["cards"] = (s.get("value") or 0)
            elif s["type"] == "Corner Kicks":
                result["corners"] = (s.get("value") or 0)
    except (IndexError, KeyError):
        pass
    return result


async def sync_matches_from_api(db: Session) -> int:
    """Sync World Cup matches from API-Football. Returns count of new matches."""
    try:
        fixtures = await fetch_world_cup_fixtures()
    except Exception as e:
        print(f"[RapidAPI] Error fetching fixtures: {e}")
        return 0

    count = 0
    for f in fixtures:
        fixture_info = f["fixture"]
        fixture_id = fixture_info["id"]
        match_date_utc = parse_fixture_date(f)
        is_finished = fixture_info.get("status", {}).get("short") in ("FT", "AET", "PEN")

        teams = f["teams"]
        home = teams["home"]
        away = teams["away"]
        goals = f.get("goals", {})

        home_score = goals.get("home")
        away_score = goals.get("away")

        league_info = f.get("league", {})
        league_name = f.get("_league_name", "")
        group_name = league_info.get("round", "Grupos")

        # For friendlies, set a special group
        is_friendly = league_name == "Friendlies"
        if is_friendly:
            group_name = "Amistosos"
            group_order = 98
            stage = "Amistoso"
        else:
            group_order = 0
            stage = "Grupos"

        existing = db.query(Match).filter(
            Match.openligadb_match_id == fixture_id
        ).first()

        match_data = {
            "openligadb_match_id": fixture_id,
            "home_team": translate_name(home.get("name", "Unknown")),
            "away_team": translate_name(away.get("name", "Unknown")),
            "home_short": home.get("name", "")[:3],
            "away_short": away.get("name", "")[:3],
            "home_icon": "",
            "away_icon": "",
            "match_date": match_date_utc,
            "match_date_utc": match_date_utc,
            "group_name": group_name,
            "group_order": group_order,
            "stage": stage,
            "home_score": home_score,
            "away_score": away_score,
            "is_finished": is_finished,
            "is_friendly": is_friendly,
            "last_updated": datetime.utcnow(),
        }

        # Try to fetch detailed stats (cards, corners)
        if is_finished:
            try:
                stats = await fetch_fixture_stats(fixture_id)
                h_stats = extract_stats(stats, home.get("id", 0))
                a_stats = extract_stats(stats, away.get("id", 0))
                match_data["home_cards"] = h_stats.get("cards")
                match_data["away_cards"] = a_stats.get("cards")
                match_data["home_corners"] = h_stats.get("corners")
                match_data["away_corners"] = a_stats.get("corners")
            except Exception:
                pass

        if existing:
            if is_finished and not existing.is_finished:
                for key, value in match_data.items():
                    setattr(existing, key, value)
        else:
            db.add(Match(**match_data))
            count += 1

    db.commit()
    return count


def translate_name(name: str) -> str:
    """Simple name mapping if needed."""
    # API-Football uses English names - no translation needed
    return name


async def fetch_group_standings() -> list[dict]:
    """Fetch World Cup group standings from API-Football."""
    try:
        data = await fetch_standings()
        # Transform to match OpenLigaDB format for template compatibility
        result = []
        for league_data in data:
            for group in league_data.get("league", {}).get("standings", []):
                result.append({
                    "teamGroupName": group[0]["group"],
                    "teams": [{
                        "teamName": t["team"]["name"],
                        "teamIconUrl": t["team"].get("logo", ""),
                        "points": t["points"],
                        "matches": t["all"]["played"],
                        "won": t["all"]["win"],
                        "draw": t["all"]["draw"],
                        "lost": t["all"]["lose"],
                        "goals": t["all"]["goals"]["for"],
                        "opponentGoals": t["all"]["goals"]["against"],
                        "goalDiff": t["goalsDiff"],
                    } for t in group]
                })
        return result
    except Exception as e:
        print(f"[RapidAPI] Error fetching standings: {e}")
        return []
