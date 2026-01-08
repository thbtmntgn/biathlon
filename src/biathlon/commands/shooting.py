"""Shooting accuracy command handler."""

from __future__ import annotations

import argparse
import sys

from ..api import BiathlonError, get_cup_results, get_current_season_id, get_events, get_race_results, get_races
from ..constants import CAT_TO_GENDER, GENDER_TO_CAT, INDIVIDUAL_DISCIPLINES, RELAY_DISCIPLINE
from ..formatting import Color, format_pct, is_pretty_output, render_table
from ..utils import extract_results
from .results import _has_completed_results
from .scores import find_cup_id


def accumulate_accuracy_by_athlete(results: list[dict]) -> dict[str, dict]:
    """Aggregate shooting accuracy stats per athlete."""
    stats: dict[str, dict] = {}

    for res in results:
        if res.get("IsTeam"):
            continue
        shootings = res.get("Shootings")
        if not shootings:
            continue
        ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
        if not ident:
            continue
        parts = [p.strip() for p in shootings.split("+") if p.strip()]
        if not parts:
            continue
        misses_list: list[int] = []
        for part in parts:
            try:
                misses_list.append(int(part))
            except ValueError:
                misses_list.append(0)
        shots = len(parts) * 5
        total_misses = sum(misses_list)
        entry = stats.setdefault(ident, {
            "name": res.get("Name") or res.get("ShortName") or "",
            "nat": res.get("Nat") or "",
            "races": 0, "shots": 0, "misses": 0,
            "prone_shots": 0, "prone_misses": 0,
            "standing_shots": 0, "standing_misses": 0,
        })
        entry["races"] += 1
        entry["shots"] += shots
        entry["misses"] += total_misses
        for idx, miss_val in enumerate(misses_list):
            if idx % 2 == 0:
                entry["prone_shots"] += 5
                entry["prone_misses"] += miss_val
            else:
                entry["standing_shots"] += 5
                entry["standing_misses"] += miss_val
    return stats


def _fetch_cup_standings(season_id: str, gender: str) -> list[dict]:
    """Fetch World Cup standings for a season and gender."""
    try:
        cup_id = find_cup_id(season_id, gender, level=1, cup_type="total")
        payload = get_cup_results(cup_id)
        return payload.get("Rows") or payload.get("Results") or []
    except BiathlonError:
        return []


