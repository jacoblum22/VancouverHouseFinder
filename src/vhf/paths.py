from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    # This file lives at: <root>/src/vhf/paths.py
    return Path(__file__).resolve().parents[2]


DATA_DIR = repo_root() / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORTS_DIR = DATA_DIR / "exports"
STATE_DIR = DATA_DIR / "state"
LOGS_DIR = repo_root() / "logs"

