"""Athlete command handlers."""

from __future__ import annotations

import argparse
import sys

from ..api import (
    BiathlonError,
    get_athlete_bio,
    get_athletes,
    get_current_season_id,
    get_events,
    get_race_results,
    get_races,
    get_analytic_results,
)
from ..constants import RELAY_DISCIPLINE
from ..formatting import is_pretty_output, render_table
from ..utils import (
    build_analytic_times,
    extract_results,
    get_first_time,
    get_race_label,
    get_race_start_key,
    parse_time_seconds,
)


def handle_athlete_results(args: argparse.Namespace) -> int:
    """Show season race ranks for an athlete."""
    if not args.id and not args.search:
        print("error: provide --id or --search", file=sys.stderr)
        return 1

    season_id = args.season or get_current_season_id()
    event_map: dict[str, dict] = {}
    level_arg = getattr(args, "level", 0)
    levels = [level_arg] if level_arg in {1, 2, 3, 4, 5} else [1, 2, 3, 4, 5]
    for lvl in levels:
        for ev in get_events(season_id, level=lvl):
            key = ev.get("EventId") or f"{lvl}-{ev.get('Description','')}"
            event_map.setdefault(key, ev)
    events = list(event_map.values())

    race_entries: list[dict] = []
    athlete_map: dict[str, dict] = {}

    def has_analytics(race_id: str) -> bool:
        for type_id in ("CRST", "RNGT", "SHTT"):
            try:
                analytic = get_analytic_results(race_id, type_id)
            except BiathlonError:
                return True
            if analytic.get("Results"):
                return True
        return False

    for event in events:
        event_id = event.get("EventId")
        if not event_id:
            continue
        event_label = event.get("Description") or event.get("ShortDescription") or event.get("Organizer") or ""
        location_label = event.get("ShortDescription") or event.get("Organizer") or ""
        for race in sorted(get_races(event_id), key=get_race_start_key):
            race_id = race.get("RaceId") or race.get("Id")
            if not race_id:
                continue
            if not has_analytics(race_id):
                continue
            try:
                payload = get_race_results(race_id)
            except BiathlonError:
                continue
            results = extract_results(payload)
            comp = payload.get("Competition") or {}
            sport_evt = payload.get("SportEvt") or {}
            race_label = comp.get("ShortDescription") or comp.get("Description") or get_race_label(race)
            start_raw = comp.get("StartTime") or comp.get("StartDate") or race.get("StartTime") or race.get("StartDate")
            race_date = start_raw.split("T", 1)[0] if isinstance(start_raw, str) else ""
            discipline = comp.get("DisciplineId") or race.get("DisciplineId") or ""

            ski_ranks: dict[str, int] = {}
            if args.ski:
                analytics = build_analytic_times(race_id, "CRST", "CRS", "", 0)
                time_map: dict[str, float] = {}
                for ident, vals in analytics.items():
                    total = vals.get("total")
                    secs = parse_time_seconds(total) if total else None
                    if secs is not None:
                        time_map[ident] = secs
                if not time_map and str(discipline).upper() != RELAY_DISCIPLINE:
                    for res in results:
                        ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
                        if not ident:
                            continue
                        course_val = get_first_time(res, ["TotalCourseTime", "CourseTime", "RunTime"])
                        secs = parse_time_seconds(course_val) if course_val else None
                        if secs is not None:
                            time_map[ident] = secs
                if time_map:
                    sorted_times = sorted(time_map.items(), key=lambda kv: kv[1])
                    for idx, (ident, _) in enumerate(sorted_times, start=1):
                        ski_ranks[ident] = idx

            matches: dict[str, str] = {}
            for res in results:
                ibuid = (res.get("IBUId") or "").lower()
                name = res.get("Name") or res.get("ShortName") or ""
                nat = res.get("Nat") or ""
                key = ibuid or name.lower()
                if args.ski:
                    rank_val = ski_ranks.get(res.get("IBUId") or res.get("Bib") or res.get("Name") or "", "")
                else:
                    rank_val = res.get("Rank") or res.get("ResultOrder") or res.get("Result") or ""
                include = False
                if args.id and ibuid and ibuid == args.id.lower():
                    include = True
                if args.search and args.search.lower() in name.lower():
                    include = True
                if include:
                    matches[key] = rank_val
                    if key not in athlete_map:
                        label = f"{name} ({nat})" if nat else name
                        athlete_map[key] = {"label": label, "nat": nat, "ibuid": ibuid or ""}
            if matches:
                race_entries.append({
                    "date": race_date,
                    "event": event_label or sport_evt.get("ShortDescription") or sport_evt.get("Organizer") or "",
                    "location": location_label or sport_evt.get("Organizer") or "",
                    "race": race_label,
                    "disc": discipline,
                    "race_id": race_id,
                    "matches": matches,
                })

    if args.id and args.id.lower() not in athlete_map:
        print(f"no results found for athlete id {args.id}", file=sys.stderr)
        return 1
    if args.search and not athlete_map:
        print(f"no athletes matched search '{args.search}'", file=sys.stderr)
        return 1

    athlete_keys = sorted(athlete_map.keys(), key=lambda k: athlete_map[k]["label"])
    headers = ["Date", "Event", "Location", "Race", "Discipline", "RaceId"] + [athlete_map[k]["label"] for k in athlete_keys]
    rows = []
    race_entries.sort(key=lambda r: r.get("date", ""), reverse=True)
    for entry in race_entries:
        row = [entry["date"], entry["event"], entry["location"], entry["race"], entry["disc"], entry["race_id"]]
        for key in athlete_keys:
            row.append(entry["matches"].get(key, ""))
        rows.append(row)

    print()
    print(f"# Athlete results — season {season_id}")
    render_table(headers, rows, pretty=is_pretty_output(args))
    print()
    return 0


