from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[4]
REGISTRY_PATH = ROOT_DIR / "courseware" / "components" / "registry.json"


def load_component_registry() -> dict[str, dict[str, Any]]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {
        name: config
        for name, config in data.items()
        if not name.startswith("$") and isinstance(config, dict)
    }


def supported_component_types(include_experimental: bool = False) -> set[str]:
    registry = load_component_registry()
    return {
        name
        for name, config in registry.items()
        if include_experimental or not bool(config.get("experimental"))
    }