def handle_shooting(args: argparse.Namespace) -> int:
    """Show shooting accuracy for race/event/season."""
    scope_count = sum(1 for v in [args.race, args.event, args.season] if v)
    if scope_count > 1:
        print("error: use only one of --race, --event, or --season", file=sys.stderr)
        return 1

    season_id = args.season or get_current_season_id()
    gender = "men" if args.men else "women"
    cat_id = GENDER_TO_CAT.get(gender.lower())
    current_gender = gender
    current_cat_id = cat_id

    results_to_process: list[dict] = []
    scope_label = f"season {season_id}" if not args.event and not args.race else ""
    race_ids: set[str] = set()
    race_meta: list[dict] = []

    def add_results_from_race(race_id: str, discipline_hint: str = "") -> None:
        nonlocal scope_label, current_cat_id, current_gender
        try:
            payload = get_race_results(race_id)
        except BiathlonError:
            return
        if not _has_completed_results(payload):
            return
        comp = payload.get("Competition") or {}
        comp_cat = str(
            comp.get("catId") or comp.get("CatId") or (payload.get("SportEvt") or {}).get("CatId") or ""
        ).upper()
        discipline = str(comp.get("DisciplineId") or discipline_hint or "").upper()
        if args.race and comp_cat and comp_cat != current_cat_id and comp_cat in CAT_TO_GENDER:
            current_cat_id = comp_cat
            current_gender = CAT_TO_GENDER[comp_cat]
        if discipline == RELAY_DISCIPLINE:
            return
        if args.all_races and discipline not in INDIVIDUAL_DISCIPLINES:
            return
        if current_cat_id:
            if comp_cat and comp_cat != current_cat_id:
                return
            if not comp_cat:
                return
        results = extract_results(payload)
        if not results:
            return
        # Only count races that have actual shooting data
        if not any(r.get("Shootings") for r in results if not r.get("IsTeam")):
            return
        results_to_process.extend(results)
        if args.race and not scope_label:
            scope_label = comp.get("ShortDescription") or payload.get("SportEvt", {}).get("ShortDescription") or race_id
        if race_id:
            race_ids.add(race_id)
            race_meta.append({
                "race_id": race_id, "discipline": discipline, "cat": comp_cat or "",
                "label": comp.get("ShortDescription") or comp.get("Description") or "",
            })

    if args.race:
        add_results_from_race(args.race)
    else:
        events = get_events(season_id, level=1)
        event_list = [ev for ev in events if ev.get("EventId") == args.event] if args.event else events
        for ev in event_list:
            event_id = ev.get("EventId")
            if not event_id:
                continue
            for race in get_races(event_id):
                race_id = race.get("RaceId") or race.get("Id") or ""
                discipline_hint = str(race.get("DisciplineId") or "").upper()
                add_results_from_race(race_id, discipline_hint)
            if args.event and not scope_label:
                scope_label = ev.get("ShortDescription") or ev.get("Organizer") or args.event
        if args.event and not scope_label:
            scope_label = args.event

    if not results_to_process:
        print("no shooting data found for the requested scope", file=sys.stderr)
        return 1

    total_races = len(race_ids)
    if args.all_races and total_races == 0:
        print("no non-relay races found for the requested scope", file=sys.stderr)
        return 1

    stats = accumulate_accuracy_by_athlete(results_to_process)
    if not stats:
        print("no shooting data found for the requested scope", file=sys.stderr)
        return 1

    # Fetch cup standings once (used for WC position column and --top filter)
    cup_rows = _fetch_cup_standings(season_id, current_gender)
    cup_rankings: dict[str, str] = {}
    for row in cup_rows:
        name = row.get("Name") or row.get("ShortName") or ""
        if name:
            cup_rankings[name] = str(row.get("Rank") or row.get("ResultOrder") or "")

    rows = []
    for entry in stats.values():
        shots = entry["shots"]
        misses = entry["misses"]
        hits = shots - misses
        prone_hits = entry["prone_shots"] - entry["prone_misses"]
        standing_hits = entry["standing_shots"] - entry["standing_misses"]
        acc = hits / shots if shots else -1
        rows.append({
            "name": entry["name"], "nat": entry["nat"],
            "races": entry["races"], "shots": shots, "hits": hits,
            "misses": misses, "acc": acc,
            "prone_shots": entry["prone_shots"], "prone_hits": prone_hits,
            "standing_shots": entry["standing_shots"], "standing_hits": standing_hits,
            "wc_position": cup_rankings.get(entry["name"], "-"),
        })

    must_start_all = args.all_races or bool(args.event)
    if must_start_all:
        rows = [row for row in rows if row["races"] == total_races]
    if args.min_race and args.min_race > 0:
        rows = [row for row in rows if row["races"] >= args.min_race]

    # Filter to top N athletes in WC standings (reuse already-fetched data)
    if args.top and args.top > 0 and cup_rows:
        top_names = {
            r.get("Name") or r.get("ShortName") or ""
            for r in cup_rows[:args.top]
        }
        top_names.discard("")
        if top_names:
            rows = [row for row in rows if row["name"] in top_names]

    allowed_sorts = {
        "accuracy", "misses", "shots", "races", "name", "country",
        "prone_misses", "standing_misses", "prone_accuracy", "standing_accuracy",
    }
    if args.sort and args.sort.lower() not in allowed_sorts:
        print(f"error: sort must be one of {', '.join(sorted(allowed_sorts))}", file=sys.stderr)
        return 1

    if must_start_all and not rows:
        if args.debug_races:
            for meta in race_meta:
                print(f"race {meta.get('race_id','')} disc={meta.get('discipline','')} cat={meta.get('cat','')} label={meta.get('label','')}")
        qualifier = "non-relay " if args.all_races else ""
        print(f"no athletes shot in all {total_races} {qualifier}races of this scope", file=sys.stderr)
        return 1

    def sort_key(row: dict, column: str) -> tuple:
        col = column.lower()
        if col == "name":
            return (0, row["name"])
        if col == "country":
            return (0, row["nat"], row["name"])
        if col == "misses":
            return (0, row["misses"], -row["shots"], row["name"])
        if col == "accuracy":
            return (0, -(row["acc"] if row["acc"] >= 0 else -1), -row["shots"], row["name"])
        if col == "prone_misses":
            return (0, row["prone_shots"] - row["prone_hits"], -row["shots"], row["name"])
        if col == "standing_misses":
            return (0, row["standing_shots"] - row["standing_hits"], -row["shots"], row["name"])
        if col == "prone_accuracy":
            pct = row["prone_hits"] / row["prone_shots"] if row["prone_shots"] else -1
            return (0, -pct, -row["shots"], row["name"])
        if col == "standing_accuracy":
            pct = row["standing_hits"] / row["standing_shots"] if row["standing_shots"] else -1
            return (0, -pct, -row["shots"], row["name"])
        if col in {"shots", "races"}:
            return (0, -row[col], row["name"])
        return (0, row["name"])

    sort_col = (args.sort or "accuracy").lower()
    rows.sort(key=lambda row: sort_key(row, sort_col))

    headers = [
        "Position", "Name", "Country", "WCPosition", "Races", "Shots", "Misses",
        "ProneMisses", "StandingMisses", "Accuracy", "ProneAccuracy", "StandingAccuracy",
    ]
    render_rows = []
    accuracy_values: list[tuple[float, float, float]] = []
    position = 1
    for row in rows:
        if row["shots"] == 0:
            continue
        acc = row["hits"] / row["shots"] if row["shots"] else 0
        prone_acc = row["prone_hits"] / row["prone_shots"] if row["prone_shots"] else 0
        standing_acc = row["standing_hits"] / row["standing_shots"] if row["standing_shots"] else 0
        render_rows.append([
            position, row["name"], row["nat"], row.get("wc_position", "-"),
            row["races"], row["shots"], row["misses"],
            row["prone_shots"] - row["prone_hits"],
            row["standing_shots"] - row["standing_hits"],
            format_pct(row["hits"], row["shots"]),
            format_pct(row["prone_hits"], row["prone_shots"]),
            format_pct(row["standing_hits"], row["standing_shots"]),
        ])
        accuracy_values.append((acc, prone_acc, standing_acc))
        position += 1

    # Apply display limit
    first_n = getattr(args, "first", 25) or 0
    if first_n > 0:
        render_rows = render_rows[:first_n]
        accuracy_values = accuracy_values[:first_n]

    pretty = is_pretty_output(args)

    # Create cell formatters for accuracy columns (indices 9, 10, 11)
    # Scale from 100% (green) to min% (red), with midpoint having no color
    cell_formatters = None
    if pretty and accuracy_values:
        all_acc = [v for acc_tuple in accuracy_values for v in acc_tuple]
        min_acc = min(all_acc) if all_acc else 0.5
        mid_acc = (1.0 + min_acc) / 2  # midpoint between 100% and min%

        def make_acc_formatter(acc_idx: int):
            def formatter(cell_str: str, row_idx: int) -> str:
                if row_idx < len(accuracy_values):
                    pct = accuracy_values[row_idx][acc_idx]
                    if not Color.enabled():
                        return cell_str
                    if pct > mid_acc:
                        intensity = (pct - mid_acc) / (1.0 - mid_acc) if mid_acc < 1.0 else 0
                        return Color.green(cell_str, intensity)
                    elif pct < mid_acc:
                        intensity = (mid_acc - pct) / (mid_acc - min_acc) if mid_acc > min_acc else 0
                        return Color.red(cell_str, intensity)
                return cell_str
            return formatter

        cell_formatters = [None] * len(headers)
        cell_formatters[9] = make_acc_formatter(0)   # Accuracy
        cell_formatters[10] = make_acc_formatter(1)  # ProneAccuracy
        cell_formatters[11] = make_acc_formatter(2)  # StandingAccuracy

    print()
    print(f"# Shooting accuracy — {current_gender} — {scope_label or (f'season {season_id}' if not args.race else args.race)}")
    render_table(headers, render_rows, pretty=pretty, cell_formatters=cell_formatters)
    print()
    return 0
