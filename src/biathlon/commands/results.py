"""Results command handlers."""

from __future__ import annotations

import argparse
import datetime
import sys

from ..api import (
    BiathlonError,
    get_analytic_results,
    get_cup_results,
    get_cups,
    get_current_season_id,
    get_race_results,
)
from ..constants import RELAY_DISCIPLINE, SHOOTING_STAGES, SINGLE_MIXED_RELAY_DISCIPLINE, SKI_LAPS
from ..formatting import Color, is_pretty_output, rank_style, render_table
from ..utils import (
    base_time_seconds,
    build_analytic_times,
    extract_results,
    format_race_header,
    get_first_time,
    is_dns,
    normalize_result_time,
    parse_misses,
    parse_time_seconds,
    sort_rows,
)


def _get_top_n_ibu_ids(cat_id: str, n: int, season_id: str = "") -> set[str]:
    """Return IBUIds of top N athletes in World Cup total standings.

    Args:
        cat_id: Category ID (SM for men, SW for women)
        n: Number of top athletes to include
        season_id: Optional season ID (defaults to current season)
    """
    if not season_id:
        season_id = get_current_season_id()

    # Find total standings cup (DisciplineId="TS", Level=1)
    cup_id = None
    for cup in get_cups(season_id):
        if cup.get("CatId") == cat_id and cup.get("DisciplineId") == "TS" and cup.get("Level") == 1:
            cup_id = cup.get("CupId")
            break

    if not cup_id:
        return set()

    # Get standings and return top N IBUIds
    try:
        payload = get_cup_results(cup_id)
    except BiathlonError:
        return set()

    rows = payload.get("Rows") or payload.get("Results") or []
    # Sort by rank to ensure proper ordering
    rows.sort(key=lambda r: int(r.get("Rank") or r.get("Score") or 9999) if str(r.get("Rank", "")).isdigit() else 9999)
    return {r.get("IBUId") for r in rows[:n] if r.get("IBUId")}


def _has_completed_results(payload: dict) -> bool:
    """Return True when a race payload contains completed, non-team results."""
    results = extract_results(payload)
    if not results:
        return False
    for res in results:
        rank = res.get("Rank")
        if rank is not None:
            rank_text = str(rank).strip()
            if rank_text and rank_text != "10000":
                return True
        result_val = res.get("Result") or res.get("TotalTime")
        if result_val:
            result_text = str(result_val).strip().upper()
            if result_text and result_text not in {"DNS", "-"}:
                return True
        if res.get("Time") or res.get("TotalTime") or res.get("Result"):
            if str(res.get("TotalTime") or res.get("Result") or "").strip() not in {"", "-", "DNS"}:
                return True
        irm = str(res.get("IRM") or "").strip().upper()
        if irm and irm not in {"OK", "DNS"}:
            return True
    return False


