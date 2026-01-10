"""Relay command handler."""

from __future__ import annotations

import argparse
import datetime
import sys

from ..api import BiathlonError, get_current_season_id, get_events, get_races, get_race_results
from ..constants import (
    RELAY_DISCIPLINE,
    RELAY_MEN_CAT,
    RELAY_MIXED_CAT,
    RELAY_WOMEN_CAT,
    SINGLE_MIXED_RELAY_DISCIPLINE,
)
from ..formatting import is_pretty_output, rank_style, render_table
from ..utils import format_race_header, get_race_start_key, parse_misses, parse_time_seconds


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


def _has_completed_results(payload: dict) -> bool:
    """Return True when a race payload contains completed results."""
    results = payload.get("Results", [])
    if not results:
        return False
    for res in results:
        if not res.get("IsTeam"):
            continue
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
    return False


def _find_latest_relay_race(
    discipline: str,
    category: str,
) -> tuple[str, dict]:
    """Find the most recent completed relay race.

    Args:
        discipline: Discipline code (RL or SR)
        category: Category code (SW, SM, or MX)
    """
    now = datetime.datetime.utcnow()
    season_id = get_current_season_id()
    events = get_events(season_id, level=1)

    races: list[tuple[str, str, str, str]] = []
    for event in events:
        event_id = event.get("EventId")
        if not event_id:
            continue
        for race in get_races(event_id):
            start_key = get_race_start_key(race)
            race_id = race.get("RaceId") or race.get("Id") or ""
            race_disc = str(race.get("DisciplineId") or "").upper()
            race_cat = str(race.get("catId") or race.get("CatId") or "").upper()
            if race_id:
                races.append((start_key, race_id, race_disc, race_cat))

    races.sort(reverse=True)

    for start_key, race_id, race_disc, race_cat in races:
        if race_disc != discipline or race_cat != category:
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

    # Build descriptive label for error message
    if discipline == SINGLE_MIXED_RELAY_DISCIPLINE:
        relay_type = "single mixed relay"
    elif category == RELAY_MIXED_CAT:
        relay_type = "mixed relay"
    elif category == RELAY_MEN_CAT:
        relay_type = "men relay"
    else:
        relay_type = "women relay"

    raise BiathlonError(f"No completed {relay_type} races with results found")


