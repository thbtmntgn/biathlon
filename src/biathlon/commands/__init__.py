"""Command handlers for the Biathlon CLI."""

from .seasons import handle_seasons
from .events import handle_events
from .results import (
    handle_results,
    handle_results_remontada,
    handle_results_ski,
    handle_results_range,
    handle_results_shooting,
)
from .cumulate import (
    handle_cumulate_course,
    handle_cumulate_miss,
    handle_cumulate_shooting,
    handle_cumulate_range,
    handle_cumulate_ski,
    handle_cumulate_penalty,
    handle_cumulate_remontada,
)
from .scores import handle_scores
from .records import handle_record_lap
from .ceremony import handle_ceremony
from .athlete import handle_athlete_results, handle_athlete_info
from .shooting import handle_shooting
from .relay import handle_relay

__all__ = [
    "handle_seasons",
    "handle_events",
    "handle_results",
    "handle_results_remontada",
    "handle_results_ski",
    "handle_results_range",
    "handle_results_shooting",
    "handle_cumulate_course",
    "handle_cumulate_miss",
    "handle_cumulate_shooting",
    "handle_cumulate_range",
    "handle_cumulate_ski",
    "handle_cumulate_penalty",
    "handle_cumulate_remontada",
    "handle_scores",
    "handle_record_lap",
    "handle_ceremony",
    "handle_athlete_results",
    "handle_athlete_info",
    "handle_shooting",
    "handle_relay",
]
