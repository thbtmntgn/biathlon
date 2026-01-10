"""Cumulate command handlers for aggregated statistics."""

from __future__ import annotations

import argparse
import sys

from ..api import (
    BiathlonError,
    get_analytic_results,
    get_cup_results,
    get_current_season_id,
    get_events,
    get_race_results,
    get_races,
)
from ..constants import GENDER_TO_CAT, INDIVIDUAL_DISCIPLINES, RELAY_DISCIPLINE, SHOTS_PER_DISCIPLINE
from ..formatting import format_seconds, is_pretty_output, rank_style, render_table
from ..utils import (
    base_time_seconds,
    extract_results,
    get_first_time,
    parse_misses,
    parse_time_seconds,
    result_seconds,
)
from .scores import find_cup_id, SCORE_TYPE_TO_DISCIPLINE


def selected_disciplines(type_arg: str) -> set[str]:
    """Return set of discipline ids for a given type (supports 'all')."""
    if type_arg.lower() == "all":
        return INDIVIDUAL_DISCIPLINES.copy()
    discipline = SCORE_TYPE_TO_DISCIPLINE.get(type_arg.lower())
    if not discipline:
        raise BiathlonError("unknown race type")
    return {discipline}


def cumulate_across_races(
    args: argparse.Namespace,
    accumulator: str,
) -> tuple[list[dict], int, str, str, str, str]:
    """Generic cumulation helper returning rows, race count, gender label, season id, scope label, type label."""
    season_id = args.season or get_current_season_id()
    gender = "men" if args.men else "women"
    resolved_type = "all" if args.event else (args.discipline or "sprint")
    disciplines = selected_disciplines(resolved_type)
    position_mode = accumulator in {"ski", "time", "range", "shooting"} and getattr(args, "position", False)
    min_races_required = getattr(args, "min_race", 0) if position_mode else 0
    cat_id = GENDER_TO_CAT.get(gender.lower())
    debug_races = getattr(args, "debug_races", False)
    scope_label = ""

    if args.event:
        event_list = get_events(season_id, level=1)
        matching = next((ev for ev in event_list if ev.get("EventId") == args.event), None)
        if matching:
            scope_label = matching.get("ShortDescription") or matching.get("Organizer") or args.event
            events = [matching]
        else:
            events = [{"EventId": args.event, "SeasonId": season_id}]
    else:
        events = get_events(season_id, level=1)

    if not scope_label:
        scope_label = f"season {season_id}"

    totals: dict[str, dict] = {}
    total_races = 0

    for event in events:
        event_id = event.get("EventId")
        if not event_id:
            continue
        for race in get_races(event_id):
            disc = str(race.get("DisciplineId") or "").upper()
            if disc not in disciplines or disc == RELAY_DISCIPLINE:
                continue
            default_shots = SHOTS_PER_DISCIPLINE.get(disc, 0)
            race_id = race.get("RaceId") or race.get("Id")
            if not race_id:
                continue
            try:
                payload = get_race_results(race_id)
            except BiathlonError:
                continue
            comp = payload.get("Competition") or {}
            comp_cat = str(comp.get("catId") or "").upper()
            if comp_cat and comp_cat != cat_id:
                continue
            results = extract_results(payload)
            if not results:
                continue
            race_used = False
            base_secs = base_time_seconds(results)

            shooting_lookup: dict[str, str] = {}
            range_lookup: dict[str, str] = {}
            ski_lookup: dict[str, str] = {}
            race_times: dict[str, float] = {}

            if accumulator in {"shooting", "range", "ski"}:
                type_ids = (
                    ["STTM"] if accumulator == "shooting"
                    else ["RNGT"] if accumulator == "range"
                    else ["SKIT", "CRST"]
                )
                for tid in type_ids:
                    try:
                        analytic = get_analytic_results(race_id, tid)
                    except BiathlonError:
                        continue
                    for row in analytic.get("Results") or []:
                        if row.get("IsTeam"):
                            continue
                        ident = row.get("IBUId") or row.get("Bib") or row.get("Name")
                        if not ident:
                            continue
                        val = get_first_time(row, ["TotalTime", "Result"])
                        if accumulator == "shooting":
                            shooting_lookup[ident] = val
                        elif accumulator == "range":
                            range_lookup[ident] = val
                        else:
                            ski_lookup.setdefault(ident, val)

            for res in results:
                ibuid = res.get("IBUId") or res.get("Bib") or res.get("Name")
                if not ibuid:
                    continue
                entry = totals.setdefault(ibuid, {
                    "name": res.get("Name") or res.get("ShortName") or "",
                    "nat": res.get("Nat") or "",
                    "races": 0, "time": 0.0, "misses": 0, "shots": 0,
                    "pos_total": 0.0, "pos_races": 0,
                })

                if accumulator == "time":
                    secs = result_seconds(res, base_secs)
                    if secs is None:
                        continue
                    entry["time"] += secs
                    entry["races"] += 1
                    race_used = True
                    if position_mode:
                        race_times[ibuid] = secs
                elif accumulator == "miss":
                    misses = parse_misses(res.get("ShootingTotal"))
                    if misses is None:
                        continue
                    entry["misses"] += misses
                    entry["races"] += 1
                    race_used = True
                elif accumulator in {"shooting", "range", "ski"}:
                    lookup = shooting_lookup if accumulator == "shooting" else range_lookup if accumulator == "range" else ski_lookup
                    val = lookup.get(ibuid)
                    if accumulator == "ski" and not val:
                        val = get_first_time(res, [
                            "TotalSkiTime", "SkiTime", "SkiTimeTotal", "SKITime", "Ski",
                            "TotalCourseTime", "CourseTime", "RunTime",
                        ])
                    if accumulator == "shooting" and not val:
                        val = get_first_time(res, ["TotalShootingTime", "ShootingTime"])
                    if accumulator == "range" and not val:
                        val = get_first_time(res, ["TotalRangeTime", "RangeTime"])
                    secs = parse_time_seconds(val) if val else None
                    if secs is None:
                        if position_mode:
                            secs = float("inf")
                        else:
                            continue
                    entry.setdefault("time", 0.0)
                    entry["time"] += secs

                    if accumulator == "shooting":
                        shooting_total = res.get("ShootingTotal")
                        miss_val = parse_misses(shooting_total)
                        shootings = res.get("Shootings")
                        shots_taken = 0
                        if shootings:
                            parts = [p.strip() for p in shootings.split("+") if p.strip()]
                            shots_taken = len(parts) * 5
                            if miss_val is None:
                                try:
                                    miss_val = sum(int(p) for p in parts if p.isdigit())
                                except ValueError:
                                    miss_val = None
                        elif miss_val is not None:
                            shots_taken = default_shots
                        if miss_val is not None:
                            entry["misses"] += miss_val
                        if shots_taken:
                            entry["shots"] += shots_taken
                        if position_mode:
                            race_times[ibuid] = secs
                    if accumulator == "range" and position_mode:
                        race_times[ibuid] = secs
                    if accumulator == "ski" and position_mode:
                        race_times[ibuid] = secs
                    entry["races"] += 1
                    race_used = True

            if position_mode and race_times:
                sorted_times = sorted(race_times.items(), key=lambda kv: kv[1])
                missing_start = len(sorted_times)
                missing_idx = 0
                for res in results:
                    ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
                    if not ident or ident in race_times:
                        continue
                    entry = totals.setdefault(ident, {
                        "name": res.get("Name") or res.get("ShortName") or "",
                        "nat": res.get("Nat") or "",
                        "races": 0, "time": 0.0, "misses": 0, "shots": 0,
                        "pos_total": 0.0, "pos_races": 0,
                    })
                    entry["pos_total"] += missing_start + missing_idx + 1
                    entry["pos_races"] += 1
                    missing_idx += 1
                for idx, (ident, _) in enumerate(sorted_times, start=1):
                    totals[ident]["pos_total"] += idx
                    totals[ident]["pos_races"] += 1
                race_used = True
            elif position_mode and results:
                for idx, res in enumerate(results, start=1):
                    ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
                    if not ident:
                        continue
                    entry = totals.setdefault(ident, {
                        "name": res.get("Name") or res.get("ShortName") or "",
                        "nat": res.get("Nat") or "",
                        "races": 0, "time": 0.0, "misses": 0, "shots": 0,
                        "pos_total": 0.0, "pos_races": 0,
                    })
                    entry["pos_total"] += idx
                    entry["pos_races"] += 1
                race_used = True

            if debug_races:
                event_label = event.get("ShortDescription") or event.get("Organizer") or event_id
                race_label = race.get("ShortDescription") or race.get("Description") or disc
                status = "used" if race_used else "SKIPPED"
                print(f"[{accumulator}] {event_label} / {race_label} ({race_id}): {status}")
            if race_used:
                total_races += 1

    rows: list[dict] = []
    if position_mode:
        for entry in totals.values():
            races_done = entry.get("pos_races", entry.get("races", 0))
            if races_done == 0:
                continue
            if min_races_required and races_done < min_races_required:
                continue
            entry["races"] = races_done
            entry["avg_pos"] = entry.get("pos_total", 0) / races_done
            rows.append(entry)
    else:
        for entry in totals.values():
            if entry["races"] != total_races:
                continue
            rows.append(entry)

    return rows, total_races, gender, season_id, scope_label, resolved_type


