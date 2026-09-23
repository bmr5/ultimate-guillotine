"""Import the reviewed 2023–2025 Sleeper score archives. Dry-run unless --apply."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg.types.json import Jsonb
from ultimate_guillotine.history.score_records import (
    competitive_scores,
    saved_matchup_roster,
)

LEAGUES = {
    2023: "986707271361060864",
    2024: "1119313867575783424",
    2025: "1254581579569713152",
}
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = dotenv_values(ROOT / ".env")
    with (
        psycopg.connect(config["DATABASE_URL"]) as conn,
        httpx.Client(timeout=30) as client,
    ):
        labels = dict(
            conn.execute("""select t.sleeper_user_id,
          coalesce(nullif(m.nickname,''),nullif(m.sleeper_display_name,''))
          from public.teams t join public.members m on m.id=t.member_id""").fetchall()
        )
        imported = []
        sleeper_players = None
        for season, league_id in LEAGUES.items():

            def get(path, source_league=league_id):
                response = client.get(
                    f"https://api.sleeper.app/v1/league/{source_league}{path}"
                )
                response.raise_for_status()
                return response.json()

            league = get("")
            if (
                str(league["season"]) != str(season)
                or league["status"] != "complete"
                or league["name"] != "Ultimate Guillotine League"
            ):
                raise ValueError("Historical league identity/status mismatch")
            users = {u["user_id"]: u for u in get("/users")}
            rosters = {r["roster_id"]: r for r in get("/rosters")}
            with ThreadPoolExecutor(max_workers=4) as pool:
                payloads = list(pool.map(lambda w: get(f"/matchups/{w}"), range(1, 18)))
            if any(len(rows) != league["total_rosters"] for rows in payloads):
                raise ValueError("Incomplete historical matchup response")
            required_starters = sum(
                slot not in {"BN", "IR", "TAXI"} for slot in league["roster_positions"]
            )
            if required_starters < 1:
                raise ValueError("Missing required starting positions")
            rows, excluded = competitive_scores(
                dict(enumerate(payloads, 1)), required_starters=required_starters
            )
            matchups = {
                (week, r["roster_id"]): r
                for week, payload in enumerate(payloads, 1)
                for r in payload
            }
            player_ids = list(
                {
                    str(p)
                    for r in matchups.values()
                    for p in (r.get("players") or []) + (r.get("starters") or [])
                    if p and str(p) != "0"
                }
            )
            directory = {
                player_id: {"full_name": name, "position": position}
                for player_id, name, position in conn.execute(
                    "select sleeper_player_id,full_name,position from public.players where sleeper_player_id=any(%s)",
                    (player_ids,),
                ).fetchall()
            }
            missing_names = [
                player_id
                for player_id in player_ids
                if not directory.get(player_id, {}).get("full_name")
            ]
            if missing_names and sleeper_players is None:
                response = client.get("https://api.sleeper.app/v1/players/nfl")
                response.raise_for_status()
                sleeper_players = response.json()
            for player_id in missing_names:
                info = (sleeper_players or {}).get(player_id) or {}
                directory[player_id] = {
                    "full_name": info.get("full_name"),
                    "position": info.get("position"),
                }
            for row in rows:
                owner_id = rosters[row["sleeper_roster_id"]]["owner_id"]
                user = users.get(owner_id, {})
                manager = (
                    labels.get(owner_id) or user.get("display_name") or "Former manager"
                )
                team = (user.get("metadata") or {}).get("team_name") or manager
                imported.append(
                    (
                        season,
                        row["week"],
                        row["sleeper_roster_id"],
                        league_id,
                        str(team)[:120],
                        str(manager)[:120],
                        row["points"],
                        row["filled_starting_slots"],
                        row["required_starters"],
                        Jsonb(
                            saved_matchup_roster(
                                matchups[row["week"], row["sleeper_roster_id"]],
                                league["roster_positions"],
                                directory,
                            )
                        ),
                    )
                )
            print(
                f"{season}: {len(rows)} competitive scores; excluded from week {excluded}"
            )
            print(
                "  Low/high:",
                min(r["points"] for r in rows),
                max(r["points"] for r in rows),
            )
            full = [
                r for r in rows if r["filled_starting_slots"] == r["required_starters"]
            ]
            print(
                f"  Full lineups: {len(full)}; lowest {min(r['points'] for r in full)}"
            )
        if args.apply:
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into public.historical_weekly_scores
                  (season,week,sleeper_roster_id,sleeper_league_id,team_label,manager_label,points,
                   filled_starting_slots,required_starters,roster)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  on conflict (season,week,sleeper_roster_id) do update set
                    team_label=excluded.team_label,manager_label=excluded.manager_label,
                    points=excluded.points,filled_starting_slots=excluded.filled_starting_slots,
                    required_starters=excluded.required_starters,roster=excluded.roster,
                    loaded_at=now()""",
                    imported,
                )
            print(f"Saved {len(imported)} historical scores.")
        else:
            print(f"Dry run: {len(imported)} scores, no writes.")


if __name__ == "__main__":
    main()
