"""CLI entry point for Biathlon results."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from importlib.metadata import version, PackageNotFoundError

from .api import BiathlonError


def get_version() -> str:
    """Get package version."""
    try:
        return version("biathlon")
    except PackageNotFoundError:
        return "dev"


from .commands import (
    handle_athlete_info,
    handle_athlete_results,
    handle_ceremony,
    handle_cumulate_course,
    handle_cumulate_miss,
    handle_cumulate_penalty,
    handle_cumulate_range,
    handle_cumulate_remontada,
    handle_cumulate_shooting,
    handle_cumulate_ski,
    handle_events,
    handle_record_lap,
    handle_relay,
    handle_results,
    handle_results_range,
    handle_results_remontada,
    handle_results_shooting,
    handle_results_ski,
    handle_scores,
    handle_seasons,
    handle_shooting,
)


class CompactOptionalFormatter(argparse.HelpFormatter):
    """Formatter that groups optional flags before their metavar."""

    def __init__(self, prog: str, indent_increment: int = 2, max_help_position: int = 40, width: int | None = None) -> None:
        super().__init__(prog, indent_increment, max_help_position, width)

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return super()._format_action_invocation(action)
        opts = ", ".join(action.option_strings)
        if action.nargs != 0:
            opts += f" {self._format_args(action, action.dest.upper())}"
        return opts

    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            parts = []
            subactions = list(action._get_subactions())
            self._indent()
            for subaction in subactions:
                if not subaction.help:
                    continue
                parts.append(super()._format_action(subaction))
            self._dedent()
            return "".join(parts)
        return super()._format_action(action)


def traverse_to_parser(
    parser: argparse.ArgumentParser,
    tokens: list[str],
) -> tuple[argparse.ArgumentParser, list[str]]:
    """Traverse subparsers to the deepest matching parser."""
    if not parser._subparsers:
        return parser, tokens
    subparsers_action = None
    for action in parser._subparsers._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            break
    if not subparsers_action or not tokens:
        return parser, tokens
    command = tokens[0]
    choices = subparsers_action.choices
    if command not in choices:
        return parser, tokens
    return traverse_to_parser(choices[command], tokens[1:])


BASH_COMPLETION = '''
_biathlon_completion() {
    local cur prev commands subcommands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    commands="seasons events results cumulate record standings ceremony biathlete shooting relay"

    case "${COMP_WORDS[1]}" in
        results)
            subcommands="remontada ski range shooting"
            ;;
        cumulate)
            subcommands="course ski range shooting miss remontada"
            ;;
        record)
            subcommands="lap"
            ;;
        biathlete)
            subcommands="info results"
            ;;
        *)
            subcommands=""
            ;;
    esac

    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )
    elif [[ ${COMP_CWORD} -eq 2 && -n "${subcommands}" ]]; then
        COMPREPLY=( $(compgen -W "${subcommands}" -- ${cur}) )
    elif [[ ${cur} == -* ]]; then
        local opts="--help --tsv --men --season --race --event"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
    fi
}
complete -F _biathlon_completion biathlon
'''

ZSH_COMPLETION = '''
#compdef biathlon

_biathlon() {
    local -a commands subcommands
    commands=(
        'seasons:List available seasons'
        'events:List events'
        'results:Show race results'
        'cumulate:Cumulative statistics'
        'record:Record lists'
        'standings:Cup standings'
        'ceremony:Medal ranking'
        'biathlete:Biathlete information'
        'shooting:Shooting accuracy'
        'relay:Relay race results'
    )

    _arguments -C \\
        '1: :->command' \\
        '*: :->args'

    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[2] in
                results)
                    _values 'subcommand' remontada ski range shooting
                    ;;
                cumulate)
                    _values 'subcommand' course ski range shooting miss remontada
                    ;;
                record)
                    _values 'subcommand' lap
                    ;;
                biathlete)
                    _values 'subcommand' info results
                    ;;
            esac
            ;;
    esac
}

_biathlon "$@"
'''


def print_completion(shell: str) -> int:
    """Print shell completion script and exit."""
    if shell == "bash":
        print(BASH_COMPLETION.strip())
    elif shell == "zsh":
        print(ZSH_COMPLETION.strip())
    else:
        print(f"Unknown shell: {shell}. Use 'bash' or 'zsh'.", file=sys.stderr)
        return 1
    return 0


def add_output_flag(subparser: argparse.ArgumentParser) -> None:
    """Add --tsv flag to a subparser."""
    subparser.add_argument(
        "--tsv",
        action="store_true",
        help="Output TSV instead of aligned table",
    )


def add_cumulate_args(subparser: argparse.ArgumentParser) -> None:
    """Add common cumulate arguments to a subparser."""
    subparser.add_argument(
        "--men",
        action="store_true",
        help="Show men (default: women)",
    )
    subparser.add_argument(
        "--discipline",
        "-d",
        default="all",
        choices=["individual", "sprint", "pursuit", "mass-start", "all"],
        metavar="DISCIPLINE",
        help="Race discipline (default: all, accepted options: individual, sprint, pursuit, mass-start, all)",
    )
    subparser.add_argument(
        "--season",
        "-s",
        default="",
        help="Season id (default: current season)",
    )
    subparser.add_argument(
        "--event",
        "-e",
        default="",
        help="Cumulate races from given event (overrides --discipline and --season)",
    )
    subparser.add_argument(
        "--position",
        "-p",
        action="store_true",
        help="Rank by average position instead of cumulative time",
    )
    subparser.add_argument(
        "--no-sprint-delay",
        action="store_true",
        help="For pursuit races, cumulate pursuit time without start delay based on sprint results",
    )
    subparser.add_argument(
        "--min-race",
        type=int,
        default=0,
        help="Minimum races required (when using --position)",
    )
    subparser.add_argument(
        "--top",
        type=int,
        default=0,
        help="Filter to top N athletes in WC standings",
    )
    subparser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=25,
        help="Number of rows to display (default: 25, 0 for all)",
    )
    subparser.add_argument(
        "--debug-races",
        action="store_true",
        help="Debug: print races considered",
    )
    subparser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse sort order (highest first)",
    )
    add_output_flag(subparser)


def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="biathlon",
        description="CLI for exploring IBU biathlon results",
        usage="biathlon command [subcommand] ...",
        add_help=False,
        formatter_class=CompactOptionalFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- seasons ---
    seasons_parser = subparsers.add_parser(
        "seasons",
        help="List seasons",
        formatter_class=CompactOptionalFormatter,
        add_help=False,
    )
    seasons_parser.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(seasons_parser)
    seasons_parser.set_defaults(func=handle_seasons)

    # --- events ---
    events_parser = subparsers.add_parser(
        "events",
        help="List events",
        formatter_class=CompactOptionalFormatter,
        add_help=False,
    )
    events_parser.add_argument("--season", "-s", default="", help="Season id or 'all' (default: current season)")
    events_parser.add_argument(
        "--level", "-l", default="1",
        help="Levels: -1=All, 0=Mixed, 1=World Cup (default), 2=IBU Cup, 3=Junior, 4=Other, 5=Regional, 6=Para",
    )
    events_parser.add_argument("--search", default="", help="Filter events by name")
    events_parser.add_argument("--sort", default="startdate", choices=["startdate", "event", "country"], help="Sort order")
    events_parser.add_argument("--completed", action="store_true", help="Only completed events")
    events_parser.add_argument("--summary", action="store_true", help="Show race-type availability per event")
    events_parser.add_argument("--races", action="store_true", help="Include races under each event")
    events_parser.add_argument("--discipline", "-d", default="", choices=["individual", "sprint", "pursuit", "massstart", "mass-start", "relay", ""], help="Filter races by discipline")
    add_output_flag(events_parser)
    events_parser.set_defaults(func=handle_events)

    # --- results ---
    results_parser = subparsers.add_parser(
        "results",
        help="Show race results",
        usage="biathlon results [subcommand]",
        formatter_class=CompactOptionalFormatter,
        add_help=False,
    )
    results_parser.add_argument("--race", "-r", default="", help="Race id (default: most recent completed World Cup race)")
    results_parser.add_argument("--sort", default="", help="Sort by column (result, ski, range, penalty, penaltyloopavg, shooting, misses)")
    results_parser.add_argument("--country", "-c", default="", metavar="COUNTRY", help="Filter by country code (e.g., FRA, GER, NOR)")
    results_parser.add_argument("--top", type=int, default=0, help="Filter to top N athletes in World Cup standings")
    results_parser.add_argument("--first", type=int, default=0, help="Filter to first N finishers in the race")
    results_parser.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(results_parser)
    results_parser.set_defaults(func=handle_results, results_command=None)
    results_sub = results_parser.add_subparsers(dest="results_command", title="subcommands", metavar="")
    for group in results_parser._action_groups:
        if any(isinstance(action, argparse._SubParsersAction) for action in group._group_actions):
            group.title = "subcommands"
            subcommands_group = group
            break
    else:
        subcommands_group = None
    if subcommands_group:
        results_parser._action_groups.remove(subcommands_group)
        for idx, group in enumerate(results_parser._action_groups):
            if group.title == "optional arguments":
                results_parser._action_groups.insert(idx, subcommands_group)
                break
        else:
            results_parser._action_groups.append(subcommands_group)

    results_ski = results_sub.add_parser("ski", help="Show ski time details", formatter_class=CompactOptionalFormatter, add_help=False)
    results_ski.add_argument("--race", "-r", default="", help="Race id")
    results_ski.add_argument("--sort", default="", help="Sort by column")
    results_ski.add_argument("--country", "-c", default="", help="Filter by country code (e.g., FRA, GER, NOR)")
    results_ski.add_argument("--top", type=int, default=0, help="Filter to top N athletes in World Cup standings")
    results_ski.add_argument("--first", type=int, default=0, help="Filter to first N finishers in the race")
    results_ski.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(results_ski)
    results_ski.set_defaults(func=handle_results_ski)

    results_range = results_sub.add_parser("range", help="Show range time details", formatter_class=CompactOptionalFormatter, add_help=False)
    results_range.add_argument("--race", "-r", default="", help="Race id")
    results_range.add_argument("--sort", default="", help="Sort by column")
    results_range.add_argument("--country", "-c", default="", help="Filter by country code (e.g., FRA, GER, NOR)")
    results_range.add_argument("--top", type=int, default=0, help="Filter to top N athletes in World Cup standings")
    results_range.add_argument("--first", type=int, default=0, help="Filter to first N finishers in the race")
    results_range.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(results_range)
    results_range.set_defaults(func=handle_results_range)

    results_shooting = results_sub.add_parser("shooting", help="Show shooting time details", formatter_class=CompactOptionalFormatter, add_help=False)
    results_shooting.add_argument("--race", "-r", default="", help="Race id")
    results_shooting.add_argument("--sort", default="", help="Sort by column")
    results_shooting.add_argument("--country", "-c", default="", help="Filter by country code (e.g., FRA, GER, NOR)")
    results_shooting.add_argument("--top", type=int, default=0, help="Filter to top N athletes in World Cup standings")
    results_shooting.add_argument("--first", type=int, default=0, help="Filter to first N finishers in the race")
    results_shooting.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(results_shooting)
    results_shooting.set_defaults(func=handle_results_shooting)

    results_remontada = results_sub.add_parser(
        "remontada",
        help="Show pursuit gains (for pursuit races only)",
        formatter_class=CompactOptionalFormatter,
        add_help=False,
    )
    results_remontada.add_argument("--race", "-r", default="", help="Race id")
    results_remontada.add_argument("--country", "-c", default="", help="Filter by country code (e.g., FRA, GER, NOR)")
    results_remontada.add_argument("--top", type=int, default=0, help="Filter to top N athletes in World Cup standings")
    results_remontada.add_argument("--first", type=int, default=0, help="Filter to first N finishers in the race")
    results_remontada.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    results_remontada.add_argument(
        "--highlight-wc",
        action="store_true",
        help="Highlight top 6 by World Cup standing instead of race rank",
    )
    add_output_flag(results_remontada)
    results_remontada.set_defaults(func=handle_results_remontada)

    # --- cumulate ---
    cumulate_parser = subparsers.add_parser(
        "cumulate",
        help="Show cumulative rankings",
        usage=(
            "biathlon cumulate subcommand [--men] "
            "[--discipline {individual,sprint,pursuit,mass-start,all}] "
            "[--season SEASON] [--event EVENT] [--position] [--no-sprint-delay] "
            "[--min-race MIN_RACE] [--top TOP] [--limit LIMIT] [--debug-races] [--reverse] [--tsv]"
        ),
        formatter_class=CompactOptionalFormatter,
        add_help=False,
    )
    add_cumulate_args(cumulate_parser)
    cumulate_parser.set_defaults(func=handle_cumulate_course, cumulate_command=None)
    cumulate_sub = cumulate_parser.add_subparsers(dest="cumulate_command", title="subcommands", metavar="")

    cumulate_course = cumulate_sub.add_parser("course", help="Cumulated course times (default)", formatter_class=CompactOptionalFormatter, add_help=False)
    add_cumulate_args(cumulate_course)
    cumulate_course.set_defaults(func=handle_cumulate_course)

    cumulate_ski = cumulate_sub.add_parser("ski", help="Cumulated ski times", formatter_class=CompactOptionalFormatter, add_help=False)
    add_cumulate_args(cumulate_ski)
    cumulate_ski.set_defaults(func=handle_cumulate_ski)

    cumulate_penalty = cumulate_sub.add_parser("penalty", help="Cumulated penalty times", formatter_class=CompactOptionalFormatter, add_help=False)
    add_cumulate_args(cumulate_penalty)
    cumulate_penalty.set_defaults(func=handle_cumulate_penalty)

    cumulate_range = cumulate_sub.add_parser("range", help="Cumulated range times", formatter_class=CompactOptionalFormatter, add_help=False)
    add_cumulate_args(cumulate_range)
    cumulate_range.set_defaults(func=handle_cumulate_range)

    cumulate_shooting = cumulate_sub.add_parser("shooting", help="Cumulated shooting times", formatter_class=CompactOptionalFormatter, add_help=False)
    cumulate_shooting.add_argument("--sort", default="shootingtime", choices=["shootingtime", "misses", "accuracy", "position"], help="Sort order")
    add_cumulate_args(cumulate_shooting)
    cumulate_shooting.set_defaults(func=handle_cumulate_shooting)

    cumulate_miss = cumulate_sub.add_parser("miss", help="Cumulated misses", formatter_class=CompactOptionalFormatter, add_help=False)
    add_cumulate_args(cumulate_miss)
    cumulate_miss.set_defaults(func=handle_cumulate_miss)

    cumulate_remontada = cumulate_sub.add_parser("remontada", help="Cumulated pursuit gains", formatter_class=CompactOptionalFormatter, add_help=False)
    cumulate_remontada.add_argument("--season", "-s", default="", help="Season id")
    cumulate_remontada.add_argument("--men", action="store_true", help="Show men")
    cumulate_remontada.add_argument("--min-race", type=int, default=0, help="Minimum races")
    cumulate_remontada.add_argument("--top", type=int, default=0, help="Filter to top N WC athletes")
    cumulate_remontada.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(cumulate_remontada)
    cumulate_remontada.set_defaults(func=handle_cumulate_remontada)

    for idx, group in enumerate(cumulate_parser._action_groups):
        if group.title == "subcommands":
            subcommands_group = cumulate_parser._action_groups.pop(idx)
            break
    else:
        subcommands_group = None
    if subcommands_group:
        for idx, group in enumerate(cumulate_parser._action_groups):
            if group.title == "optional arguments":
                cumulate_parser._action_groups.insert(idx, subcommands_group)
                break
        else:
            cumulate_parser._action_groups.append(subcommands_group)

    # --- record ---
    record_parser = subparsers.add_parser("record", help="Show records (lap, etc.)", formatter_class=CompactOptionalFormatter, add_help=False)
    record_parser.add_argument("--event", "-e", default="", help="Event id")
    record_parser.add_argument("--discipline", "-d", default="", choices=["individual", "sprint", "pursuit", "massstart", "mass-start", ""], help="Discipline filter")
    record_parser.add_argument("--men", action="store_true", help="Show men")
    add_output_flag(record_parser)
    record_parser.set_defaults(func=handle_record_lap, record_command=None)
    record_sub = record_parser.add_subparsers(dest="record_command", title="subcommands", metavar="")

    record_lap = record_sub.add_parser("lap", help="Top lap times", formatter_class=CompactOptionalFormatter, add_help=False)
    record_lap.add_argument("--event", "-e", default="", help="Event id")
    record_lap.add_argument("--discipline", "-d", default="", choices=["individual", "sprint", "pursuit", "massstart", "mass-start", ""], help="Discipline filter")
    record_lap.add_argument("--men", action="store_true", help="Show men")
    add_output_flag(record_lap)
    record_lap.set_defaults(func=handle_record_lap)

    # --- standings ---
    standings_parser = subparsers.add_parser("standings", help="Show world cup standing", formatter_class=CompactOptionalFormatter, add_help=False)
    standings_parser.add_argument("--season", "-s", default="", help="Season id")
    standings_parser.add_argument("--men", action="store_true", help="Show men")
    standings_parser.add_argument("--level", "-l", default="1", help="Cup level")
    standings_parser.add_argument("--sort", default="total", choices=["total", "sprint", "pursuit", "individual", "massstart"], help="Sort by column")
    standings_parser.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(standings_parser)
    standings_parser.set_defaults(func=handle_scores)

    # --- ceremony ---
    ceremony_parser = subparsers.add_parser("ceremony", help="Show medal standing", formatter_class=CompactOptionalFormatter, add_help=False)
    ceremony_parser.add_argument("--athlete", action="store_true", help="Rank by athlete")
    ceremony_parser.add_argument("--race", "-r", default="", help="Race id")
    ceremony_parser.add_argument("--event", "-e", default="", help="Event id")
    gender_group = ceremony_parser.add_mutually_exclusive_group()
    gender_group.add_argument("--men", action="store_true", help="Show men")
    gender_group.add_argument("--women", action="store_true", help="Show women")
    ceremony_parser.add_argument("--country", "-c", default="", help="Filter by host country (where event is held)")
    ceremony_parser.add_argument("--search", default="", help="Filter events by name (e.g., 'annecy', 'holmenkollen')")
    ceremony_parser.add_argument("--season", "-s", default="", help="Season id")
    add_output_flag(ceremony_parser)
    ceremony_parser.set_defaults(func=handle_ceremony)

    # --- biathlete ---
    biathlete_parser = subparsers.add_parser("biathlete", help="Show biathlete information", formatter_class=CompactOptionalFormatter, add_help=False)
    biathlete_parser.add_argument("--id", "-i", default="", help="Athlete IBU id (comma-separated)")
    biathlete_parser.add_argument("--search", "-s", default="", help="Search by name")
    biathlete_parser.add_argument("--season", default="", help="Season id")
    add_output_flag(biathlete_parser)
    biathlete_parser.set_defaults(func=handle_athlete_info, athlete_command=None)
    athlete_sub = biathlete_parser.add_subparsers(dest="athlete_command", title="subcommands", metavar="")

    athlete_results = athlete_sub.add_parser("results", help="Season race ranks", formatter_class=CompactOptionalFormatter, add_help=False)
    athlete_results.add_argument("--id", "-i", default="", help="Athlete IBU id")
    athlete_results.add_argument("--search", "-s", default="", help="Search by name")
    athlete_results.add_argument("--season", default="", help="Season id")
    athlete_results.add_argument("--level", type=int, default=0, help="Event level (1-5, 0 for all)")
    athlete_results.add_argument("--ski", action="store_true", help="Use ski time rank")
    add_output_flag(athlete_results)
    athlete_results.set_defaults(func=handle_athlete_results)

    athlete_info = athlete_sub.add_parser("info", help="Athlete bio info", formatter_class=CompactOptionalFormatter, add_help=False)
    athlete_info.add_argument("--id", "-i", default="", help="Athlete IBU id (comma-separated)")
    athlete_info.add_argument("--search", "-s", default="", help="Search by name")
    athlete_info.add_argument("--season", default="", help="Season id")
    athlete_info.add_argument("--level", type=int, default=0, help="Event level (1-5, 0 for all)")
    add_output_flag(athlete_info)
    athlete_info.set_defaults(func=handle_athlete_info)

    # --- shooting ---
    shooting_parser = subparsers.add_parser("shooting", help="Show shooting accuracy", formatter_class=CompactOptionalFormatter, add_help=False)
    shooting_parser.add_argument("--race", "-r", default="", help="Race id")
    shooting_parser.add_argument("--event", "-e", default="", help="Event id")
    shooting_parser.add_argument("--season", "-s", default="", help="Season id")
    shooting_parser.add_argument("--men", action="store_true", help="Show men")
    shooting_parser.add_argument("--all-races", action="store_true", help="Only athletes who started every race")
    shooting_parser.add_argument("--sort", default="accuracy", help="Sort order")
    shooting_parser.add_argument("--min-race", type=int, default=0, help="Minimum races")
    shooting_parser.add_argument("--top", type=int, default=0, help="Restrict to top N athletes in WC standings")
    shooting_parser.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    shooting_parser.add_argument("--debug-races", action="store_true", help="Debug: print races considered")
    add_output_flag(shooting_parser)
    shooting_parser.set_defaults(func=handle_shooting)

    # --- relay ---
    relay_parser = subparsers.add_parser("relay", help="Show relay results", formatter_class=CompactOptionalFormatter, add_help=False)
    relay_parser.add_argument(
        "--race",
        "-r",
        default="",
        help="Race id (default: most recent completed women relay)",
    )
    relay_parser.add_argument(
        "--men", action="store_true", help="Show most recent men relay (default: women)"
    )
    relay_parser.add_argument("--mixed", action="store_true", help="Show most recent mixed relay")
    relay_parser.add_argument(
        "--singlemixed", action="store_true", help="Show most recent single mixed relay"
    )
    relay_parser.add_argument("--sort", default="", help="Sort by column (e.g., course, penalty, misses)")
    relay_parser.add_argument(
        "--detail",
        action="store_true",
        help="Show leg details (biathlete, result, behind, miss)",
    )
    relay_parser.add_argument("--first", type=int, default=0, help="Filter to first N teams in the race")
    relay_parser.add_argument("--limit", "-n", type=int, default=25, help="Limit output rows (default: 25, 0 for all)")
    add_output_flag(relay_parser)
    relay_parser.set_defaults(func=handle_relay)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Main CLI entry point."""
    tokens = list(argv) if argv is not None else sys.argv[1:]

    # Handle --version before parsing
    if tokens and tokens[0] in ("--version", "-V"):
        print(f"biathlon {get_version()}")
        return 0

    # Handle --completion before parsing
    if len(tokens) >= 2 and tokens[0] == "--completion":
        return print_completion(tokens[1])
    if len(tokens) == 1 and tokens[0] == "--completion":
        print("Usage: biathlon --completion [bash|zsh]", file=sys.stderr)
        return 1

    parser = build_parser()

    if tokens and tokens[-1] == "help":
        target_tokens = tokens[:-1]
        target_parser, remaining = traverse_to_parser(parser, target_tokens)
        if remaining:
            print(f"error: unknown command {' '.join(remaining)}", file=sys.stderr)
            return 1
        print()
        target_parser.print_help()
        print()
        return 0

    args = parser.parse_args(tokens)

    if args.command is None:
        print(
            "\nbiathlon: [ERROR]: the following arguments are required: command\n\n"
            "Usage: biathlon <command> [<subcommand> ...] [parameters]\n\n"
            "Example: biathlon events --races\n\n"
            "To see help text, you can run:\n"
            "  biathlon help\n"
            "  biathlon <command> help\n"
            "  biathlon <command> <subcommand> help\n",
            file=sys.stderr,
        )
        return 2

    try:
        return args.func(args)
    except BiathlonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
