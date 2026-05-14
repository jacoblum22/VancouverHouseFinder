"""New-listing detection and email notification.

Run as:
    python -m vhf.notify

Compares the current listings.jsonl against the prior state snapshot.
Sends one aggregated email if new or removed listings are detected, then
updates the state file so the next run only reports genuine changes.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import smtplib
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from typing import Any

from .models import Listing
from .paths import PROCESSED_DIR, STATE_DIR
from .state_file import listing_summary_for_state, listings_map_by_key, write_canonical_state_file
from .storage import read_jsonl


@lru_cache(maxsize=1)
def _rich_console() -> Any:
    from rich.console import Console

    return Console()


_STATE_FILE = STATE_DIR / "last_seen.json"
_LISTINGS_FILE = PROCESSED_DIR / "listings.jsonl"


# ------------------------------------------------------------------ #
# State helpers                                                        #
# ------------------------------------------------------------------ #


def _load_prior_state() -> tuple[set[str], dict[str, dict[str, Any]]]:
    if not _STATE_FILE.exists():
        return set(), {}
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return set(), {}

    entries_raw = data.get("entries")
    if isinstance(entries_raw, dict):
        entries: dict[str, dict[str, Any]] = {}
        for k, v in entries_raw.items():
            if isinstance(v, dict):
                entries[str(k)] = v
        return set(entries.keys()), entries

    return set(), {}


def _save_state(current_map: dict[str, Listing]) -> None:
    entries = {k: listing_summary_for_state(v) for k, v in current_map.items()}
    write_canonical_state_file(_STATE_FILE, entries, updated_at=datetime.now(UTC))


# ------------------------------------------------------------------ #
# Email builder                                                        #
# ------------------------------------------------------------------ #

def _fmt_beds(beds: float | None) -> str:
    if beds is None:
        return "?"
    return str(int(beds)) if beds == int(beds) else str(beds)


def _price_display_stored(price_cad: Any) -> str:
    """Format price from last_seen *entries* JSON (int, float, or missing)."""
    if price_cad is None or isinstance(price_cad, bool):
        return "?"
    if isinstance(price_cad, int):
        return f"${price_cad:,}"
    if isinstance(price_cad, float):
        i = int(price_cad)
        return f"${i:,}" if i == price_cad else f"${price_cad:,.0f}"
    return "?"


def _beds_from_stored(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _table_rows_from_summaries(
    summaries: list[dict[str, Any]],
    cell_style: str,
) -> list[str]:
    rows_html: list[str] = []
    for i, s in enumerate(summaries):
        price = _price_display_stored(s.get("price_cad"))
        beds = _fmt_beds(_beds_from_stored(s.get("bedrooms")))
        tm = s.get("transit_minutes_to_ubc")
        transit = f"{int(tm)} min" if isinstance(tm, int) and not isinstance(tm, bool) else "—"
        raw_url = str(s.get("url") or "").strip()
        url = _html.escape(raw_url)
        neigh = _html.escape(str(s.get("neighborhood") or ""))
        address = _html.escape(str(s.get("address_text") or ""))
        title = _html.escape(str(s.get("title") or ""))
        source = _html.escape(str(s.get("source") or ""))
        key_hint = str(s.get("_key") or "")
        if not title and key_hint:
            title = _html.escape(f"(key: {key_hint})")
        bg = "#ffffff" if i % 2 == 0 else "#fafafa"
        link_cell = (
            f'<a href="{url}" style="color:#1a73e8">link</a>' if raw_url else "—"
        )
        rows_html.append(
            f'<tr style="background:{bg}">'
            f'<td style="{cell_style}">{price}</td>'
            f'<td style="{cell_style}">{beds}</td>'
            f'<td style="{cell_style}">{transit}</td>'
            f'<td style="{cell_style}">{neigh}</td>'
            f'<td style="{cell_style}">{address}</td>'
            f'<td style="{cell_style}">{source}</td>'
            f'<td style="{cell_style}">{link_cell}</td>'
            f'<td style="{cell_style}">{title}</td>'
            "</tr>"
        )
    return rows_html


def _table_rows_from_listings(
    listings: list[Listing],
    cell_style: str,
) -> list[str]:
    rows_html: list[str] = []
    for i, lst in enumerate(listings):
        price = f"${lst.price_cad:,}" if lst.price_cad else "?"
        beds = _fmt_beds(lst.bedrooms)
        transit = f"{lst.transit_minutes_to_ubc} min" if lst.transit_minutes_to_ubc is not None else "—"
        neigh = _html.escape(lst.neighborhood or "")
        address = _html.escape(lst.address_text or "")
        title = _html.escape(lst.title or "")
        url = _html.escape(str(lst.url))
        source = _html.escape(lst.source)
        bg = "#ffffff" if i % 2 == 0 else "#fafafa"
        rows_html.append(
            f'<tr style="background:{bg}">'
            f'<td style="{cell_style}">{price}</td>'
            f'<td style="{cell_style}">{beds}</td>'
            f'<td style="{cell_style}">{transit}</td>'
            f'<td style="{cell_style}">{neigh}</td>'
            f'<td style="{cell_style}">{address}</td>'
            f'<td style="{cell_style}">{source}</td>'
            f'<td style="{cell_style}"><a href="{url}" style="color:#1a73e8">link</a></td>'
            f'<td style="{cell_style}">{title}</td>'
            "</tr>"
        )
    return rows_html


def _thead_html(head_cell: str) -> str:
    return f"""    <thead>
      <tr>
        <th style="{head_cell}">Price</th>
        <th style="{head_cell}">Beds</th>
        <th style="{head_cell}">Transit to UBC</th>
        <th style="{head_cell}">Neighborhood</th>
        <th style="{head_cell}">Address</th>
        <th style="{head_cell}">Source</th>
        <th style="{head_cell}">URL</th>
        <th style="{head_cell}">Title</th>
      </tr>
    </thead>"""


def _build_email(
    new_listings: list[Listing],
    removed_summaries: list[dict[str, Any]],
    total_current: int,
    run_at: datetime,
) -> tuple[str, str]:
    """Return (plain_text, html_text) for the notification email."""
    n_new = len(new_listings)
    n_rm = len(removed_summaries)
    ts = run_at.strftime("%Y-%m-%d %H:%M UTC")

    summary_bits: list[str] = []
    if n_new:
        summary_bits.append(f"{n_new} new listing{'s' if n_new != 1 else ''}")
    if n_rm:
        summary_bits.append(f"{n_rm} removed listing{'s' if n_rm != 1 else ''}")
    headline = "Vancouver House Finder — " + ", ".join(summary_bits)

    # ---- plain text ----
    lines = [
        headline,
        f"Run: {ts}  |  Total active listings: {total_current}",
        "",
    ]
    if new_listings:
        lines.append("NEW")
        lines.append("")
    for lst in new_listings:
        price = f"${lst.price_cad:,}" if lst.price_cad else "?"
        beds = _fmt_beds(lst.bedrooms)
        transit = f"{lst.transit_minutes_to_ubc} min to UBC" if lst.transit_minutes_to_ubc is not None else ""
        lines += [
            f"  {price} | {beds} bed | {transit}",
            f"  {lst.neighborhood or ''} — {lst.address_text or ''}",
            f"  [{lst.source}]  {lst.title or ''}",
            f"  {lst.url}",
            "",
        ]
    if removed_summaries:
        if new_listings:
            lines.append("")
        lines.append("REMOVED (no longer in filtered snapshot)")
        lines.append("")
    for s in removed_summaries:
        pc = s.get("price_cad")
        price = _price_display_stored(pc)
        beds = _fmt_beds(_beds_from_stored(s.get("bedrooms")))
        tm = s.get("transit_minutes_to_ubc")
        transit = (
            f"{int(tm)} min to UBC"
            if isinstance(tm, (int, float)) and not isinstance(tm, bool)
            else ""
        )
        url = s.get("url") or s.get("_key") or ""
        lines += [
            f"  {price} | {beds} bed | {transit}",
            f"  {s.get('neighborhood') or ''} — {s.get('address_text') or ''}",
            f"  [{s.get('source') or ''}]  {s.get('title') or ''}",
            f"  {url}",
            "",
        ]
    plain = "\n".join(lines)

    # ---- HTML ----
    cell = "padding:8px 12px;border:1px solid #e0e0e0;vertical-align:top;"
    head_cell = cell + "background:#f5f5f5;font-weight:600;white-space:nowrap;"

    sections: list[str] = []
    if new_listings:
        rows = "".join(_table_rows_from_listings(new_listings, cell))
        sections.append(
            f"""  <h3 style="margin-top:24px;color:#1a73e8;">New ({n_new})</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
{_thead_html(head_cell)}
    <tbody>
{rows}
    </tbody>
  </table>"""
        )
    if removed_summaries:
        rows = "".join(_table_rows_from_summaries(removed_summaries, cell))
        sections.append(
            f"""  <h3 style="margin-top:24px;color:#c5221f;">Removed ({n_rm})</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
{_thead_html(head_cell)}
    <tbody>
{rows}
    </tbody>
  </table>"""
        )

    html_body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"/></head>
<body style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;margin:24px;color:#222;">
  <h2 style="color:#1a73e8;margin-bottom:4px;">
    {headline}
  </h2>
  <p style="color:#666;margin-top:4px;font-size:14px;">{ts} &nbsp;·&nbsp; {total_current} total active listings</p>
{"".join(sections)}
</body>
</html>"""

    return plain, html_body


