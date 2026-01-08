"""Records command handler."""

from __future__ import annotations

import argparse
import datetime
import sys

from ..api import BiathlonError, get_current_season_id, get_events, get_race_results, get_races
from ..constants import GENDER_TO_CAT, SKI_LAPS
from ..formatting import format_seconds, is_pretty_output, render_table
from ..utils import build_analytic_times, extract_results, get_event_label, get_race_label, parse_time_seconds


def handle_record_lap(args: argparse.Namespace) -> int:
    """Show top 10 fastest laps for an event or race."""
    gender = "men" if args.men else "women"
    cat_id = GENDER_TO_CAT.get(gender.lower())

    disc_map = {
        "sprint": {"SP"},
        "pursuit": {"PU"},
        "individual": {"IN"},
        "massstart": {"MS", "MASS-START"},
        "mass-start": {"MS", "MASS-START"},
    }

    # When no event specified, find most recent completed sprint race
    single_race = None
    if args.event:
        event_id = args.event
        event_label = args.event
    else:
        today = datetime.date.today()
        current_season = get_current_season_id()
        evs = get_events(current_season, level=1)

        # Find most recent completed sprint race for the selected gender
        sprint_races = []
        for ev in evs:
            event_id = ev.get("EventId")
            if not event_id:
                continue
            for race in get_races(event_id):
                disc = str(race.get("DisciplineId") or "").upper()
                if disc != "SP":
                    continue
                # Filter by gender (check description since catId may not be in race list)
                race_cat = str(race.get("catId") or race.get("CatId") or "").upper()
                race_desc = (race.get("Description") or race.get("ShortDescription") or "").lower()
                if race_cat and race_cat != cat_id:
                    continue
                # Also check description for gender keywords
                if not race_cat:
                    has_women = "women" in race_desc
                    has_men = "men" in race_desc and not has_women  # "women" contains "men"
                    if gender == "men" and has_women:
                        continue
                    if gender == "women" and has_men:
                        continue
                start_raw = race.get("StartTime") or ""
                try:
                    d = datetime.date.fromisoformat(start_raw.split("T", 1)[0])
                except Exception:
                    continue
                if d <= today:
                    sprint_races.append((d, race, ev))

        sprint_races.sort(key=lambda t: t[0], reverse=True)
        if not sprint_races:
            print(f"no completed {gender} sprint races found", file=sys.stderr)
            return 1

        _, single_race, event = sprint_races[0]
        event_id = event.get("EventId")
        event_label = get_event_label(event) or event_id or ""

    if not event_id and not single_race:
        print("no event id resolved", file=sys.stderr)
        return 1

    rows: list[dict] = []

    # If we found a specific race, only process that one
    races_to_process = [single_race] if single_race else get_races(event_id)
    for race in races_to_process:
        disc = str(race.get("DisciplineId") or "").upper()
        if disc == "RL":
            continue
        if args.discipline:
            allowed = set()
            for key, val in disc_map.items():
                if args.discipline.lower() == key:
                    allowed = {d for d in val}
                    break
            if allowed and disc not in allowed:
                continue
        laps = SKI_LAPS.get(disc, 0)
        if laps == 0:
            continue
        race_id = race.get("RaceId") or race.get("Id")
        if not race_id:
            continue
        try:
            payload = get_race_results(race_id)
        except BiathlonError:
            continue
        comp = payload.get("Competition") or {}
        comp_cat = str(comp.get("catId") or comp.get("CatId") or "").upper()
        if comp_cat and comp_cat != cat_id:
            continue
        athlete_info: dict[str, dict] = {}
        for res in extract_results(payload):
            ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
            if not ident:
                continue
            athlete_info.setdefault(ident, {
                "name": res.get("Name") or res.get("ShortName") or "",
                "nat": res.get("Nat") or "",
            })
        analytics = build_analytic_times(race_id, "CRST", "CRS", "", laps)
        if not analytics:
            continue
        race_label = get_race_label(race)
        for ident, times in analytics.items():
            info = athlete_info.get(ident, {"name": ident, "nat": ""})
            for lap in range(1, laps + 1):
                lap_val = times.get(f"lap{lap}")
                secs = parse_time_seconds(lap_val) if lap_val else None
                if secs is None:
                    continue
                rows.append({
                    "time_sec": secs,
                    "time_str": format_seconds(secs),
                    "lap": lap,
                    "race": race_label,
                    "race_id": race_id,
                    "disc": disc,
                    "name": info["name"],
                    "nat": info["nat"],
                })

    if not rows:
        print("no lap data found for the selected scope", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: r["time_sec"])
    top_rows = rows[:10]

    headers = ["Rank", "Name", "Country", "Discipline", "Race", "Lap", "LapTime", "RaceId"]
    render_rows = [
        [idx + 1, row["name"], row["nat"], row["disc"], row["race"], row["lap"], row["time_str"], row["race_id"]]
        for idx, row in enumerate(top_rows)
    ]

    if single_race:
        race_label = get_race_label(single_race)
        scope_label = f"{event_label} / {race_label}"
    else:
        scope_label = args.event or event_label
    discipline_label = f" — {args.discipline}" if args.discipline else ""
    print(f"# Fastest laps — {gender}{discipline_label} — {scope_label}")
    render_table(headers, render_rows, pretty=is_pretty_output(args))
    return 0
