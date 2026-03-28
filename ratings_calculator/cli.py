"""
cli.py
------
Command-line interface for the PDGA ratings calculator.

Usage:
    pdga-ratings --pdga 12345
    pdga-ratings --pdga 12345 --whatif 950,960,970
    pdga-ratings --pdga 12345 --target 950 --rounds 3
    pdga-ratings --pdga 12345 --refresh
"""

import argparse
import sys

from rich.console import Console
from rich.table import Table
from rich import box

from .scraper    import load_player_data, FetchError, ParseError
from .calculator import project_rating, rounds_needed_for_target

console = Console()

COLOR_GREEN = "green"
COLOR_RED   = "red"
COLOR_YELLOW = "yellow"
COLOR_MUTED  = "bright_black"
COLOR_CYAN   = "cyan"


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="pdga-ratings",
        description="PDGA ratings calculator — project your next rating update.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --pdga 12345
  %(prog)s --pdga 12345 --whatif 950,960,970
  %(prog)s --pdga 12345 --target 950 --rounds 3
  %(prog)s --pdga 12345 --refresh
        """,
    )
    parser.add_argument("--pdga",    required=True,  help="PDGA player number")
    parser.add_argument("--whatif",  default=None,   help="Comma-separated hypothetical round ratings")
    parser.add_argument("--target",  type=int, default=None, help="Target rating to solve for")
    parser.add_argument("--rounds",  type=int, default=3,    help="Number of rounds for --target solver (default: 3)")
    parser.add_argument("--refresh", action="store_true",    help="Bypass cache and re-fetch all data")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _rounds_table(title: str, rounds: list[dict], drop_below: float) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAD, show_lines=False, title_style="bold")
    table.add_column("Tournament", style="dim", no_wrap=False, ratio=6)
    table.add_column("Rd",     justify="right", ratio=1)
    table.add_column("Rating", justify="right", ratio=1)
    for rd in rounds:
        rating = rd["rating"]
        color  = COLOR_RED if rating < drop_below else "white"
        table.add_row(
            rd.get("name", "?"),
            str(rd.get("round", "?")),
            f"[{color}]{rating}[/{color}]",
        )
    return table


def print_results(result: dict, current_rating: int) -> None:
    projected  = result["projected_rating"]
    drop_below = result["drop_below"]
    change     = projected - current_rating
    sign       = "+" if change >= 0 else ""
    change_col = COLOR_GREEN if change >= 0 else COLOR_RED

    console.print()
    console.rule("[bold]PDGA Rating Projection[/bold]")
    console.print(
        f"\n  [bold]Projected rating:[/bold] [bold {COLOR_CYAN}]{projected}[/bold {COLOR_CYAN}]  "
        f"([{change_col}]{sign}{change}[/{change_col}] from current {current_rating})"
    )
    console.print(f"  [bold]Outlier cutoff:[/bold] {int(drop_below)}\n")

    if result["outgoing_rounds"]:
        console.print(_rounds_table("Rounds Dropping Off", result["outgoing_rounds"], drop_below))
    else:
        console.print(f"  [{COLOR_MUTED}]No rounds dropping off.[/{COLOR_MUTED}]")

    console.print()

    if result["incoming_rounds"]:
        console.print(_rounds_table("Rounds Coming In", result["incoming_rounds"], drop_below))
    else:
        console.print(f"  [{COLOR_MUTED}]No new rounds coming in.[/{COLOR_MUTED}]")

    console.print()

    if result["outlier_rounds"]:
        console.print(_rounds_table("Outlier Rounds (excluded)", result["outlier_rounds"], drop_below))
    else:
        console.print(f"  [{COLOR_GREEN}]No outlier rounds.[/{COLOR_GREEN}]")

    console.print()


def print_target_result(target_result: dict, target: int, num_rounds: int) -> None:
    console.rule(f"[bold]Target Rating Solver — {target} in {num_rounds} round(s)[/bold]")
    console.print()
    if target_result["achievable"]:
        console.print(
            f"  [bold {COLOR_GREEN}]Achievable![/bold {COLOR_GREEN}]  "
            f"Average [bold]{target_result['needed_avg']}[/bold] over {num_rounds} round(s) "
            f"→ projected [bold]{target_result['with_avg']}[/bold]"
        )
    else:
        console.print(
            f"  [bold {COLOR_RED}]Not achievable[/bold {COLOR_RED}] — "
            f"{target_result['message']}"
        )
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv)

    try:
        with console.status(f"Loading data for PDGA #{args.pdga}..."):
            data = load_player_data(args.pdga, force_refresh=args.refresh)
    except (FetchError, ParseError) as e:
        console.print(f"[{COLOR_RED}]Error:[/{COLOR_RED}] {e}")
        sys.exit(1)

    tournaments     = data["tournaments"]
    new_tournaments = data["new_tournaments"]
    current_rating  = data["current_rating"]

    whatif_ratings: list[int] | None = None
    if args.whatif:
        try:
            whatif_ratings = [int(r.strip()) for r in args.whatif.split(",")]
        except ValueError:
            console.print(f"[{COLOR_RED}]--whatif must be comma-separated integers.[/{COLOR_RED}]")
            sys.exit(1)

    try:
        result = project_rating(tournaments, new_tournaments, whatif_ratings)
    except ValueError as e:
        console.print(f"[{COLOR_RED}]Calculation error:[/{COLOR_RED}] {e}")
        sys.exit(1)

    print_results(result, current_rating)

    if args.target is not None:
        try:
            target_result = rounds_needed_for_target(
                tournaments, new_tournaments, args.target, args.rounds
            )
        except ValueError as e:
            console.print(f"[{COLOR_RED}]Target solver error:[/{COLOR_RED}] {e}")
            sys.exit(1)
        print_target_result(target_result, args.target, args.rounds)


if __name__ == "__main__":
    main()