def handle_cumulate_time_generic(args: argparse.Namespace, label: str, accumulator: str) -> int:
    """Generic handler for cumulative time rankings."""
    position_mode = getattr(args, "position", False)
    rows, total_races, gender, season_id, scope_label, resolved_type = cumulate_across_races(args, accumulator)

    if total_races == 0:
        print("no cumulative data found", file=sys.stderr)
        return 1
    if not rows:
        if position_mode:
            print("no athletes met the position/minimum races criteria", file=sys.stderr)
        else:
            print("no athletes completed all races of this type", file=sys.stderr)
        return 1

    if position_mode:
        rows.sort(key=lambda row: (row["avg_pos"], -row["races"], row["name"]))
        headers = ["Rank", "Name", "Country", "Races", "AvgPosition"]
    else:
        rows.sort(key=lambda row: row.get("time", 0))
        headers = ["Rank", "Name", "Country", "Races", "TotalTime"]

    # Apply display limit
    limit_n = getattr(args, "limit", 25) or 0
    if limit_n > 0:
        rows = rows[:limit_n]

    if position_mode:
        render_rows = [
            [idx + 1, row["name"], row["nat"], row["races"], f"{row['avg_pos']:.2f}"]
            for idx, row in enumerate(rows)
        ]
    else:
        render_rows = [
            [idx + 1, row["name"], row["nat"], row["races"], format_seconds(row.get("time", 0))]
            for idx, row in enumerate(rows)
        ]

    scope = scope_label or (f"event {args.event}" if args.event else f"season {season_id}")
    note = "" if position_mode else f" (must start all {total_races} races)"
    print(f"# Cumulative {label} {resolved_type} — {gender} — {scope}{note}")
    pretty = is_pretty_output(args)
    row_styles = [rank_style(idx + 1) for idx in range(len(render_rows))] if pretty else None
    render_table(headers, render_rows, pretty=pretty, row_styles=row_styles)
    return 0


