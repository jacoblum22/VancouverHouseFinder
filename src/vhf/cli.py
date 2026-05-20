from __future__ import annotations

import sys

# Ensure UTF-8 output on Windows so Rich can render box-drawing and other
# non-ASCII characters without hitting the cp1252 codec limitation.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from datetime import date
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from .models import Listing, SearchCriteria
from .pipeline import run_once

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def run(
    max_rent_cad: int = typer.Option(6600, help="Max rent in CAD/month."),
    min_bedrooms: int = typer.Option(4, help="Minimum number of bedrooms."),
    available_before: Optional[str] = typer.Option(
        "2026-09-01", help="Only include listings available on/before this date (YYYY-MM-DD)."
    ),
    city: str = typer.Option("Vancouver", help="City filter (normalized text)."),
) -> None:
    """Run the pipeline once (MVP entrypoint)."""
    avail_date: date | None = None
    if available_before:
        try:
            avail_date = date.fromisoformat(available_before)
        except ValueError:
            console.print(f"[red]Invalid date '{available_before}' — expected YYYY-MM-DD. Ignoring.[/red]")

    criteria = SearchCriteria(
        max_rent_cad=max_rent_cad,
        min_bedrooms=min_bedrooms,
        available_before=avail_date,
        city=city,
    )
    result = run_once(criteria=criteria)

    table = Table(title=f"VHF results (count={len(result.listings)})")
    table.add_column("Price", justify="right")
    table.add_column("Beds", justify="right")
    table.add_column("Availability")
    table.add_column("Neighborhood/Address")
    table.add_column("Source")
    table.add_column("URL", overflow="fold")

    for l in result.listings:
        table.add_row(
            "" if l.price_cad is None else f"${l.price_cad:,}",
            "" if l.bedrooms is None else str(l.bedrooms),
            "" if l.availability_date is None else l.availability_date.isoformat(),
            (l.neighborhood or l.address_text or ""),
            l.source,
            str(l.url),
        )

    console.print(table)


@app.command("verify-export")
def verify_export(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to results.html (default: data/exports/results.html).",
    ),
) -> None:
    """Verify the HTML export used for GitHub Pages (map + geo rows)."""
    from .paths import EXPORTS_DIR
    from .verify_export_html import collect_results_html_errors

    p = path or (EXPORTS_DIR / "results.html")
    errors = collect_results_html_errors(p)
    if errors:
        for e in errors:
            console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]OK[/green] export looks valid -> [cyan]{p}[/cyan]")


@app.command("labels-init")
def labels_init(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Labels CSV path (default: data/labels/listing_kind_labels.csv).",
    ),
) -> None:
    """Create the listing-kind labels CSV with headers if it does not exist yet."""
    from .listing_labels import DEFAULT_LABELS_PATH, init_labels_file

    p = path or DEFAULT_LABELS_PATH
    created = init_labels_file(p)
    if created:
        console.print(f"[green]Created[/green] [cyan]{p}[/cyan]")
    else:
        console.print(f"[yellow]Already exists[/yellow] -> [cyan]{p}[/cyan]")


@app.command("listing-kind-train")
def listing_kind_train(
    export_csv: Optional[Path] = typer.Option(
        None,
        "--export",
        "-e",
        help="Path to results.csv (default: data/exports/results.csv).",
    ),
    labels_csv: Optional[Path] = typer.Option(
        None,
        "--labels",
        "-l",
        help="Labels CSV (default: data/labels/listing_kind_labels.csv).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Log each LOO fold (DEBUG on vhf.listing_kind_ml).",
    ),
) -> None:
    """Cross-validated accuracy / F1 for binary labels (requires pip install -e '.[ml]')."""
    import logging

    from .listing_kind_ml import train_listing_kind

    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )
    if verbose:
        logging.getLogger("vhf.listing_kind_ml").setLevel(logging.DEBUG)

    try:
        report = train_listing_kind(export_csv=export_csv, labels_csv=labels_csv)
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e

    console.print(
        f"Rows used: [cyan]{report.n_fit}[/cyan] "
        f"(whole_unit={report.n_whole_unit}, room_or_partial={report.n_room_or_partial})"
    )
    console.print(f"CV scheme: [cyan]{report.cv_scheme}[/cyan]")
    console.print(f"CV accuracy: [cyan]{report.cv_accuracy:.3f}[/cyan]")
    console.print(f"CV F1 (room_or_partial): [cyan]{report.cv_f1_room:.3f}[/cyan]")
    console.print(
        "[dim]Hand-engineered features (L2 logistic):[/dim] "
        + ", ".join(f"[cyan]{n}[/cyan]" for n in report.feature_names)
    )


