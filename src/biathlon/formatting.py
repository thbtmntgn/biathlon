"""Output formatting utilities for the Biathlon CLI."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable


class Color:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    BOLD_GREEN = "\033[1;32m"
    COLOR_PREFIX = "\033[38;2;"
    COLOR_SUFFIX = "m"

    GOLD = (255, 215, 0)
    LIGHT_GOLD = (218, 165, 32)  # Goldenrod - distinct from bold gold
    SILVER = (192, 192, 192)
    BRONZE = (205, 127, 50)
    FLOWERS = (255, 182, 108)
    OTHER = (215, 215, 215)
    GREEN = (0, 200, 0)
    RED = (220, 60, 60)

    @classmethod
    def enabled(cls) -> bool:
        """Check if colors should be enabled."""
        if os.environ.get("NO_COLOR"):
            return False
        if not sys.stdout.isatty():
            return False
        return True

    @classmethod
    def dim(cls, text: str) -> str:
        """Apply dim style (for past events)."""
        if not cls.enabled():
            return text
        return f"{cls.DIM}{text}{cls.RESET}"

    @classmethod
    def highlight(cls, text: str) -> str:
        """Apply highlight style (for current/next event)."""
        if not cls.enabled():
            return text
        return f"{cls.BOLD_GREEN}{text}{cls.RESET}"

    @classmethod
    def rgb(cls, text: str, color: tuple[int, int, int], bold: bool = False) -> str:
        """Apply a 24-bit color (optionally bold)."""
        if not cls.enabled():
            return text
        r, g, b = color
        prefix = f"{cls.BOLD}" if bold else ""
        return f"{prefix}{cls.COLOR_PREFIX}{r};{g};{b}{cls.COLOR_SUFFIX}{text}{cls.RESET}"

    @classmethod
    def silver(cls, text: str) -> str:
        """Apply silver style (2nd place)."""
        return cls.rgb(text, cls.SILVER, bold=True)

    @classmethod
    def bronze(cls, text: str) -> str:
        """Apply bronze style (3rd place)."""
        return cls.rgb(text, cls.BRONZE, bold=True)

    @classmethod
    def gold(cls, text: str) -> str:
        """Apply gold style (1st place)."""
        return cls.rgb(text, cls.GOLD, bold=True)

    @classmethod
    def flowers(cls, text: str) -> str:
        """Apply flowers ceremony style (4th/5th/6th place)."""
        return cls.rgb(text, cls.FLOWERS, bold=False)

    @classmethod
    def other(cls, text: str) -> str:
        """Apply style for non-top athletes."""
        return cls.dim(text)

    @classmethod
    def green(cls, text: str, intensity: float = 1.0) -> str:
        """Apply green color with intensity scale (0.0 to 1.0)."""
        base_g = 100
        max_g = 220
        g = int(base_g + (max_g - base_g) * min(1.0, max(0.0, intensity)))
        return cls.rgb(text, (0, g, 0), bold=intensity > 0.5)

    @classmethod
    def red(cls, text: str, intensity: float = 1.0) -> str:
        """Apply red color with intensity scale (0.0 to 1.0)."""
        base_r = 150
        max_r = 240
        r = int(base_r + (max_r - base_r) * min(1.0, max(0.0, intensity)))
        return cls.rgb(text, (r, 50, 50), bold=intensity > 0.5)

    @classmethod
    def accuracy(cls, text: str, pct: float) -> str:
        """Apply color based on accuracy percentage (0.0 to 1.0).

        Green for > 50%, red for < 50%, no color at 50%.
        """
        if not cls.enabled():
            return text
        if pct > 0.5:
            # Scale from 50% to 100% -> intensity 0.0 to 1.0
            intensity = (pct - 0.5) * 2
            return cls.green(text, intensity)
        elif pct < 0.5:
            # Scale from 50% to 0% -> intensity 0.0 to 1.0
            intensity = (0.5 - pct) * 2
            return cls.red(text, intensity)
        return text


def render_table(
    headers: list[str],
    rows: list[list[str]],
    pretty: bool,
    row_styles: list[str] | None = None,
    cell_formatters: list[Callable] | None = None,
    highlight_headers: list[int] | None = None,
) -> None:
    """Render tabular data either aligned (pretty) or TSV.

    Args:
        headers: Column headers.
        rows: Data rows.
        pretty: If True, align columns; otherwise output TSV.
        row_styles: Optional list of style names per row ("dim", "highlight", or "").
        cell_formatters: Optional list of functions (one per column) to format cell values.
                        Each function takes (value, row_index) and returns formatted string.
        highlight_headers: Optional list of column indices to highlight in the header row.
    """
    if not pretty:
        print("\t".join(headers))
        for row in rows:
            print("\t".join(str(cell) for cell in row))
        return

    widths = [
        max(len(str(headers[idx])), max((len(str(row[idx])) for row in rows), default=0))
        for idx in range(len(headers))
    ]

    def fmt_row(row: list[str], row_idx: int) -> str:
        parts = []
        for col_idx, cell in enumerate(row):
            cell_str = str(cell).ljust(widths[col_idx])
            if cell_formatters and col_idx < len(cell_formatters) and cell_formatters[col_idx]:
                cell_str = cell_formatters[col_idx](cell_str, row_idx)
            parts.append(cell_str)
        return "  ".join(parts)

    def fmt_header(idx: int, h: str) -> str:
        text = str(h).ljust(widths[idx])
        if highlight_headers and idx in highlight_headers:
            return Color.highlight(text)
        return text

    print("  ".join(fmt_header(i, h) for i, h in enumerate(headers)))
    for idx, row in enumerate(rows):
        line = fmt_row(row, idx)
        if row_styles and idx < len(row_styles):
            style = row_styles[idx]
            if style == "dim":
                line = Color.dim(line)
            elif style == "highlight":
                line = Color.highlight(line)
            elif style == "gold":
                line = Color.gold(line)
            elif style == "silver":
                line = Color.silver(line)
            elif style == "bronze":
                line = Color.bronze(line)
            elif style == "flowers":
                line = Color.flowers(line)
            elif style == "other":
                line = Color.other(line)
        print(line)


def format_seconds(seconds: float | None) -> str:
    """Render seconds as mm:ss.t or hh:mm:ss.t if needed."""
    if seconds is None:
        return "-"
    hours = int(seconds // 3600)
    remainder = seconds - hours * 3600
    minutes = int(remainder // 60)
    secs = remainder - minutes * 60
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:d}:{secs:04.1f}"


def format_pct(numerator: int, denominator: int) -> str:
    """Format a percentage with one decimal place."""
    if denominator == 0:
        return "-"
    return f"{100 * numerator / denominator:.1f}%"


def is_pretty_output(args) -> bool:
    """Return True if output should be pretty-printed (not TSV)."""
    return not getattr(args, "tsv", False)


def rank_style(rank: int | object) -> str:
    """Return style name for a given rank (1-6 get podium/flowers colors)."""
    try:
        r = int(rank)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "other"
    return {
        1: "gold",
        2: "silver",
        3: "bronze",
        4: "flowers",
        5: "flowers",
        6: "flowers",
    }.get(r, "other")