def handle_cumulate_course(args: argparse.Namespace) -> int:
    """Compute cumulative course time ranking."""
    return handle_cumulate_time_generic(args, "course time", "time")


def handle_cumulate_miss(args: argparse.Namespace) -> int:
    """Compute cumulative missed targets ranking."""
    rows, total_races, gender, season_id, scope_label, resolved_type = cumulate_across_races(args, "miss")

    if total_races == 0:
        print("no cumulative data found", file=sys.stderr)
        return 1
    if not rows:
        print("no athletes completed all races of this type", file=sys.stderr)
        return 1

    rows.sort(key=lambda row: (row["misses"], row.get("time", 0)))

    # Apply display limit
    limit_n = getattr(args, "limit", 25) or 0
    if limit_n > 0:
        rows = rows[:limit_n]

    headers = ["Rank", "Name", "Country", "Races", "Misses"]
    render_rows = [
        [idx + 1, row["name"], row["nat"], row["races"], row["misses"]]
        for idx, row in enumerate(rows)
    ]

    scope = scope_label or (f"event {args.event}" if args.event else f"season {season_id}")
    print(f"# Cumulative misses {resolved_type} — {gender} — {scope} (must start all {total_races} races)")
    pretty = is_pretty_output(args)
    row_styles = [rank_style(idx + 1) for idx in range(len(render_rows))] if pretty else None
    render_table(headers, render_rows, pretty=pretty, row_styles=row_styles)
    return 0


