from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BDEWPaths:
    """Paths for BDEW SLP inputs (CSV + mapping + optional population)."""

    bdew_profiles_csv: Path
    building_function_mapping_json: Optional[Path] = None
    building_population_json: Optional[Path] = None


def _default_bdew_paths() -> BDEWPaths:
    """
    Resolve BDEW input paths without hardcoding a specific cluster.

    Priority:
    1) data/raw/bdew_profiles.csv (project data)
    2) Legacy/fromDifferentThesis/load-profile-generator/bdew_profiles.csv (legacy reference)
    """
    repo_root = Path(__file__).resolve().parents[3]
    cand_csv = [
        repo_root / "data" / "raw" / "bdew_profiles.csv",
        repo_root / "Legacy" / "fromDifferentThesis" / "load-profile-generator" / "bdew_profiles.csv",
    ]
    csv_path = next((p for p in cand_csv if p.exists()), None)
    if csv_path is None:
        raise FileNotFoundError(
            "Could not find bdew_profiles.csv. Expected at data/raw/bdew_profiles.csv "
            "or Legacy/fromDifferentThesis/load-profile-generator/bdew_profiles.csv"
        )

    cand_map = [
        repo_root / "data" / "raw" / "bdew_slp_gebaeudefunktionen.json",
        repo_root / "Legacy" / "fromDifferentThesis" / "load-profile-generator" / "bdew_slp_gebaeudefunktionen.json",
    ]
    map_path = next((p for p in cand_map if p.exists()), None)

    cand_pop = [
        repo_root / "data" / "raw" / "building_population_resultsV6.json",
        repo_root / "Legacy" / "fromDifferentThesis" / "load-profile-generator" / "building_population_resultsV6.json",
    ]
    pop_path = next((p for p in cand_pop if p.exists()), None)

    return BDEWPaths(bdew_profiles_csv=csv_path, building_function_mapping_json=map_path, building_population_json=pop_path)


def _day_type(dt: datetime) -> str:
    # 0=Mon..6=Sun
    if dt.weekday() < 5:
        return "workday"
    if dt.weekday() == 5:
        return "saturday"
    return "sunday"


def _period(dt: datetime) -> str:
    # match BDEW CSV periods: winter/summer/transition
    m = dt.month
    if m in (12, 1, 2):
        return "winter"
    if m in (6, 7, 8):
        return "summer"
    return "transition"


def _h0_dynamic_factor(day_of_year: int) -> float:
    """
    BDEW H0 dynamic factor polynomial (as used in legacy generator).
    day_of_year: 1..365
    """
    a = -3.92e-10
    b = 3.20e-7
    c = -7.02e-5
    d = 2.10e-3
    e = 1.24
    return float(a * day_of_year**4 + b * day_of_year**3 + c * day_of_year**2 + d * day_of_year + e)