def _parse_start_datetime(value: str | None) -> datetime.datetime | None:
    """Parse a start time string into a datetime object."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        if "T" in text:
            return datetime.datetime.fromisoformat(text)
        return datetime.datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError:
        return None


def _find_latest_race_with_results(discipline_filter: str | None = None):
    """Return the most recent race id with completed results.

    Args:
        discipline_filter: Optional discipline code to filter by (e.g., "PU" for pursuit).
    """
    from ..api import get_current_season_id, get_events, get_races
    from ..utils import get_race_start_key
    now = datetime.datetime.utcnow()

    season_id = get_current_season_id()
    events = get_events(season_id, level=1)

    races: list[tuple[str, str, str]] = []
    for event in events:
        event_id = event.get("EventId")
        if not event_id:
            continue
        for race in get_races(event_id):
            start_key = get_race_start_key(race)
            race_id = race.get("RaceId") or race.get("Id") or ""
            discipline = str(race.get("DisciplineId") or "").upper()
            if race_id:
                races.append((start_key, race_id, discipline))

    races.sort(reverse=True)

    for start_key, race_id, discipline in races:
        if discipline_filter and discipline != discipline_filter:
            continue
        # Skip relay races (use 'biathlon relay' command instead)
        if discipline in (RELAY_DISCIPLINE, SINGLE_MIXED_RELAY_DISCIPLINE):
            continue
        try:
            payload = get_race_results(race_id)
        except BiathlonError:
            continue
        comp = payload.get("Competition") or {}
        start_raw = comp.get("StartTime") or start_key
        start_dt = _parse_start_datetime(start_raw if isinstance(start_raw, str) else None)
        if start_dt and start_dt > now:
            continue
        if _has_completed_results(payload):
            return race_id, payload

    discipline_label = f" {discipline_filter}" if discipline_filter else ""
    raise BiathlonError(f"No completed{discipline_label} races with results found")


def _resolve_race(args: argparse.Namespace) -> tuple[str, dict]:
    """Return race id and payload, defaulting to latest race with results."""
    if getattr(args, "race", ""):
        race_id = args.race
        payload = get_race_results(race_id)
    else:
        race_id, payload = _find_latest_race_with_results()
    return race_id, payload


def _get_discipline(payload: dict) -> str:
    """Return the discipline id for a race payload."""
    comp = payload.get("Competition") or {}
    return str(comp.get("DisciplineId") or "").upper()


def _format_race_error_label(payload: dict, race_id: str) -> str:
    """Return a descriptive label for error messages: 'Race Name (race_id)'."""
    comp = payload.get("Competition") or {}
    sport_evt = payload.get("SportEvt") or {}
    race_name = comp.get("ShortDescription") or comp.get("Description") or ""
    event_name = sport_evt.get("ShortDescription") or sport_evt.get("Organizer") or ""
    if race_name and event_name:
        label = f"{race_name} — {event_name}"
    elif race_name:
        label = race_name
    elif event_name:
        label = event_name
    else:
        label = ""
    if label:
        return f"{label} ({race_id})"
    return race_id


def handle_results(args: argparse.Namespace) -> int:
    """List results for a race (default: most recent race)."""
    race_id, payload = _resolve_race(args)

    # Exclude relay races (use 'biathlon relay' command instead)
    discipline = _get_discipline(payload)
    if discipline in (RELAY_DISCIPLINE, SINGLE_MIXED_RELAY_DISCIPLINE):
        print("relay races are not supported by this command (use 'biathlon relay' instead)", file=sys.stderr)
        return 1

    results = extract_results(payload)

    # Apply --top filter (top N in World Cup standings)
    top_n = getattr(args, "top", 0)
    if top_n > 0:
        cat_id = (payload.get("Competition") or {}).get("catId", "").upper()
        if cat_id in ("SM", "SW"):
            top_ibu_ids = _get_top_n_ibu_ids(cat_id, top_n)
            if top_ibu_ids:
                results = [r for r in results if r.get("IBUId") in top_ibu_ids]

    # Apply --first filter (first N finishers by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        results = results[:first_n]

    if not results:
        label = _format_race_error_label(payload, race_id)
        print(f"no results found for race {label}", file=sys.stderr)
        return 1
    base_secs = base_time_seconds(results)

    def collect_times(type_id: str, key: str, store: dict) -> None:
        try:
            analytic = get_analytic_results(race_id, type_id)
        except BiathlonError:
            return
        for res in analytic.get("Results", []):
            if res.get("IsTeam"):
                continue
            ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
            if not ident:
                continue
            store.setdefault(ident, {})[key] = get_first_time(res, ["TotalTime", "Result"])

    analytic_times: dict = {}
    collect_times("CRST", "course", analytic_times)
    collect_times("RNGT", "range", analytic_times)
    collect_times("STTM", "shooting", analytic_times)

    # Check if this is a pursuit race
    discipline = _get_discipline(payload)
    is_pursuit = discipline == "PU"

    rows = []
    for result in results:
        identifier = result.get("IBUId") or result.get("Bib") or result.get("Name")
        times = analytic_times.get(identifier, {})
        row = {
            "rank": result.get("Rank") or result.get("ResultOrder") or "",
            "name": result.get("Name") or result.get("ShortName") or "",
            "nat": result.get("Nat") or "",
            "start_position": result.get("StartOrder") or "-" if is_pursuit else None,
            "start_delay": result.get("StartInfo") or "-" if is_pursuit else None,
            "result": normalize_result_time(result, base_secs),
            "course": times.get("course") or get_first_time(result, ["TotalCourseTime", "CourseTime", "RunTime"]) or "-",
            "range": times.get("range") or get_first_time(result, ["TotalRangeTime", "RangeTime"]) or "-",
            "shooting": times.get("shooting") or get_first_time(result, ["TotalShootingTime", "ShootingTime"]) or "-",
            "misses": parse_misses(result.get("ShootingTotal")) or 0,
            "dns": is_dns(result),
        }
        rows.append(row)

    if args.sort:
        sort_col = args.sort.lower()
        if sort_col == "ski":
            sort_col = "course"
        if sort_col not in {"result", "course", "range", "shooting", "misses"}:
            print("error: sort must be one of result, ski, range, shooting, misses", file=sys.stderr)
            return 1
        if sort_col == "misses":
            def time_key(value: object) -> float:
                parsed = parse_time_seconds(str(value)) if value not in ("", None, "-") else None
                return parsed if parsed is not None else float("inf")

            def rank_key(value: object) -> int:
                try:
                    return int(str(value).strip())
                except (TypeError, ValueError):
                    return 10**9

            rows = sorted(
                rows,
                key=lambda row: (row.get("misses", 0), time_key(row.get("result")), rank_key(row.get("rank"))),
            )
        else:
            rows = sort_rows(rows, sort_col)

    # Apply --country filter
    country_filter = getattr(args, "country", "").upper()
    if country_filter:
        rows = [r for r in rows if r.get("nat", "").upper() == country_filter]

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    print(format_race_header(payload, race_id))
    show_sort_rank = bool(args.sort)
    sort_col_map = {"result": "Result", "ski": "Ski", "range": "Range", "shooting": "Shooting", "misses": "Misses"}
    if show_sort_rank:
        sort_col = args.sort.lower()
        sort_header = sort_col_map.get(sort_col, sort_col.capitalize())
        headers = [f"{sort_header}Rank", "Rank"]
    else:
        headers = ["Rank"]
    headers.extend(["Name", "Country"])
    if is_pursuit:
        headers.extend(["StartRank", "StartDelay"])
    headers.extend(["Result", "Ski", "Range", "Shooting", "Misses"])

    # Find index of sorted column header for highlighting
    highlight_headers = None
    if args.sort:
        sort_col = args.sort.lower()
        sort_header = sort_col_map.get(sort_col)
        if sort_header and sort_header in headers:
            highlight_headers = [headers.index(sort_header)]

    render_rows = []
    for idx, row in enumerate(rows, start=1):
        render_row = []
        if show_sort_rank:
            render_row.extend([idx, row["rank"]])
        else:
            render_row.append(row["rank"])
        render_row.extend([row["name"], row["nat"]])
        if is_pursuit:
            render_row.extend([row["start_position"], row["start_delay"]])
        render_row.extend([
            row["result"],
            row["course"],
            row["range"],
            row["shooting"],
            row["misses"],
        ])
        render_rows.append(render_row)
    row_styles = [rank_style(row["rank"]) for row in rows]
    render_table(headers, render_rows, pretty=is_pretty_output(args), row_styles=row_styles, highlight_headers=highlight_headers)
    return 0


def handle_results_remontada(args: argparse.Namespace) -> int:
    """Show pursuit remontada: biggest gains from start to finish rank."""
    if getattr(args, "race", ""):
        race_id = args.race
        payload = get_race_results(race_id)
    else:
        race_id, payload = _find_latest_race_with_results(discipline_filter="PU")

    discipline = _get_discipline(payload)
    if discipline != "PU":
        print(f"remontada is only available for pursuit races (got {discipline or 'unknown'})", file=sys.stderr)
        return 1

    results = extract_results(payload)

    # Apply --top filter (top N in World Cup standings)
    top_n = getattr(args, "top", 0)
    if top_n > 0:
        cat_id = (payload.get("Competition") or {}).get("catId", "").upper()
        if cat_id in ("SM", "SW"):
            top_ibu_ids = _get_top_n_ibu_ids(cat_id, top_n)
            if top_ibu_ids:
                results = [r for r in results if r.get("IBUId") in top_ibu_ids]

    # Apply --first filter (first N finishers by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        results = results[:first_n]

    if not results:
        label = _format_race_error_label(payload, race_id)
        print(f"no results found for race {label}", file=sys.stderr)
        return 1

    def as_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    rows = []
    for res in results:
        status = str(res.get("IRM") or "").upper()
        start_rank = as_int(res.get("StartOrder") or res.get("StartPosition") or res.get("StartRow"))
        finish_rank = as_int(res.get("Rank") or res.get("ResultOrder"))
        name = res.get("Name") or res.get("ShortName") or ""
        nat = res.get("Nat") or ""

        if status and status not in {"OK", ""}:
            rows.append({
                "diff": None, "start": start_rank, "finish": status or finish_rank,
                "name": name, "nat": nat, "status": status,
            })
            continue

        if start_rank is None or finish_rank is None:
            continue
        diff = start_rank - finish_rank
        rows.append({
            "diff": diff, "start": start_rank, "finish": finish_rank,
            "name": name, "nat": nat, "status": "",
        })

    if not rows:
        print("no start/finish ranks available for remontada", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: (
        1 if r["diff"] is None else 0,
        0 if r["diff"] is None else -r["diff"],
        r.get("finish") if isinstance(r.get("finish"), int) else 9999,
        r["name"],
    ))

    # Apply --country filter
    country_filter = getattr(args, "country", "").upper()
    if country_filter:
        rows = [r for r in rows if r.get("nat", "").upper() == country_filter]

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    print(format_race_header(payload, race_id))
    headers = ["Rank", "Name", "Country", "Gain", "StartRank", "FinishRank"]
    pretty = is_pretty_output(args)

    # Find max gain for scaling colors
    max_gain = max((abs(r["diff"]) for r in rows if r["diff"] is not None), default=1)

    render_rows = []
    for rank, row in enumerate(rows, start=1):
        diff = row["diff"]
        status = row.get("status", "")
        if diff is None:
            gain_val = status or "-"
        else:
            gain_val = f"+{diff}" if diff > 0 else str(diff)
        render_rows.append([rank, row["name"], row["nat"], gain_val, row["start"], row["finish"]])

    def rank_color_formatter(cell_str: str, row_idx: int) -> str:
        """Apply ranking colors based on finish position."""
        if not Color.enabled():
            return cell_str
        row = rows[row_idx]
        if row["diff"] is None:  # DNF/DNS
            return Color.dim(cell_str)
        finish = row["finish"]
        style = rank_style(finish)
        if style == "gold":
            return Color.gold(cell_str)
        elif style == "silver":
            return Color.silver(cell_str)
        elif style == "bronze":
            return Color.bronze(cell_str)
        elif style == "flowers":
            return Color.flowers(cell_str)
        elif style == "other":
            return Color.other(cell_str)
        return cell_str

    def gain_formatter(cell_str: str, row_idx: int) -> str:
        if not Color.enabled():
            return cell_str
        row = rows[row_idx]
        diff = row["diff"]
        if diff is None:
            return Color.dim(cell_str)
        intensity = abs(diff) / max_gain if max_gain > 0 else 0
        if diff > 0:
            return Color.green(cell_str, intensity)
        elif diff < 0:
            return Color.red(cell_str, intensity)
        return cell_str

    cell_formatters = [rank_color_formatter, rank_color_formatter, rank_color_formatter, gain_formatter, gain_formatter, gain_formatter] if pretty else None
    render_table(headers, render_rows, pretty=pretty, cell_formatters=cell_formatters)
    return 0


def handle_results_ski(args: argparse.Namespace) -> int:
    """Show ski/course time breakdown for a race."""
    race_id, payload = _resolve_race(args)
    results = extract_results(payload)

    # Apply --top filter (top N in World Cup standings)
    top_n = getattr(args, "top", 0)
    if top_n > 0:
        cat_id = (payload.get("Competition") or {}).get("catId", "").upper()
        if cat_id in ("SM", "SW"):
            top_ibu_ids = _get_top_n_ibu_ids(cat_id, top_n)
            if top_ibu_ids:
                results = [r for r in results if r.get("IBUId") in top_ibu_ids]

    # Apply --first filter (first N finishers by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        results = results[:first_n]

    if not results:
        label = _format_race_error_label(payload, race_id)
        print(f"no results found for race {label}", file=sys.stderr)
        return 1

    discipline = _get_discipline(payload)
    is_pursuit = discipline == "PU"
    if discipline == RELAY_DISCIPLINE:
        print(format_race_header(payload, race_id))
        print("(relay course breakdown not supported yet)")
        return 0

    laps = SKI_LAPS.get(discipline)
    if not laps:
        print(format_race_header(payload, race_id))
        print(f"(discipline {discipline or 'unknown'} not supported for course breakdown)")
        return 0

    show_result = discipline != "SP"
    include_ski_col = discipline == "IN"

    analytics = build_analytic_times(race_id, "CRST", "CRS", "", laps)
    ski_times = build_analytic_times(race_id, "SKIT", "SKI", "T", 0) if include_ski_col else {}
    base_secs = base_time_seconds(results)

    rows = []
    for res in results:
        ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
        row_times = analytics.get(ident, {})
        ski_total = ski_times.get(ident, {}).get("total", "-") if include_ski_col else "-"
        course_total = row_times.get("total", "-")
        lap_values = [row_times.get(f"lap{i}", "-") for i in range(1, laps + 1)]
        position = res.get("Rank") or res.get("ResultOrder") or ""
        row = {
            "dns": is_dns(res),
            "position": position,
            "name": res.get("Name") or res.get("ShortName") or "",
            "nat": res.get("Nat") or "",
            "start_position": res.get("StartOrder") or "-" if is_pursuit else None,
            "start_delay": res.get("StartInfo") or "-" if is_pursuit else None,
            "course": course_total,
            "ski_col": ski_total,
        }
        if show_result:
            row["result"] = normalize_result_time(res, base_secs)
        for i, lap_val in enumerate(lap_values, start=1):
            row[f"lap{i}"] = lap_val
        rows.append(row)

    col_names = []
    if show_result:
        col_names.append("result")
    if include_ski_col:
        col_names.append("ski")
    col_names.append("course")
    col_names.extend([f"lap{i}" for i in range(1, laps + 1)])

    sort_col = args.sort.lower() if args.sort else "course"
    if sort_col == "ski" and not include_ski_col:
        sort_col = "course"
    if sort_col not in col_names:
        print(f"error: sort must be one of {', '.join(col_names)}", file=sys.stderr)
        return 1
    rows = sort_rows(rows, sort_col)

    # Assign ski rank after sorting
    for ski_rank, row in enumerate(rows, start=1):
        row["ski_rank"] = ski_rank

    # Apply --country filter
    country_filter = getattr(args, "country", "").upper()
    if country_filter:
        rows = [r for r in rows if r.get("nat", "").upper() == country_filter]

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    # Build headers and render rows
    sort_col_map = {"course": "Ski", "ski": "SkiTime", "result": "Result"}
    sort_header = sort_col_map.get(sort_col, sort_col.capitalize())
    rank_col_name = f"{sort_header}Rank"

    headers = [rank_col_name, "Position", "Name", "Country"]
    if is_pursuit:
        headers.extend(["StartPosition", "StartDelay"])
    if show_result:
        headers.append("Result")
    if include_ski_col:
        headers.append("SkiTime")
    headers.append("Ski")
    headers.extend([f"Lap{i}" for i in range(1, laps + 1)])

    # Find index of sorted column header for highlighting
    highlight_headers = None
    if sort_header in headers:
        highlight_headers = [headers.index(sort_header)]

    render_rows = []
    for row in rows:
        render_row = [row["ski_rank"], row["position"], row["name"], row["nat"]]
        if is_pursuit:
            render_row.extend([row["start_position"], row["start_delay"]])
        if show_result:
            render_row.append(row["result"])
        if include_ski_col:
            render_row.append(row["ski_col"])
        render_row.append(row["course"])
        render_row.extend([row[f"lap{i}"] for i in range(1, laps + 1)])
        render_rows.append(render_row)

    print(format_race_header(payload, race_id))
    row_styles = [rank_style(row["position"]) for row in rows]
    render_table(
        headers,
        render_rows,
        pretty=is_pretty_output(args),
        row_styles=row_styles,
        highlight_headers=highlight_headers,
    )
    return 0


def handle_results_range(args: argparse.Namespace) -> int:
    """Show range time breakdown for a race."""
    race_id, payload = _resolve_race(args)
    results = extract_results(payload)

    # Apply --top filter (top N in World Cup standings)
    top_n = getattr(args, "top", 0)
    if top_n > 0:
        cat_id = (payload.get("Competition") or {}).get("catId", "").upper()
        if cat_id in ("SM", "SW"):
            top_ibu_ids = _get_top_n_ibu_ids(cat_id, top_n)
            if top_ibu_ids:
                results = [r for r in results if r.get("IBUId") in top_ibu_ids]

    # Apply --first filter (first N finishers by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        results = results[:first_n]

    if not results:
        label = _format_race_error_label(payload, race_id)
        print(f"no results found for race {label}", file=sys.stderr)
        return 1

    discipline = _get_discipline(payload)
    if discipline == RELAY_DISCIPLINE:
        print(format_race_header(payload, race_id))
        print("(relay range breakdown not supported yet)")
        return 0

    laps = SHOOTING_STAGES.get(discipline)
    if not laps:
        print(format_race_header(payload, race_id))
        print(f"(discipline {discipline or 'unknown'} not supported for range breakdown)")
        return 0

    analytics = build_analytic_times(race_id, "RNGT", "RNG", "", laps)

    rows = []
    for res in results:
        ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
        row_times = analytics.get(ident, {})
        range_total = row_times.get("total", "-")
        lap_values = [row_times.get(f"lap{i}", "-") for i in range(1, laps + 1)]
        row = {
            "dns": is_dns(res),
            "position": res.get("Rank") or res.get("ResultOrder") or "",
            "name": res.get("Name") or res.get("ShortName") or "",
            "nat": res.get("Nat") or "",
            "range": range_total,
        }
        for i, lap_val in enumerate(lap_values, start=1):
            row[f"lap{i}"] = lap_val
        rows.append(row)

    # Determine sort column
    col_names = ["range"] + [f"lap{i}" for i in range(1, laps + 1)]
    sort_col = args.sort.lower() if args.sort else "range"
    if sort_col not in col_names:
        print(f"error: sort must be one of {', '.join(col_names)}", file=sys.stderr)
        return 1
    rows = sort_rows(rows, sort_col)

    # Assign rank after sorting
    for rank, row in enumerate(rows, start=1):
        row["sort_rank"] = rank

    # Apply --country filter
    country_filter = getattr(args, "country", "").upper()
    if country_filter:
        rows = [r for r in rows if r.get("nat", "").upper() == country_filter]

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    # Build headers
    sort_col_map = {"range": "Range"}
    sort_header = sort_col_map.get(sort_col, sort_col.capitalize())
    rank_col_name = f"{sort_header}Rank"

    headers = [rank_col_name, "Position", "Name", "Country", "Range"]
    headers.extend([f"Lap{i}" for i in range(1, laps + 1)])

    # Find index of sorted column header for highlighting
    highlight_headers = None
    if sort_header in headers:
        highlight_headers = [headers.index(sort_header)]

    # Build render rows
    render_rows = []
    for row in rows:
        render_row = [row["sort_rank"], row["position"], row["name"], row["nat"], row["range"]]
        render_row.extend([row[f"lap{i}"] for i in range(1, laps + 1)])
        render_rows.append(render_row)

    print(format_race_header(payload, race_id))
    row_styles = [rank_style(row["position"]) for row in rows]
    render_table(
        headers,
        render_rows,
        pretty=is_pretty_output(args),
        row_styles=row_styles,
        highlight_headers=highlight_headers,
    )
    return 0


def handle_results_shooting(args: argparse.Namespace) -> int:
    """Show shooting time breakdown for a race."""
    race_id, payload = _resolve_race(args)
    results = extract_results(payload)

    # Apply --top filter (top N in World Cup standings)
    top_n = getattr(args, "top", 0)
    if top_n > 0:
        cat_id = (payload.get("Competition") or {}).get("catId", "").upper()
        if cat_id in ("SM", "SW"):
            top_ibu_ids = _get_top_n_ibu_ids(cat_id, top_n)
            if top_ibu_ids:
                results = [r for r in results if r.get("IBUId") in top_ibu_ids]

    # Apply --first filter (first N finishers by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        results = results[:first_n]

    if not results:
        label = _format_race_error_label(payload, race_id)
        print(f"no results found for race {label}", file=sys.stderr)
        return 1

    discipline = _get_discipline(payload)
    if discipline == RELAY_DISCIPLINE:
        print(format_race_header(payload, race_id))
        print("(relay shooting breakdown not supported yet)")
        return 0

    laps = SHOOTING_STAGES.get(discipline, 4)

    analytics = build_analytic_times(race_id, "STTM", "S", "TM", laps)

    def parse_miss_list(shootings: str | None, count: int) -> list[str]:
        if not shootings:
            return ["-"] * count
        parts = shootings.split("+")
        misses = []
        for part in parts[:count]:
            try:
                misses.append(str(int(part)))
            except ValueError:
                misses.append("-")
        while len(misses) < count:
            misses.append("-")
        return misses

    rows = []
    for res in results:
        ident = res.get("IBUId") or res.get("Bib") or res.get("Name")
        row_times = analytics.get(ident, {})
        shooting_total = row_times.get("total", "-")
        lap_values = [row_times.get(f"lap{i}", "-") for i in range(1, laps + 1)]
        misses_total = parse_misses(res.get("ShootingTotal")) or 0
        misses_list = parse_miss_list(res.get("Shootings"), 4)
        while len(lap_values) < 4:
            lap_values.append("-")
        row = {
            "dns": is_dns(res),
            "position": res.get("Rank") or res.get("ResultOrder") or "",
            "name": res.get("Name") or res.get("ShortName") or "",
            "nat": res.get("Nat") or "",
            "shooting": shooting_total,
            "misses": misses_total,
        }
        for i in range(4):
            row[f"lap{i+1}"] = lap_values[i]
            row[f"miss{i+1}"] = misses_list[i]
        rows.append(row)

    # Determine sort column
    time_cols = ["shooting"] + [f"lap{i}" for i in range(1, 5)]
    miss_cols = ["misses"] + [f"miss{i}" for i in range(1, 5)]
    col_names = time_cols + miss_cols
    sort_col = args.sort.lower() if args.sort else "shooting"
    if sort_col not in col_names:
        print(f"error: sort must be one of {', '.join(col_names)}", file=sys.stderr)
        return 1

    # Sort rows - for miss columns, use position as secondary sort
    if sort_col in miss_cols:
        def miss_sort_key(row):
            val = row.get(sort_col)
            try:
                miss_val = int(str(val).strip()) if val not in ("", None, "-") else float("inf")
            except (TypeError, ValueError):
                miss_val = float("inf")
            try:
                pos_val = int(str(row.get("position", "")).strip())
            except (TypeError, ValueError):
                pos_val = 10**9
            return (miss_val, pos_val)
        rows = sorted(rows, key=miss_sort_key)
    else:
        rows = sort_rows(rows, sort_col)

    # Assign rank after sorting
    for rank, row in enumerate(rows, start=1):
        row["sort_rank"] = rank

    # Apply --country filter
    country_filter = getattr(args, "country", "").upper()
    if country_filter:
        rows = [r for r in rows if r.get("nat", "").upper() == country_filter]

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    # Build headers
    sort_col_map = {"shooting": "Shooting", "misses": "Misses"}
    sort_header = sort_col_map.get(sort_col, sort_col.capitalize())
    rank_col_name = f"{sort_header}Rank"

    headers = [
        rank_col_name, "Position", "Name", "Country", "Shooting", "Misses",
        "Lap1", "Miss1", "Lap2", "Miss2", "Lap3", "Miss3", "Lap4", "Miss4",
    ]

    # Find index of sorted column header for highlighting
    highlight_headers = None
    if sort_header in headers:
        highlight_headers = [headers.index(sort_header)]

    # Build render rows
    render_rows = []
    for row in rows:
        render_row = [
            row["sort_rank"], row["position"], row["name"], row["nat"],
            row["shooting"], row["misses"],
            row["lap1"], row["miss1"],
            row["lap2"], row["miss2"],
            row["lap3"], row["miss3"],
            row["lap4"], row["miss4"],
        ]
        render_rows.append(render_row)

    print(format_race_header(payload, race_id))
    row_styles = [rank_style(row["position"]) for row in rows]
    render_table(
        headers,
        render_rows,
        pretty=is_pretty_output(args),
        row_styles=row_styles,
        highlight_headers=highlight_headers,
    )
    return 0