def handle_cumulate_shooting(args: argparse.Namespace) -> int:
    """Compute cumulative shooting time ranking."""
    position_mode = getattr(args, "position", False)
    rows, total_races, gender, season_id, scope_label, resolved_type = cumulate_across_races(args, "shooting")

    if total_races == 0:
        print("no cumulative data found", file=sys.stderr)
        return 1
    if not rows:
        msg = "no athletes met the position/minimum races criteria" if position_mode else "no athletes completed all races of this type"
        print(msg, file=sys.stderr)
        return 1

    def acc_value(row: dict) -> float | None:
        shots = row.get("shots", 0)
        return (1 - (row.get("misses", 0) / shots)) if shots else None

    # Apply display limit
    first_n = getattr(args, "first", 25) or 0

    if position_mode:
        sort_opt = (args.sort or "position").lower()
        if sort_opt not in {"position", "accuracy", "shootingtime", "misses"}:
            print("error: sort must be position or accuracy when using --position", file=sys.stderr)
            return 1
        base_sorted = sorted(rows, key=lambda row: (row["avg_pos"], -row["races"], row["name"]))
        for idx, row in enumerate(base_sorted, start=1):
            row["rank_saved"] = idx
        if sort_opt == "accuracy":
            display_rows = sorted(rows, key=lambda row: (-(acc_value(row) or -1.0), row["rank_saved"]))
        else:
            display_rows = base_sorted
        if first_n > 0:
            display_rows = display_rows[:first_n]
        headers = ["Rank", "Name", "Country", "Races", "AvgPosition", "Accuracy"]
        render_rows = [
            [row.get("rank_saved", idx), row["name"], row["nat"], row["races"],
             f"{row['avg_pos']:.2f}", "-" if acc_value(row) is None else f"{acc_value(row) * 100:.1f}%"]
            for idx, row in enumerate(display_rows, start=1)
        ]
    else:
        sort_key = (args.sort or "shootingtime").lower()
        if sort_key not in {"shootingtime", "misses"}:
            print("error: sort must be shootingtime or misses", file=sys.stderr)
            return 1
        base_sorted = sorted(rows, key=lambda row: (row.get("time", 0), row.get("misses", 0)))
        for idx, row in enumerate(base_sorted, start=1):
            row["rank_saved"] = idx
        display_rows = sorted(rows, key=lambda row: (row.get("misses", 0), row.get("time", 0), row["rank_saved"])) if sort_key == "misses" else base_sorted
        if first_n > 0:
            display_rows = display_rows[:first_n]
        headers = ["Rank", "Name", "Country", "Races", "ShootingTime", "Misses"]
        render_rows = [
            [row["rank_saved"], row["name"], row["nat"], row["races"], format_seconds(row.get("time", 0)), row.get("misses", 0)]
            for row in display_rows
        ]

    scope = scope_label or (f"event {args.event}" if args.event else f"season {season_id}")
    note = "" if position_mode else f" (must start all {total_races} races)"
    print(f"# Cumulative shooting time {resolved_type} — {gender} — {scope}{note}")
    pretty = is_pretty_output(args)
    # Use rank_saved for styling since rows may be re-sorted by different criteria
    row_styles = [rank_style(row["rank_saved"]) for row in display_rows] if pretty else None
    render_table(headers, render_rows, pretty=pretty, row_styles=row_styles)
    return 0


