"""Loader for corpus/registry.yaml — the single source of truth for
onrecord's corpus adapters (design spec Sec 2.2): youtube channels, tickers,
and regulatory docket sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "corpus" / "registry.yaml"


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Load and parse corpus/registry.yaml.

    Returns a dict with (at least) the top-level keys `youtube_channels`,
    `tickers`, and `docket_sources`, each a list of mappings.
    """
    registry_path = Path(path) if path is not None else _REGISTRY_PATH
    with registry_path.open() as fh:
        data = yaml.safe_load(fh)
    return data
