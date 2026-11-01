"""Public, no-login job sources. Each module exposes fetch(board: dict, query: str) -> list[Job]."""

from . import ashby, greenhouse, lever, workday

REGISTRY = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workday": workday,
}