def handle_cumulate_range(args: argparse.Namespace) -> int:
    """Compute cumulative range time ranking."""
    return handle_cumulate_time_generic(args, "range time", "range")


def handle_cumulate_ski(args: argparse.Namespace) -> int:
    """Compute cumulative ski time ranking."""
    return handle_cumulate_time_generic(args, "ski time", "ski")


def handle_cumulate_remontada(args: argparse.Namespace) -> int:
    """Aggregate pursuit remontada across a season."""
    season_id = args.season or get_current_season_id()
    gender = "men" if args.men else "women"
    cat_id = GENDER_TO_CAT.get(gender.lower())
    totals: dict[str, dict] = {}
    total_races = 0

    def as_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    for event in get_events(season_id, level=1):
        event_id = event.get("EventId")
        if not event_id:
            continue
        for race in get_races(event_id):
            if str(race.get("DisciplineId") or "").upper() != "PU":
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
            results = extract_results(payload)
            if not results:
                continue
            race_used = False
            for res in results:
                status = str(res.get("IRM") or "").upper()
                if status and status not in {"OK", ""}:
                    continue
                start_rank = as_int(res.get("StartOrder") or res.get("StartPosition") or res.get("StartRow"))
                finish_rank = as_int(res.get("Rank") or res.get("ResultOrder"))
                if start_rank is None or finish_rank is None:
                    continue
                # Skip placeholder values from unfinished races
                if finish_rank > 500:
                    continue
                gain = start_rank - finish_rank
                ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
                if not ident:
                    continue
                entry = totals.setdefault(ident, {
                    "name": res.get("Name") or res.get("ShortName") or "",
                    "nat": res.get("Nat") or "", "gain": 0, "races": 0,
                })
                entry["gain"] += gain
                entry["races"] += 1
                race_used = True
            if race_used:
                total_races += 1

    if total_races == 0:
        print("no pursuit races found for remontada", file=sys.stderr)
        return 1
    if not totals:
        print("no athletes with start/finish ranks for remontada", file=sys.stderr)
        return 1

    rows = list(totals.values())

    cup_rankings: dict[str, str] = {}
    try:
        cup_id = find_cup_id(season_id, gender, level=1, cup_type="total")
        cup_payload = get_cup_results(cup_id)
        cup_rows = cup_payload.get("Rows") or cup_payload.get("Results") or []
        for idx, crow in enumerate(cup_rows, start=1):
            name = crow.get("Name") or crow.get("ShortName") or ""
            if name:
                cup_rankings[name] = str(crow.get("Rank") or crow.get("ResultOrder") or idx)
        if args.top and args.top > 0:
            top_names = {r.get("Name") or r.get("ShortName") or "" for r in cup_rows[:args.top]}
            rows = [row for row in rows if row["name"] in top_names]
    except BiathlonError:
        pass

    min_race_val = getattr(args, "min_race", 0)
    if min_race_val and min_race_val > 0:
        rows = [row for row in rows if row["races"] >= min_race_val]

    rows.sort(key=lambda r: (-r["gain"], -r["races"], r["name"]))

    # Apply display limit
    limit_n = getattr(args, "limit", 25) or 0
    if limit_n > 0:
        rows = rows[:limit_n]

    headers = ["Rank", "Name", "Country", "Races", "Gain", "WCRank"]
    render_rows = [
        [idx + 1, row["name"], row["nat"], row["races"],
         f"+{row['gain']}" if row["gain"] > 0 else str(row["gain"]),
         cup_rankings.get(row["name"], "-")]
        for idx, row in enumerate(rows)
    ]

    print(f"# Cumulative remontada — {gender} — season {season_id} (pursuit races)")
    pretty = is_pretty_output(args)
    row_styles = [rank_style(idx + 1) for idx in range(len(render_rows))] if pretty else None
    render_table(headers, render_rows, pretty=pretty, row_styles=row_styles)
    return 0