# ------------------------------------------------------------------ #
# SMTP send                                                            #
# ------------------------------------------------------------------ #

def _send_email(
    new_listings: list[Listing],
    removed_summaries: list[dict[str, Any]],
    total_current: int,
) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USERNAME", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    email_from = os.environ.get("EMAIL_FROM", "") or smtp_user
    email_to = os.environ.get("EMAIL_TO", "")
    recipients = _parse_recipients(email_to)

    if not all([smtp_host, smtp_user, smtp_pass, recipients]):
        _rich_console().print("  [yellow]SKIP[/yellow] Email: SMTP env vars not configured")
        return

    n_new = len(new_listings)
    n_rm = len(removed_summaries)
    run_at = datetime.now(UTC)
    sub_parts: list[str] = []
    if n_new:
        sub_parts.append(f"{n_new} new")
    if n_rm:
        sub_parts.append(f"{n_rm} removed")
    subject = "VHF: " + ", ".join(sub_parts)
    plain, html_body = _build_email(
        new_listings, removed_summaries, total_current, run_at
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(email_from, recipients, msg.as_string())

    _rich_console().print(
        f"  [green]Email sent[/green] -> {', '.join(recipients)}  ({subject})"
    )


def _parse_recipients(raw: str) -> list[str]:
    """Parse EMAIL_TO into a recipient list.

    Accepts comma, semicolon, or newline separated values.
    """
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,\n;]+", raw) if p.strip()]
    # Keep insertion order while removing accidental duplicates
    return list(dict.fromkeys(parts))