def _find_athletes_by_search(season_id: str, levels: list[int], term: str) -> dict[str, dict]:
    matches: dict[str, dict] = {}
    for lvl in levels:
        for event in get_events(season_id, level=lvl):
            event_id = event.get("EventId")
            if not event_id:
                continue
            for race in get_races(event_id):
                race_id = race.get("RaceId") or race.get("Id")
                if not race_id:
                    continue
                try:
                    payload = get_race_results(race_id)
                except BiathlonError:
                    continue
                for res in extract_results(payload):
                    name = res.get("Name") or res.get("ShortName") or ""
                    if term.lower() in name.lower():
                        ident = res.get("IBUId")
                        if ident:
                            matches.setdefault(ident, {"name": name, "nat": res.get("Nat") or ""})
    return matches


def handle_athlete_id(args: argparse.Namespace) -> int:
    """Show IBU ids for athletes matching a search term."""
    if not args.search:
        print("error: provide --search", file=sys.stderr)
        return 1

    season_id = args.season or get_current_season_id()
    level_arg = getattr(args, "level", 0)
    levels = [level_arg] if level_arg in {1, 2, 3, 4, 5} else [1, 2, 3, 4, 5]
    matches: dict[str, dict] = {}
    search_term = args.search.strip()
    tokens = [tok for tok in search_term.split() if tok]
    family_name = tokens[-1] if tokens else search_term
    given_name = " ".join(tokens[:-1]) if len(tokens) > 1 else ""
    try:
        def add_matches(athletes: list[dict]) -> None:
            for athlete in athletes:
                if not isinstance(athlete, dict):
                    continue
                ibu_id = athlete.get("IBUId") or athlete.get("IbuId") or ""
                if not ibu_id:
                    continue
                given = athlete.get("GivenName") or ""
                family = athlete.get("FamilyName") or ""
                name = athlete.get("Name") or " ".join(part for part in [given, family] if part)
                nat = athlete.get("Nat") or athlete.get("Nation") or athlete.get("Country") or ""
                if not nat and isinstance(athlete.get("NF"), dict):
                    nat = athlete["NF"].get("Nat") or athlete["NF"].get("Country") or ""
                matches.setdefault(ibu_id, {"name": name or f"IBU {ibu_id}", "nat": nat})

        add_matches(get_athletes(family_name, given_name))
        if search_term and not given_name:
            add_matches(get_athletes(search_term, ""))
            add_matches(get_athletes("", search_term))
    except BiathlonError:
        matches = _find_athletes_by_search(season_id, levels, search_term)

    if not matches:
        print(f"no athletes matched search '{args.search}'", file=sys.stderr)
        return 1

    for ibu_id, meta in matches.items():
        if meta.get("nat"):
            continue
        try:
            bio = get_athlete_bio(ibu_id)
        except BiathlonError:
            continue
        nat = bio.get("NAT") or ""
        if nat:
            meta["nat"] = nat

    rows = []
    for ibu_id, meta in sorted(matches.items(), key=lambda item: item[1].get("name", "")):
        name = meta.get("name") or f"IBU {ibu_id}"
        rows.append([name, meta.get("nat", ""), ibu_id])

    print()
    print("# Athlete IBU ids")
    render_table(["Name", "Country", "IBUId"], rows, pretty=is_pretty_output(args))
    print()
    return 0


def handle_athlete_info(args: argparse.Namespace) -> int:
    """Show basic bio info for athletes."""
    if not args.id and not args.search:
        print("error: provide --id or --search", file=sys.stderr)
        return 1

    season_id = args.season or get_current_season_id()
    level_arg = getattr(args, "level", 0)
    levels = [level_arg] if level_arg in {1, 2, 3, 4, 5} else [1, 2, 3, 4, 5]

    requested: dict[str, dict] = {}
    if args.id:
        for part in args.id.split(","):
            ibu = part.strip()
            if ibu:
                requested[ibu] = {}
    if args.search:
        requested.update(_find_athletes_by_search(season_id, levels, args.search))

    if not requested:
        print("no athletes matched the provided criteria", file=sys.stderr)
        return 1

    rows = []
    for ibu_id, meta in requested.items():
        try:
            bio = get_athlete_bio(ibu_id)
        except BiathlonError:
            continue
        personal = {p.get("Description", "").lower(): p.get("Value") for p in bio.get("Personal", []) if p.get("Description")}
        age_val = bio.get("Age") or personal.get("age") or "-"
        if isinstance(age_val, str) and "," in age_val:
            age_val = age_val.split(",", 1)[0].strip()
        born_in = personal.get("born in", "-")
        residence = personal.get("residence", "-")
        profession = personal.get("profession", "-")
        name = bio.get("FullName") or meta.get("name") or f"IBU {ibu_id}"
        nat = bio.get("NAT") or meta.get("nat") or ""
        photo = bio.get("PhotoURI") or f"https://ibu.blob.core.windows.net/docs/athletes/{ibu_id}.png"
        rows.append([name, nat, age_val, born_in, residence, profession, photo, ibu_id])

    if not rows:
        print("no bios found", file=sys.stderr)
        return 1

    headers = ["Name", "Country", "Age", "BornIn", "Residence", "Profession", "Photo", "IBUId"]
    print()
    print("# Athlete info")
    render_table(headers, rows, pretty=is_pretty_output(args))
    print()
    return 0
