"""Load profile/search.toml (falls back to config/search.example.toml)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG = ROOT / "profile" / "search.toml"
EXAMPLE_CONFIG = ROOT / "config" / "search.example.toml"
DATA = ROOT / "data"


def load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else (USER_CONFIG if USER_CONFIG.exists() else EXAMPLE_CONFIG)
    with open(p, "rb") as fh:
        cfg = tomllib.load(fh)
    cfg.setdefault("search", {})
    cfg.setdefault("linkedin", {})
    cfg.setdefault("feeds", {})
    cfg.setdefault("boards", [])
    cfg["_path"] = str(p)
    return cfg