@app.command("listing-kind-suggest")
def listing_kind_suggest(
    export_csv: Optional[Path] = typer.Option(
        None,
        "--export",
        "-e",
        help="Path to results.csv (default: data/exports/results.csv).",
    ),
    labels_csv: Optional[Path] = typer.Option(
        None,
        "--labels",
        "-l",
        help="Labels CSV (default: data/labels/listing_kind_labels.csv).",
    ),
    top_n: int = typer.Option(15, "--top", "-n", help="How many uncertain listings to print."),
) -> None:
    """Print unlabeled listings the model is least sure about (active-learning queue)."""
    from .listing_kind_ml import suggest_listing_kind_labels

    try:
        rows = suggest_listing_kind_labels(
            export_csv=export_csv, labels_csv=labels_csv, top_n=top_n
        )
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e

    if not rows:
        console.print("[yellow]No unlabeled rows in export (or all keys already in labels).[/yellow]")
        return

    table = Table(title=f"Most uncertain (P(room_or_partial)), top {len(rows)}")
    table.add_column("p_room", justify="right")
    table.add_column("listing_key", overflow="fold")
    table.add_column("title", overflow="fold")
    table.add_column("url", overflow="fold")
    for r in rows:
        table.add_row(f"{r.p_room:.3f}", r.listing_key, r.title or "—", r.url or "—")
    console.print(table)


def _print_phrase_lift_table(title: str, rows: list[Any], *, limit: int = 50) -> None:
    table = Table(title=title)
    table.add_column("phrase", overflow="fold")
    table.add_column("df slice", justify="right")
    table.add_column("df rest", justify="right")
    table.add_column("lift", justify="right")
    for r in rows[:limit]:
        lift_s = "∞" if r.lift == float("inf") else f"{r.lift:.2f}"
        table.add_row(r.phrase, str(r.df_slice), str(r.df_rest), lift_s)
    console.print(table)


@app.command("explore-keywords")
def explore_keywords(
    jsonl: Optional[Path] = typer.Option(
        None,
        "--jsonl",
        "-j",
        help="Path to listings.jsonl (default: data/processed/listings.jsonl).",
    ),
    min_price: int = typer.Option(0, help="Focus slice min rent (CAD/month), inclusive."),
    max_price: int = typer.Option(2000, help="Focus slice max rent (CAD/month), inclusive."),
    ppb_max: Optional[float] = typer.Option(
        None,
        help="Also include listings with price/bedrooms <= this value (optional OR).",
    ),
    bigram_top_k: int = typer.Option(40, help="How many bigram rows to show / write."),
    bigram_min_df: int = typer.Option(
        2,
        help="Minimum slice document-frequency for a bigram to be considered.",
    ),
    write: Optional[Path] = typer.Option(
        None,
        "--write",
        "-w",
        help="Write markdown report to this path (e.g. tmp/phase_b_report.md).",
    ),
) -> None:
    """Phase B: seed phrase + bigram lift on title+description (local analysis; not in CSV/HTML)."""
    try:
        from .keyword_explore import build_explore_tables, format_explore_markdown
    except ImportError as e:
        console.print(
            "[red]keyword_explore module is missing from this checkout.[/red] "
            "Restore `src/vhf/keyword_explore.py` or skip this command."
        )
        raise typer.Exit(code=1) from e
    from .paths import PROCESSED_DIR
    from .storage import read_jsonl

    path = jsonl or (PROCESSED_DIR / "listings.jsonl")
    if not path.exists():
        console.print(
            f"[red]Missing {path} — run [cyan]vhf run[/cyan] first to generate listings.jsonl.[/red]"
        )
        raise typer.Exit(code=1)

    listings = read_jsonl(path, Listing)
    room_rows, whole_rows, bi_rows, n_s, n_r = build_explore_tables(
        listings,
        min_price=min_price,
        max_price=max_price,
        max_price_per_bed=ppb_max,
        bigram_top_k=bigram_top_k,
        bigram_min_df_slice=bigram_min_df,
    )

    band = f"${min_price}–${max_price}/mo"
    ppb_note = f" OR price/bed ≤ {ppb_max:g}" if ppb_max is not None else ""
    console.print(
        f"[bold]Phase B[/bold] — focus: [cyan]{band}[/cyan]{ppb_note} · "
        f"slice docs with text: [cyan]{n_s}[/cyan] · rest: [cyan]{n_r}[/cyan]"
    )
    if n_s == 0:
        console.print(
            "[yellow]No listings in the focus slice with title/description — widen band or run scrape.[/yellow]"
        )

    _print_phrase_lift_table("Room / shared hints (seed phrases)", room_rows)
    _print_phrase_lift_table("Whole-unit hints (seed phrases)", whole_rows)
    _print_phrase_lift_table(
        f"Top bigrams (min df in slice ≥ {bigram_min_df})", bi_rows, limit=bigram_top_k
    )

    if write is not None:
        md = format_explore_markdown(
            listings,
            min_price=min_price,
            max_price=max_price,
            max_price_per_bed=ppb_max,
            bigram_top_k=bigram_top_k,
            bigram_min_df_slice=bigram_min_df,
        )
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(md, encoding="utf-8")
        console.print(f"[green]Wrote[/green] [cyan]{write}[/cyan]")


if __name__ == "__main__":
    app()