def _load_bdew_shapes(csv_path: Path) -> Dict[str, Dict[str, Dict[str, np.ndarray]]]:
    """
    Load BDEW shapes from CSV.
    Returns: shapes[profile_id][period][day] -> np.array(96) of watts (for 1000 kWh/a reference)
    """
    df = pd.read_csv(csv_path)
    required = {"profile_id", "period", "day", "timestamp", "watts"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"bdew_profiles.csv missing columns: {sorted(missing)}")

    shapes: Dict[str, Dict[str, Dict[str, np.ndarray]]] = {}
    for pid, g_pid in df.groupby("profile_id"):
        shapes[str(pid)] = {}
        for per, g_per in g_pid.groupby("period"):
            shapes[str(pid)][str(per)] = {}
            for day, g_day in g_per.groupby("day"):
                # ensure correct order by timestamp (00:00 .. 23:45)
                g_day = g_day.sort_values("timestamp")
                arr = pd.to_numeric(g_day["watts"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                if arr.shape[0] != 96:
                    raise ValueError(f"BDEW shape not 96 samples: profile={pid} period={per} day={day} n={arr.shape[0]}")
                shapes[str(pid)][str(per)][str(day)] = arr
    return shapes


def _household_consumption_kwh(residents: int) -> float:
    # Legacy BDEW household standards (kWh/a)
    r = int(residents) if residents and residents > 0 else 1
    if r == 1:
        return 1900.0
    if r == 2:
        return 2890.0
    if r == 3:
        return 3720.0
    if r == 4:
        return 4085.0
    # 5+ persons
    return 5430.0 + float(max(0, r - 5)) * 1020.0


def _load_population(pop_path: Optional[Path]) -> Dict[str, Dict[str, object]]:
    if pop_path is None or not pop_path.exists():
        return {}
    try:
        obj = json.loads(pop_path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _infer_profile_type(building_id: str, building_code: Optional[str], mapping_obj: Optional[dict]) -> str:
    """
    Map building code/id to BDEW profile types: H0, MIXED, G0..G6, L0, Y1.
    Falls back to H0.
    """
    bid = str(building_id)
    code = str(building_code) if building_code is not None else ""

    # Special bakery ID used in legacy
    if bid == "DEBBAL520000wboz":
        return "G5"

    if mapping_obj and isinstance(mapping_obj, dict):
        # H0
        if isinstance(mapping_obj.get("H0_Profile"), dict) and code in mapping_obj["H0_Profile"]:
            return "H0"
        # MIXED
        if isinstance(mapping_obj.get("50prozent_H0_50prozent_G0_Profile"), dict) and code in mapping_obj["50prozent_H0_50prozent_G0_Profile"]:
            return "MIXED"
        # Gewerbe grouped
        gew = mapping_obj.get("Gewerbe_Profile")
        if isinstance(gew, dict):
            for gk in ("G0", "G1", "G2", "G3", "G4", "G5", "G6"):
                rec = gew.get(gk)
                if isinstance(rec, dict) and code in rec:
                    return gk
        # Landwirtschaft
        land = mapping_obj.get("Landwirtschaft_Profile")
        if isinstance(land, dict) and isinstance(land.get("L0"), dict) and code in land["L0"]:
            return "L0"
        # Y1
        y1 = mapping_obj.get("Y1_Lastprofil")
        if isinstance(y1, dict) and isinstance(y1.get("codes"), dict) and code in y1["codes"]:
            return "Y1"

    # Reasonable fallback
    return "H0"


def _yearly_consumption_kwh(
    *,
    profile_type: str,
    building_id: str,
    building_code: Optional[str],
    floor_area_m2: Optional[float],
    population_obj: Mapping[str, object],
) -> float:
    """
    Estimate annual electricity consumption in kWh/a for scaling.
    Mirrors the legacy assumptions (best-effort).
    """
    pt = str(profile_type)
    bid = str(building_id)
    code = str(building_code) if building_code is not None else ""
    area = float(floor_area_m2) if floor_area_m2 is not None and np.isfinite(float(floor_area_m2)) else 0.0

    # Special fixed consumptions (from legacy constants / mapping json)
    if code == "2512":  # Pumpstation
        return 45000.0

    if pt == "Y1":
        # simple buildings; legacy generator uses 0.75 kWh/m²/a (their constants.py)
        return max(0.0, area) * 0.75

    if pt in {"G0", "G1", "G2", "G3", "G4", "G6"}:
        per_sqm = {
            "G0": 73.93,
            "G1": 85.0,
            "G2": 120.0,
            "G3": 180.0,
            "G4": 95.0,
            "G6": 250.0,
        }[pt]
        if area <= 0:
            # fallback: small commercial
            return 10000.0
        return area * per_sqm

    if pt == "G5":
        # bakeries are energy intensive; legacy constants use 350 kWh/m²/a
        if area <= 0:
            return 35000.0
        return area * 350.0

    # H0 / MIXED: use household distribution if present
    pop = population_obj.get(bid)
    if isinstance(pop, dict):
        hh_list = pop.get("Haushaltsverteilung")
        if isinstance(hh_list, list) and hh_list:
            total = 0.0
            for hh in hh_list:
                if not isinstance(hh, dict):
                    continue
                total += _household_consumption_kwh(int(hh.get("einwohner", 1) or 1))
            if total > 0:
                return total
        # fallback: computed residents if present
        try:
            residents = int(pop.get("BerechneteEinwohner", 0) or 0)
            households = int(pop.get("BerechneteHaushalte", 0) or 0)
            if residents > 0 and households > 0:
                # approximate: evenly distribute residents across households
                per = max(1, int(round(residents / households)))
                return float(households) * _household_consumption_kwh(per)
        except Exception:
            pass

    # final fallback: one 2-person household
    base_h0 = 2890.0
    if pt == "MIXED":
        # 50% household + 50% small commercial
        comm = (area * 73.93) if area > 0 else 8000.0
        return 0.5 * base_h0 + 0.5 * comm
    return base_h0


def compute_bdew_base_loads_for_hours(
    buildings_df: pd.DataFrame,
    *,
    hours: Iterable[int],
    year: int = 2023,
    paths: Optional[BDEWPaths] = None,
) -> pd.DataFrame:
    """Compute per-building base electricity P_base (kW) for the requested hour indices."""
    base_df, _assumptions = compute_bdew_base_loads_for_hours_and_assumptions(
        buildings_df=buildings_df,
        hours=hours,
        year=year,
        paths=paths,
        require_population=False,
    )
    return base_df


def compute_bdew_base_loads_for_hours_and_assumptions(
    buildings_df: pd.DataFrame,
    *,
    hours: Iterable[int],
    year: int = 2023,
    paths: Optional[BDEWPaths] = None,
    require_population: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute per-building base electricity P_base (kW) for the requested hour indices,
    AND return an auditable per-building assumptions table.

    Returns:
      - base_df: index=hour (int), columns=building_id (str), values=kW
      - assumptions_df: rows per building_id with profile_type + yearly_kwh + inputs used
    """
    hours_list = [int(h) for h in hours]
    if not hours_list:
        raise ValueError("hours is empty")

    paths = paths or _default_bdew_paths()
    if require_population:
        if paths.building_population_json is None:
            raise ValueError(
                "BDEW base loads require an explicit building population file "
                "(building_population_resultsV6.json) for deterministic H0 scaling."
            )
        if not Path(paths.building_population_json).exists():
            raise FileNotFoundError(f"Population JSON not found: {paths.building_population_json}")

    shapes = _load_bdew_shapes(paths.bdew_profiles_csv)

    mapping_obj = None
    if paths.building_function_mapping_json and paths.building_function_mapping_json.exists():
        try:
            mapping_obj = json.loads(paths.building_function_mapping_json.read_text(encoding="utf-8"))
        except Exception:
            mapping_obj = None

    population_obj = _load_population(paths.building_population_json)

    if "building_id" not in buildings_df.columns:
        raise ValueError("buildings_df must contain building_id")
    b = buildings_df.copy()
    b["building_id"] = b["building_id"].astype(str)

    # Precompute per-building profile type + yearly consumption scaling
    meta: Dict[str, Dict[str, object]] = {}
    for _, r in b.iterrows():
        bid = str(r.get("building_id"))
        code = r.get("building_code")
        area = r.get("floor_area_m2")
        pt = _infer_profile_type(bid, code, mapping_obj)
        yearly = _yearly_consumption_kwh(
            profile_type=pt,
            building_id=bid,
            building_code=str(code) if code is not None else None,
            floor_area_m2=float(area) if area is not None else None,
            population_obj=population_obj,
        )
        meta[bid] = {"profile_type": pt, "yearly_kwh": float(yearly)}

    assumptions_rows: List[Dict[str, object]] = []
    for _, r in b.iterrows():
        bid = str(r.get("building_id"))
        m = meta.get(bid, {})
        assumptions_rows.append(
            {
                "building_id": bid,
                "building_code": r.get("building_code"),
                "floor_area_m2": r.get("floor_area_m2"),
                "profile_type": m.get("profile_type"),
                "yearly_kwh_assumed": m.get("yearly_kwh"),
                "bdew_profiles_csv": str(paths.bdew_profiles_csv),
                "bdew_mapping_json": str(paths.building_function_mapping_json) if paths.building_function_mapping_json else None,
                "population_json": str(paths.building_population_json) if paths.building_population_json else None,
            }
        )
    assumptions_df = pd.DataFrame(assumptions_rows)

    # Compute per-hour base loads
    out = pd.DataFrame(index=hours_list, columns=b["building_id"].tolist(), dtype=float)
    start = datetime(int(year), 1, 1, 0, 0, 0)

    for hour in hours_list:
        dt = start + timedelta(hours=int(hour))
        per = _period(dt)
        day = _day_type(dt)
        doy = int(dt.timetuple().tm_yday)

        # Quarter-hour indices within the day
        q0 = int(dt.hour) * 4
        qs = [q0, q0 + 1, q0 + 2, q0 + 3]

        for bid, m in meta.items():
            pt = str(m["profile_type"])
            yearly = float(m["yearly_kwh"])
            scale = yearly / 1000.0  # BDEW shapes are normalized to 1000 kWh/a

            # Use BDEW profile id for this type. For MIXED we blend 50% H0 + 50% G0.
            if pt == "MIXED":
                h0 = shapes["H0"][per][day][qs].mean() * (0.5 * _household_consumption_kwh(2) / 1000.0)  # baseline
                g0 = shapes["G0"][per][day][qs].mean() * (0.5 * max(0.0, yearly) / 1000.0)
                watts = h0 + g0
            else:
                pid = "H0" if pt == "H0" else pt
                if pid not in shapes:
                    pid = "H0"
                watts = float(shapes[pid][per][day][qs].mean()) * scale

            # Apply H0 dynamic factor (legacy behavior)
            if pt == "H0":
                watts *= _h0_dynamic_factor(doy)

            out.at[hour, bid] = max(0.0, watts / 1000.0)  # W -> kW

    out.index.name = "hour"
    return out, assumptions_df

