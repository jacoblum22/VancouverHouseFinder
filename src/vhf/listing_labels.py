"""Human labels for listing-kind (whole unit vs room/partial) keyed like ``state_file.listing_key``."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .paths import LABELS_DIR
from .state_file import listing_key

DEFAULT_LABELS_PATH: Final[Path] = LABELS_DIR / "listing_kind_labels.csv"

LISTING_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {"whole_unit", "room_or_partial", "unclear"}
)

_FIELDNAMES: Final[tuple[str, ...]] = ("listing_key", "label", "labeled_at", "notes")

__all__ = [
    "DEFAULT_LABELS_PATH",
    "LISTING_KIND_VALUES",
    "append_listing_kind_label",
    "init_labels_file",
    "listing_key",
    "read_listing_kind_labels",
]


def init_labels_file(path: Path | None = None) -> bool:
    """Create parent dirs and write CSV header if the file is missing.

    Returns True if a new file was created, False if it already existed.
    """
    target = path or DEFAULT_LABELS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return False
    with target.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(_FIELDNAMES))
        w.writeheader()
    return True


def read_listing_kind_labels(path: Path | None = None) -> dict[str, str]:
    """Return ``listing_key -> label`` for the latest row per key (file order wins)."""
    target = path or DEFAULT_LABELS_PATH
    if not target.is_file():
        return {}
    out: dict[str, str] = {}
    with target.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames is None:
            return out
        have = {h.strip() for h in r.fieldnames if h and h.strip()}
        required = set(_FIELDNAMES)
        if not required.issubset(have):
            raise ValueError(
                f"Labels CSV missing columns {sorted(required - have)}; "
                f"expected at least {sorted(required)}"
            )
        for row in r:
            row_key = (row.get("listing_key") or "").strip()
            label = (row.get("label") or "").strip()
            if not row_key:
                continue
            if label not in LISTING_KIND_VALUES:
                raise ValueError(f"Invalid label {label!r} for listing_key {row_key!r}")
            out[row_key] = label
    return out


def append_listing_kind_label(
    path: Path | None = None,
    *,
    row_key: str,
    label: str,
    notes: str = "",
    labeled_at: datetime | None = None,
) -> None:
    """Append one label row. Creates the file (with header) if needed."""
    if label not in LISTING_KIND_VALUES:
        raise ValueError(
            f"label must be one of {sorted(LISTING_KIND_VALUES)}, got {label!r}"
        )
    target = path or DEFAULT_LABELS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = (labeled_at or datetime.now(UTC)).isoformat()
    new_file = not target.exists()
    with target.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(_FIELDNAMES))
        if new_file:
            w.writeheader()
        w.writerow(
            {
                "listing_key": row_key,
                "label": label,
                "labeled_at": stamp,
                "notes": notes,
            }
        )