def handle_relay(args: argparse.Namespace) -> int:
    """Show relay race results."""
    # Determine discipline and category based on flags
    if getattr(args, "singlemixed", False):
        discipline = SINGLE_MIXED_RELAY_DISCIPLINE
        category = RELAY_MIXED_CAT
    elif getattr(args, "mixed", False):
        discipline = RELAY_DISCIPLINE
        category = RELAY_MIXED_CAT
    elif getattr(args, "men", False):
        discipline = RELAY_DISCIPLINE
        category = RELAY_MEN_CAT
    else:
        # Default: women relay
        discipline = RELAY_DISCIPLINE
        category = RELAY_WOMEN_CAT

    # Find or use specified race
    if getattr(args, "race", ""):
        race_id = args.race
        payload = get_race_results(race_id)
    else:
        race_id, payload = _find_latest_relay_race(discipline, category)

    results = payload.get("Results", [])
    if not results:
        print(f"no results found for race {race_id}", file=sys.stderr)
        return 1

    # Separate team results and leg results
    team_results = [r for r in results if r.get("IsTeam")]
    leg_results = [r for r in results if not r.get("IsTeam")]

    # Sort team results by rank
    def team_sort_key(r: dict) -> tuple:
        rank = r.get("Rank") or r.get("ResultOrder") or 9999
        try:
            return (0, int(rank))
        except (TypeError, ValueError):
            return (1, str(rank))

    team_results.sort(key=team_sort_key)

    # Apply --first filter (first N teams by race position)
    first_n = getattr(args, "first", 0)
    if first_n > 0:
        team_results = team_results[:first_n]

    # Group leg results by team (using Bib as team identifier)
    legs_by_bib: dict[str, list[dict]] = {}
    for leg in leg_results:
        bib = str(leg.get("Bib") or "")
        if bib:
            legs_by_bib.setdefault(bib, []).append(leg)

    # Sort legs within each team by leg number
    for bib in legs_by_bib:
        legs_by_bib[bib].sort(key=lambda x: x.get("Leg", 0))

    # Determine number of legs (usually 4, but single mixed is 4 too - 2 women + 2 men)
    num_legs = 4

    # Build output rows
    rows = []
    for team in team_results:
        bib = str(team.get("Bib") or "")
        team_rank = team.get("Rank") or team.get("ResultOrder") or ""
        team_name = team.get("Name") or team.get("ShortName") or ""
        nat = team.get("Nat") or ""
        total_time = team.get("TotalTime") or team.get("Result") or "-"
        behind = team.get("Behind") or ""
        shootings = team.get("ShootingTotal") or ""
        misses = parse_misses(shootings) or 0

        # Get leg athletes
        team_legs = legs_by_bib.get(bib, [])
        leg_names = []
        leg_cumulative_times = []  # Cumulative times from API
        leg_behinds = []
        leg_misses = []
        leg_ranks = []
        for i in range(1, num_legs + 1):
            leg_data = next((l for l in team_legs if l.get("Leg") == i), None)
            if leg_data:
                name = leg_data.get("ShortName") or leg_data.get("Name") or "-"
                leg_time = leg_data.get("TotalTime") or "-"
                leg_behind = leg_data.get("Behind") or "-"
                leg_miss = parse_misses(leg_data.get("ShootingTotal")) or 0
                leg_rank = leg_data.get("LegRank") or "-"
                leg_names.append(name)
                leg_cumulative_times.append(leg_time)
                leg_behinds.append(leg_behind)
                leg_misses.append(leg_miss)
                leg_ranks.append(leg_rank)
            else:
                leg_names.append("-")
                leg_cumulative_times.append("-")
                leg_behinds.append("-")
                leg_misses.append("-")
                leg_ranks.append("-")

        # Calculate individual leg times (delta from previous leg)
        leg_times = []
        for i in range(num_legs):
            curr_time = parse_time_seconds(leg_cumulative_times[i]) if leg_cumulative_times[i] != "-" else None
            if i == 0:
                # First leg: use cumulative time as-is
                leg_times.append(leg_cumulative_times[i])
            else:
                prev_time = parse_time_seconds(leg_cumulative_times[i - 1]) if leg_cumulative_times[i - 1] != "-" else None
                if curr_time is not None and prev_time is not None:
                    delta = curr_time - prev_time
                    # Format as mm:ss.t
                    minutes = int(delta // 60)
                    secs = delta - minutes * 60
                    leg_times.append(f"{minutes}:{secs:04.1f}")
                else:
                    leg_times.append("-")

        row = {
            "rank": team_rank,
            "name": team_name,
            "nat": nat,
            "total": total_time,
            "behind": behind,
            "misses": misses,
        }
        for i in range(num_legs):
            row[f"leg{i+1}_name"] = leg_names[i]
            row[f"leg{i+1}_time"] = leg_times[i]
            row[f"leg{i+1}_behind"] = leg_behinds[i]
            row[f"leg{i+1}_miss"] = leg_misses[i]
            row[f"leg{i+1}_rank"] = leg_ranks[i]
        rows.append(row)

    # Column name mapping (header -> row key)
    col_map = {
        "time": "total",
        "behind": "behind",
        "misses": "misses",
    }
    for i in range(1, num_legs + 1):
        # New column names: Time1, B1, M1
        col_map[f"time{i}"] = f"leg{i}_time"
        col_map[f"b{i}"] = f"leg{i}_behind"
        col_map[f"m{i}"] = f"leg{i}_miss"

    # Handle --sort
    sort_col = getattr(args, "sort", "").lower()
    show_sort_rank = False
    sort_rank_header = "Rank"
    if sort_col:
        row_key = col_map.get(sort_col)
        if not row_key:
            valid_cols = ["time", "behind", "misses"]
            for i in range(1, num_legs + 1):
                valid_cols.extend([f"Time{i}", f"B{i}", f"M{i}"])
            print(f"error: sort must be one of {', '.join(valid_cols)}", file=sys.stderr)
            return 1

        # Determine sort rank header name
        sort_col_map = {
            "time": "Time", "behind": "Behind", "misses": "Misses",
        }
        for i in range(1, num_legs + 1):
            sort_col_map[f"time{i}"] = f"Time{i}"
            sort_col_map[f"b{i}"] = f"B{i}"
            sort_col_map[f"m{i}"] = f"M{i}"
        sort_header = sort_col_map.get(sort_col, sort_col.capitalize())
        sort_rank_header = f"{sort_header}Rank"

        # Sort by the specified column
        if row_key == "misses" or row_key.endswith("_miss"):
            # Sort by misses (numeric), then by original rank
            def sort_key(r: dict) -> tuple:
                miss_val = r.get(row_key, 0)
                try:
                    miss_val = int(miss_val) if miss_val not in ("", None, "-") else 9999
                except (TypeError, ValueError):
                    miss_val = 9999
                try:
                    rank_val = int(r.get("rank", 9999))
                except (TypeError, ValueError):
                    rank_val = 9999
                return (miss_val, rank_val)
            rows = sorted(rows, key=sort_key)
        else:
            # Sort by time column
            def sort_key(r: dict) -> tuple:
                val = r.get(row_key)
                sec = parse_time_seconds(str(val)) if val not in ("", None, "-") else None
                if sec is None:
                    return (1, float("inf"))
                return (0, sec)
            rows = sorted(rows, key=sort_key)

        # Assign sort rank
        for idx, row in enumerate(rows, start=1):
            row["sort_rank"] = idx
        show_sort_rank = True

    # Apply --limit
    limit_n = getattr(args, "limit", 25)
    if limit_n > 0:
        rows = rows[:limit_n]

    # Build headers and render
    print(format_race_header(payload, race_id))
    show_detail = getattr(args, "detail", False)
    show_time = getattr(args, "time", False) or show_detail
    show_behind = getattr(args, "behind", False) or show_detail
    show_miss = getattr(args, "miss", False) or show_detail
    show_leg_details = show_time or show_behind or show_miss

    if show_sort_rank:
        headers = [sort_rank_header, "FinalRank", "Team", "Country", "Time", "Behind", "Misses"]
    else:
        headers = ["Rank", "Team", "Country", "Time", "Behind", "Misses"]
    if show_leg_details:
        for i in range(1, num_legs + 1):
            headers.append(f"Biathlete{i}")
            if show_time:
                headers.append(f"Time{i}")
            if show_behind and i < num_legs:  # Skip Behind for last leg (same as main)
                headers.append(f"B{i}")
            if show_miss:
                headers.append(f"M{i}")

    # Find index of sorted column header for highlighting
    highlight_headers = None
    if show_sort_rank:
        sort_header = sort_col_map.get(sort_col)
        if sort_header and sort_header in headers:
            highlight_headers = [headers.index(sort_header)]

    render_rows = []
    for row in rows:
        if show_sort_rank:
            render_row = [
                row["sort_rank"],
                row["rank"],
                row["name"],
                row["nat"],
                row["total"],
                row["behind"],
                row["misses"],
            ]
        else:
            render_row = [
                row["rank"],
                row["name"],
                row["nat"],
                row["total"],
                row["behind"],
                row["misses"],
            ]
        if show_leg_details:
            for i in range(1, num_legs + 1):
                render_row.append(row[f"leg{i}_name"])
                if show_time:
                    render_row.append(row[f"leg{i}_time"])
                if show_behind and i < num_legs:  # Skip Behind for last leg (same as main)
                    render_row.append(row[f"leg{i}_behind"])
                if show_miss:
                    render_row.append(row[f"leg{i}_miss"])
        render_rows.append(render_row)

    row_styles = [rank_style(row["rank"]) for row in rows]
    render_table(headers, render_rows, pretty=is_pretty_output(args), row_styles=row_styles, highlight_headers=highlight_headers)
    return 0
