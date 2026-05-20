"""Train / suggest labels for whole-unit vs room-or-partial (optional ``scikit-learn`` extra).

Uses a **small hand-engineered feature vector** (substring flags + price / bedrooms /
price-per-bedroom), ``SimpleImputer`` (median), and **L2** ``LogisticRegression``.

**Train CV** uses **leave-one-out** (appropriate for ~50–100 labels).
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

from .listing_labels import DEFAULT_LABELS_PATH, read_listing_kind_labels
from .paths import EXPORTS_DIR

BINARY_LABELS = frozenset({"whole_unit", "room_or_partial"})

# Column order matches ``_hand_engineered_features`` return value.
LISTING_KIND_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "has_room_for",
    "has_entire_home",
    "has_private_room",
    "price_cad",
    "n_bedrooms",
    "price_per_bedroom",
)

_ENTIRE_HOME_PHRASES: Final[tuple[str, ...]] = (
    "entire home",
    "whole house",
    "whole apt",
    "entire apt",
)
_PRIVATE_ROOM_PHRASES: Final[tuple[str, ...]] = ("private room", "shared room")


def _require_sklearn() -> None:
    try:
        import sklearn  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Listing-kind ML requires scikit-learn. Install with: pip install -e '.[ml]'"
        ) from e


def _parse_float(s: str) -> float | None:
    t = (s or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    t = (s or "").strip()
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def load_export_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing export CSV: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def row_listing_key(row: dict[str, str]) -> str:
    """Match ``state_file.listing_key``; supports exports without a ``listing_key`` column."""
    k = (row.get("listing_key") or "").strip()
    if k:
        return k
    src = (row.get("source") or "").strip()
    sid = (row.get("source_listing_id") or "").strip()
    if src and sid:
        return f"{src}:{sid}"
    url = (row.get("url") or "").strip()
    if url:
        return url.lower().rstrip("/")
    return ""


def _combined_text(row: dict[str, str]) -> str:
    title = (row.get("title") or "").strip()
    desc = (row.get("description") or "").strip()
    if title and desc:
        return f"{title}\n{desc}"
    return title or desc


def _hand_engineered_features(row: dict[str, str]) -> list[float]:
    """Fixed-length vector aligned with ``LISTING_KIND_FEATURE_NAMES``."""
    text = _combined_text(row).lower()
    p = _parse_int(row.get("price_cad") or "")
    b = _parse_float(row.get("bedrooms") or "")
    price = float(p) if p is not None else math.nan
    bedrooms = float(b) if b is not None else math.nan

    has_room_for = 1.0 if "room for" in text else 0.0
    has_entire_home = 1.0 if any(ph in text for ph in _ENTIRE_HOME_PHRASES) else 0.0
    has_private_room = 1.0 if any(ph in text for ph in _PRIVATE_ROOM_PHRASES) else 0.0

    if not math.isnan(price) and not math.isnan(bedrooms) and bedrooms > 0:
        price_per_bedroom = price / bedrooms
    else:
        price_per_bedroom = math.nan

    return [
        has_room_for,
        has_entire_home,
        has_private_room,
        price,
        bedrooms,
        price_per_bedroom,
    ]


@dataclass
class TrainReport:
    n_fit: int
    n_whole_unit: int
    n_room_or_partial: int
    cv_accuracy: float
    cv_f1_room: float
    cv_scheme: str = "leave_one_out"
    feature_names: tuple[str, ...] = LISTING_KIND_FEATURE_NAMES


def train_listing_kind(
    *,
    export_csv: Path | None = None,
    labels_csv: Path | None = None,
    random_state: int = 42,
) -> TrainReport:
    """Leave-one-out CV on binary labels (excludes ``unclear``)."""
    _require_sklearn()
    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import LeaveOneOut

    x_path = export_csv or (EXPORTS_DIR / "results.csv")
    labels = read_listing_kind_labels(labels_csv)
    rows = load_export_rows(x_path)

    keys_fit: list[str] = []
    X_rows: list[list[float]] = []
    y: list[int] = []

    for row in rows:
        key = row_listing_key(row)
        if not key or key not in labels:
            continue
        lab = labels[key]
        if lab not in BINARY_LABELS:
            continue
        keys_fit.append(key)
        X_rows.append(_hand_engineered_features(row))
        y.append(1 if lab == "room_or_partial" else 0)

    n = len(y)
    if n < 4:
        raise ValueError(
            f"Need at least 4 labeled rows with whole_unit or room_or_partial (got {n}). "
            "Add rows to the labels CSV joined on listing_key."
        )
    n_room = sum(y)
    n_whole = n - n_room
    if n_room == 0 or n_whole == 0:
        raise ValueError(
            "Need at least one row of each binary class (whole_unit and room_or_partial)."
        )

    y_arr = np.array(y, dtype=int)
    X_arr = np.asarray(X_rows, dtype=float)
    y_hat = np.empty(n, dtype=int)
    loo = LeaveOneOut()

    for train_idx, test_idx in loo.split(np.zeros((n, 1)), y_arr):
        hi = int(test_idx[0])
        X_tr = X_arr[train_idx]
        X_te = X_arr[test_idx]
        y_tr = y_arr[train_idx]

        imputer = SimpleImputer(strategy="median")
        X_tr_i = imputer.fit_transform(X_tr)
        X_te_i = imputer.transform(X_te)

        clf = LogisticRegression(
            penalty="l2",
            solver="lbfgs",
            max_iter=2000,
            C=0.1,
            class_weight="balanced",
            random_state=random_state,
        )
        clf.fit(X_tr_i, y_tr)
        y_hat[test_idx] = clf.predict(X_te_i)

        logger.debug(
            "LOO held_out=%s idx=%d label=%s y_hat=%s X_te=%s",
            keys_fit[hi],
            hi,
            "room_or_partial" if y_arr[hi] == 1 else "whole_unit",
            int(y_hat[test_idx][0]),
            X_te_i[0].tolist(),
        )

    acc = float(accuracy_score(y_arr, y_hat))
    f1 = float(f1_score(y_arr, y_hat, pos_label=1, zero_division=0))
    logger.info(
        "Listing-kind LOO: n=%d accuracy=%.3f F1(room)=%.3f features=%s",
        n,
        acc,
        f1,
        list(LISTING_KIND_FEATURE_NAMES),
    )

    return TrainReport(
        n_fit=n,
        n_whole_unit=n_whole,
        n_room_or_partial=n_room,
        cv_accuracy=acc,
        cv_f1_room=f1,
        cv_scheme="leave_one_out",
        feature_names=LISTING_KIND_FEATURE_NAMES,
    )


@dataclass
class Suggestion:
    listing_key: str
    url: str
    title: str
    p_room: float


def suggest_listing_kind_labels(
    *,
    export_csv: Path | None = None,
    labels_csv: Path | None = None,
    top_n: int = 15,
    random_state: int = 42,
) -> list[Suggestion]:
    """Fit on all binary-labeled rows; return most uncertain unlabeled rows."""
    _require_sklearn()
    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression

    x_path = export_csv or (EXPORTS_DIR / "results.csv")
    l_path = labels_csv or DEFAULT_LABELS_PATH
    labels = read_listing_kind_labels(l_path)
    rows = load_export_rows(x_path)

    fit_X: list[list[float]] = []
    fit_y: list[int] = []

    for row in rows:
        key = row_listing_key(row)
        if not key or key not in labels:
            continue
        lab = labels[key]
        if lab not in BINARY_LABELS:
            continue
        fit_X.append(_hand_engineered_features(row))
        fit_y.append(1 if lab == "room_or_partial" else 0)

    n_fit = len(fit_y)
    if n_fit < 4 or sum(fit_y) == 0 or sum(fit_y) == n_fit:
        raise ValueError(
            "Suggest needs the same labeled diversity as train: ≥4 rows and at least one "
            "whole_unit and one room_or_partial."
        )

    X_fit = np.asarray(fit_X, dtype=float)
    imputer = SimpleImputer(strategy="median")
    X_fit_i = imputer.fit_transform(X_fit)

    clf = LogisticRegression(
        penalty="l2",
        solver="lbfgs",
        max_iter=2000,
        C=0.1,
        class_weight="balanced",
        random_state=random_state,
    )
    clf.fit(X_fit_i, fit_y)

    keys_urls_titles: list[tuple[str, str, str]] = []
    X_u: list[list[float]] = []

    for row in rows:
        key = row_listing_key(row)
        if not key or key in labels:
            continue
        keys_urls_titles.append(
            (key, (row.get("url") or "").strip(), (row.get("title") or "").strip())
        )
        X_u.append(_hand_engineered_features(row))

    if not keys_urls_titles:
        return []

    X_u_i = imputer.transform(np.asarray(X_u, dtype=float))
    proba = clf.predict_proba(X_u_i)[:, 1]

    # Closest to decision boundary in probability space (smallest |p - 0.5|).
    scored: list[tuple[float, int]] = []
    for i, p_room in enumerate(proba.tolist()):
        p = float(p_room)
        scored.append((abs(p - 0.5), i))
    scored.sort(key=lambda t: t[0])

    out: list[Suggestion] = []
    for _, i in scored[:top_n]:
        key, url, title = keys_urls_titles[i]
        out.append(Suggestion(listing_key=key, url=url, title=title, p_room=float(proba[i])))
    return out
