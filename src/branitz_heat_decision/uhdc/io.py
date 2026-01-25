from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, cast


def load_json(path: Path) -> Dict[str, Any]:
    return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_kpi_contract(path: Path) -> Dict[str, Any]:
    return load_json(path)


def load_cha_kpis(path: Path) -> Dict[str, Any]:
    return load_json(path)


def load_dha_kpis(path: Path) -> Dict[str, Any]:
    return load_json(path)


def load_econ_summary(path: Path) -> Dict[str, Any]:
    return load_json(path)

