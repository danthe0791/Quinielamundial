"""
OpenLigaDB API client for fetching World Cup 2026 match data.
API is completely free, no authentication required.
"""
import httpx
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from .models import Match

LEAGUES = [
    {"shortcut": "wm26", "season": 2026},
]
BASE_URL = "https://api.openligadb.de"

# ─── Translation: German → Spanish ───────────────────────
TRANSLATIONS = {
    "Mexiko": "México", "Südafrika": "Sudáfrica", "Südkorea": "Corea del Sur",
    "Tschechien": "Rep. Checa", "Kanada": "Canadá", "USA": "EE. UU.",
    "Bosnien und Herzegowina": "Bosnia", "Bosnien-Herzegowina": "Bosnia",
    "Paraguay": "Paraguay", "Australien": "Australia", "Türkei": "Turquía",
    "Katar": "Catar", "Schweiz": "Suiza", "Brasilien": "Brasil",
    "Marokko": "Marruecos", "Haiti": "Haití", "Schottland": "Escocia",
    "Deutschland": "Alemania", "Curaçao": "Curazao",
    "Niederlande": "Países Bajos", "Japan": "Japón",
    "Elfenbeinküste": "Costa de Marfil", "Ecuador": "Ecuador",
    "Schweden": "Suecia", "Tunesien": "Túnez", "Spanien": "España",
    "Kap Verde": "Cabo Verde", "Belgien": "Bélgica", "Ägypten": "Egipto",
    "Saudi-Arabien": "Arabia Saudita", "Uruguay": "Uruguay", "Iran": "Irán",
    "Neuseeland": "Nueva Zelanda", "Österreich": "Austria",
    "Jordanien": "Jordania", "Frankreich": "Francia", "Senegal": "Senegal",
    "Irak": "Irak", "Norwegen": "Noruega", "Argentinien": "Argentina",
    "Algerien": "Argelia", "Portugal": "Portugal", "DR Kongo": "RD Congo",
    "England": "Inglaterra", "Kroatien": "Croacia", "Ghana": "Ghana",
    "Panama": "Panamá", "Usbekistan": "Uzbekistán", "Kolumbien": "Colombia",
    "Venezuela": "Venezuela", "Griechenland": "Grecia",
    "Italien": "Italia", "Dänemark": "Dinamarca", "Luxemburg": "Luxemburgo",
}

def translate(name: str) -> str:
    return TRANSLATIONS.get(name, name)


async def fetch_all_matches() -> list[dict]:
    """Fetch all matches for all configured leagues."""
    all_matches = []
    async with httpx.AsyncClient(timeout=30) as client:
        for league in LEAGUES:
            url = f"{BASE_URL}/getmatchdata/{league['shortcut']}/{league['season']}"
            try:
                response = await client.get(url)
                response.raise_for_status()
                all_matches.extend(response.json())
            except Exception as e:
                print(f"Error fetching {league['shortcut']}: {e}")
    return all_matches


async def fetch_available_groups() -> list[dict]:
    """Fetch available groups/rounds."""
    url = f"{BASE_URL}/getavailablegroups/{LEAGUE_SHORTCUT}/{LEAGUE_SEASON}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def parse_match_date(date_str: str) -> Optional[datetime]:
    """Parse match date from OpenLigaDB format."""
    try:
        # Format: "2026-06-11T21:00:00"
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def get_match_result(match_data: dict) -> tuple[Optional[int], Optional[int]]:
    """Extract final score from match results."""
    results = match_data.get("matchResults", [])
    for result in results:
        if result.get("resultTypeID") == 2:  # Final result
            return (
                result.get("pointsTeam1"),
                result.get("pointsTeam2"),
            )
    return None, None


def map_group_to_stage(group_name: str) -> str:
    """Map group name to tournament stage (Spanish)."""
    gn = (group_name or "").lower()
    if "finale" in gn:
        return "Final"
    elif "halbfinale" in gn:
        return "Semifinal"
    elif "viertelfinale" in gn:
        return "Cuartos"
    elif "achtelfinale" in gn:
        return "Octavos"
    elif "sechzehntelfinale" in gn:
        return "Dieciseisavos"
    elif "gruppe" in gn or "spieltag" in gn or "runde" in gn:
        return "Grupos"
    return "Grupos"


def translate_group_name(name: str) -> str:
    """Translate group name to Spanish."""
    if not name:
        return "Grupos"
    # Direct replacements
    replacements = {
        "Gruppenphase 1": "Fase de Grupos 1",
        "Gruppenphase 2": "Fase de Grupos 2",
        "Gruppenphase 3": "Fase de Grupos 3",
        "1. Runde": "Fase 1", "2. Runde": "Fase 2", "3. Runde": "Fase 3",
        "1. Spieltag": "Jornada 1", "2. Spieltag": "Jornada 2",
        "3. Spieltag": "Jornada 3", "4. Spieltag": "Jornada 4",
        "5. Spieltag": "Jornada 5", "6. Spieltag": "Jornada 6",
    }
    if name in replacements:
        return replacements[name]
    gn = name
    if "Gruppenphase" in gn:
        gn = gn.replace("Gruppenphase", "Fase de Grupos")
    if ". Runde" in gn:
        gn = gn.replace(". Runde", "Fase")
    if ". Spieltag" in gn:
        gn = gn.split(".")[1].strip()
        gn = f"Jornada {gn}"
    return gn


async def sync_matches_from_api(db: Session) -> int:
    """Sync matches from OpenLigaDB to local database. Returns count of matches."""
    try:
        matches_data = await fetch_all_matches()
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return 0

    count = 0
    for m in matches_data:
        match_id = m.get("matchID")
        if not match_id:
            continue

        group = m.get("group", {})
        group_name = group.get("groupName", "")
        group_order = group.get("groupOrderID", 0)

        home_score, away_score = get_match_result(m)
        is_finished = m.get("matchIsFinished", False)

        match_date = parse_match_date(m.get("matchDateTime"))
        match_date_utc = parse_match_date(m.get("matchDateTimeUTC"))

        existing = db.query(Match).filter(
            Match.openligadb_match_id == match_id
        ).first()

        team1 = m.get("team1", {})
        team2 = m.get("team2", {})

        match_data = {
            "openligadb_match_id": match_id,
            "home_team": translate(team1.get("teamName", "Unknown")),
            "away_team": translate(team2.get("teamName", "Unknown")),
            "home_short": translate(team1.get("shortName", "")),
            "away_short": translate(team2.get("shortName", "")),
            "home_icon": team1.get("teamIconUrl", ""),
            "away_icon": team2.get("teamIconUrl", ""),
            "match_date": match_date,
            "match_date_utc": match_date_utc,
            "group_name": translate_group_name(group_name),
            "group_order": group_order,
            "stage": map_group_to_stage(group_name),
            "home_score": home_score,
            "away_score": away_score,
            "is_finished": is_finished,
            "last_updated": datetime.utcnow(),
        }

        if existing:
            # Update scores if match finished
            if is_finished and not existing.is_finished:
                for key, value in match_data.items():
                    setattr(existing, key, value)
            elif not is_finished:
                # Update just metadata
                existing.group_name = group_name
                existing.group_order = group_order
                existing.stage = map_group_to_stage(group_name)
                existing.last_updated = datetime.utcnow()
        else:
            db.add(Match(**match_data))
            count += 1

    db.commit()
    return count


async def fetch_group_standings() -> list[dict]:
    """Fetch group standings from OpenLigaDB."""
    url = f"{BASE_URL}/getgrouptable/wm26/2026"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching standings: {e}")
            return []
