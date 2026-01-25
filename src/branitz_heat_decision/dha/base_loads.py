from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


def load_base_loads_from_gebaeude_lastphasen(
    json_path: Path,
    *,
    scenario: str,
    unit: str = "AUTO",
    auto_unit_sample_size: int = 500,
) -> pd.Series:
    """
    Load **base electrical demand** (P_base) from `gebaeude_lastphasenV2.json`.

    File shape (legacy):
      { "<building_id>": { "<scenario_name>": <value>, ... }, ... }

    The values can be in kW or MW depending on the source. The legacy workflow uses a
    simple heuristic: if the median absolute value is < 0.1, treat as MW; else treat as kW.
    This function converts them into **kW** and returns:
      Series index=building_id (str), values=P_base_kw (float)
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Base load JSON not found: {json_path}")
    obj = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not obj:
        raise ValueError(f"Invalid base load JSON (expected dict of buildings): {json_path}")

    unit = (unit or "").strip().upper()
    if unit not in {"KW", "MW", "AUTO"}:
        raise ValueError("unit must be 'kW', 'MW', or 'AUTO'")

    # auto-detect unit from sample values for the requested scenario
    if unit == "AUTO":
        vals = []
        n = 0
        for _, rec in obj.items():
            if not isinstance(rec, dict) or scenario not in rec:
                continue
            try:
                vals.append(abs(float(rec.get(scenario, 0.0))))
                n += 1
            except Exception:
                continue
            if n >= int(auto_unit_sample_size):
                break
        med = float(pd.Series(vals).median()) if vals else 0.0
        unit = "MW" if med < 0.1 else "KW"

    mult = 1000.0 if unit == "MW" else 1.0  # convert to kW

    out: Dict[str, float] = {}
    missing = 0
    for bid, rec in obj.items():
        if not isinstance(rec, dict):
            continue
        if scenario not in rec:
            missing += 1
            continue
        try:
            out[str(bid)] = float(rec.get(scenario, 0.0)) * mult
        except Exception:
            out[str(bid)] = 0.0

    if not out:
        sample_keys = []
        try:
            sample_keys = list(next(iter(obj.values())).keys())  # type: ignore[attr-defined]
        except Exception:
            pass
        raise ValueError(
            f"No base loads could be read for scenario='{scenario}'. "
            f"Check the scenario name. Example keys: {sample_keys[:10]}"
        )

    s = pd.Series(out, name=f"p_base_kw__{scenario}")
    # Store detected unit (if auto was used) as metadata for audit/debugging
    try:
        s.attrs["source_unit"] = unit
    except Exception:
        pass
    return s

