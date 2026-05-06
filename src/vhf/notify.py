"""New-listing detection and email notification.

Run as:
    python -m vhf.notify

Compares the current listings.jsonl against the prior state snapshot.
Sends one aggregated email if new listings are found, then updates the
state file so the next run only fires on genuinely new entries.
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

from rich.console import Console

from .models import Listing
from .paths import PROCESSED_DIR, STATE_DIR
from .storage import read_jsonl

console = Console()

_STATE_FILE = STATE_DIR / "last_seen.json"
_LISTINGS_FILE = PROCESSED_DIR / "listings.jsonl"


# ------------------------------------------------------------------ #
# State helpers                                                        #
# ------------------------------------------------------------------ #

def _listing_key(listing: Listing) -> str:
    """Stable identifier for a listing across runs."""
    if listing.source_listing_id:
        return f"{listing.source}:{listing.source_listing_id}"
    return str(listing.url).lower().rstrip("/")


def _load_prior_keys() -> set[str]:
    if not _STATE_FILE.exists():
        return set()
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return set(data.get("keys", []))
    except Exception:
        return set()


def _save_state(keys: set[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(
            {"keys": sorted(keys), "updated_at": datetime.now(UTC).isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ #
# Email builder                                                        #
# ------------------------------------------------------------------ #

def _fmt_beds(beds: float | None) -> str:
    if beds is None:
        return "?"
    return str(int(beds)) if beds == int(beds) else str(beds)


def _build_email(
    new_listings: list[Listing],
    total_current: int,
    run_at: datetime,
) -> tuple[str, str]:
    """Return (plain_text, html_text) for the notification email."""
    n = len(new_listings)
    ts = run_at.strftime("%Y-%m-%d %H:%M UTC")

    # ---- plain text ----
    lines = [
        f"Vancouver House Finder — {n} new listing{'s' if n != 1 else ''} found",
        f"Run: {ts}  |  Total active listings: {total_current}",
        "",
    ]
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
    plain = "\n".join(lines)

    # ---- HTML ----
    cell = "padding:8px 12px;border:1px solid #e0e0e0;vertical-align:top;"
    head_cell = cell + "background:#f5f5f5;font-weight:600;white-space:nowrap;"

    rows_html: list[str] = []
    for i, lst in enumerate(new_listings):
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
            f'<td style="{cell}">{price}</td>'
            f'<td style="{cell}">{beds}</td>'
            f'<td style="{cell}">{transit}</td>'
            f'<td style="{cell}">{neigh}</td>'
            f'<td style="{cell}">{address}</td>'
            f'<td style="{cell}">{source}</td>'
            f'<td style="{cell}"><a href="{url}" style="color:#1a73e8">link</a></td>'
            f'<td style="{cell}">{title}</td>'
            "</tr>"
        )

    html_body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"/></head>
<body style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;margin:24px;color:#222;">
  <h2 style="color:#1a73e8;margin-bottom:4px;">
    Vancouver House Finder — {n} new listing{'s' if n != 1 else ''} found
  </h2>
  <p style="color:#666;margin-top:4px;font-size:14px;">{ts} &nbsp;·&nbsp; {total_current} total active listings</p>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead>
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
    </thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
</body>
</html>"""

    return plain, html_body


# ------------------------------------------------------------------ #
# SMTP send                                                            #
# ------------------------------------------------------------------ #

def _send_email(new_listings: list[Listing], total_current: int) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USERNAME", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    email_from = os.environ.get("EMAIL_FROM", "") or smtp_user
    email_to = os.environ.get("EMAIL_TO", "")
    recipients = _parse_recipients(email_to)

    if not all([smtp_host, smtp_user, smtp_pass, recipients]):
        console.print("  [yellow]SKIP[/yellow] Email: SMTP env vars not configured")
        return

    n = len(new_listings)
    run_at = datetime.now(UTC)
    subject = f"VHF: {n} new Vancouver listing{'s' if n != 1 else ''} found"
    plain, html_body = _build_email(new_listings, total_current, run_at)

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

    console.print(
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
    """Compare current listings against prior snapshot; email if new ones exist."""
    console.print("[bold]Notify[/bold]")

    if not _LISTINGS_FILE.exists():
        console.print("  [yellow]SKIP[/yellow] listings.jsonl not found — run 'vhf' first")
        return

    listings = read_jsonl(_LISTINGS_FILE, Listing)
    current_map: dict[str, Listing] = {_listing_key(l): l for l in listings}
    prior_keys = _load_prior_keys()

    is_first_run = len(prior_keys) == 0
    new_keys = set(current_map.keys()) - prior_keys
    new_listings = [current_map[k] for k in new_keys]

    console.print(f"  Prior known:   {len(prior_keys)}")
    console.print(f"  Current total: {len(current_map)}")
    console.print(f"  New listings:  {len(new_listings)}")

    if is_first_run:
        console.print(
            "  [yellow]First run — seeding state snapshot.[/yellow] "
            "No email sent. Future runs will notify on new listings."
        )
    elif new_listings:
        _send_email(new_listings, len(listings))
    else:
        console.print("  No new listings — nothing to send.")

    # Always update state after a successful check
    _save_state(set(current_map.keys()))
    console.print(f"  State saved -> {_STATE_FILE}")


if __name__ == "__main__":
    run_notify()