# ------------------------------------------------------------------ #
# Main entrypoint                                                      #
# ------------------------------------------------------------------ #

def run_notify() -> None:
    """Compare current listings against prior snapshot; email on changes."""
    _rich_console().print("[bold]Notify[/bold]")

    if not _LISTINGS_FILE.exists():
        _rich_console().print("  [yellow]SKIP[/yellow] listings.jsonl not found — run 'vhf' first")
        return

    listings = read_jsonl(_LISTINGS_FILE, Listing)
    current_map: dict[str, Listing] = listings_map_by_key(listings)
    prior_keys, prior_entries = _load_prior_state()

    is_first_run = len(prior_keys) == 0
    current_keys = set(current_map.keys())
    new_keys = current_keys - prior_keys
    removed_keys = prior_keys - current_keys

    new_listings = [current_map[k] for k in sorted(new_keys)]
    removed_summaries: list[dict[str, Any]] = []
    for k in sorted(removed_keys):
        base = dict(prior_entries.get(k, {}))
        if not base.get("url") and not base.get("title"):
            base = {**base, "_key": k}
        removed_summaries.append(base)

    _rich_console().print(f"  Prior known:   {len(prior_keys)}")
    _rich_console().print(f"  Current total: {len(current_map)}")
    _rich_console().print(f"  New listings:  {len(new_listings)}")
    _rich_console().print(f"  Removed:       {len(removed_summaries)}")

    if is_first_run:
        _rich_console().print(
            "  [yellow]First run — seeding state snapshot.[/yellow] "
            "No email sent. Future runs will notify on new or removed listings."
        )
    elif new_listings or removed_summaries:
        _send_email(new_listings, removed_summaries, len(listings))
    else:
        _rich_console().print("  No new or removed listings — nothing to send.")

    # Always update state after a successful check
    _save_state(current_map)
    _rich_console().print(f"  State saved -> {_STATE_FILE}")


if __name__ == "__main__":
    run_notify()
