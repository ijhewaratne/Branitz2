"""
ADK Tools Module

Tool wrappers for existing Branitz Heat Decision pipeline components.
These tools wrap existing scripts/CLIs/functions without modifying them.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


def prepare_data_tool(
    buildings_path: Optional[str] = None,
    streets_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for data preparation pipeline (00_prepare_data.py).
    
    Args:
        buildings_path: Path to buildings GeoJSON (optional)
        streets_path: Path to streets GeoJSON (optional)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import (
        BUILDINGS_PATH,
        BUILDING_CLUSTER_MAP_PATH,
        HOURLY_PROFILES_PATH,
        DESIGN_TOPN_PATH,
    )
    
    # Path calculation: tools.py is at src/branitz_heat_decision/adk/tools.py
    # parents[2] = src/, so scripts/ is at src/scripts/
    src_dir = Path(__file__).parents[2]
    cmd = [
        sys.executable,
        str(src_dir / "scripts" / "00_prepare_data.py"),
        "--create-clusters",
    ]
    
    if buildings_path:
        cmd.extend(["--buildings", buildings_path])
    if streets_path:
        cmd.extend(["--streets", streets_path])
    if verbose:
        cmd.append("--verbose")
    
    logger.info(f"[ADK Tool] Running data preparation: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        outputs = {
            "buildings": BUILDINGS_PATH.exists(),
            "cluster_map": BUILDING_CLUSTER_MAP_PATH.exists(),
            "profiles": HOURLY_PROFILES_PATH.exists(),
            "design_topn": DESIGN_TOPN_PATH.exists(),
        }
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# Default CHP plant location (Cottbus) - used whenever CHA is run
DEFAULT_PLANT_LAT = 51.76274
DEFAULT_PLANT_LON = 14.3453979


def run_cha_tool(
    cluster_id: str,
    use_trunk_spur: bool = True,
    plant_wgs84_lat: Optional[float] = DEFAULT_PLANT_LAT,
    plant_wgs84_lon: Optional[float] = DEFAULT_PLANT_LON,
    disable_auto_plant_siting: bool = True,
    optimize_convergence: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for CHA pipeline (01_run_cha.py).
    
    Args:
        cluster_id: Cluster identifier (e.g., ST010_HEINRICH_ZILLE_STRASSE)
        use_trunk_spur: Use trunk-spur network builder (default: True)
        plant_wgs84_lat: Fixed plant latitude (WGS84)
        plant_wgs84_lon: Fixed plant longitude (WGS84)
        disable_auto_plant_siting: Disable automatic re-siting
        optimize_convergence: Enable convergence optimization
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    # Path calculation: tools.py is at src/branitz_heat_decision/adk/tools.py
    # parents[2] = src/, so scripts/ is at src/scripts/
    src_dir = Path(__file__).parents[2]
    cmd = [
        sys.executable,
        str(src_dir / "scripts" / "01_run_cha.py"),
        "--cluster-id", cluster_id,
    ]
    
    if use_trunk_spur:
        cmd.append("--use-trunk-spur")
    # Fixed CHP plant location (default) - always pass unless explicitly overridden
    lat = DEFAULT_PLANT_LAT if plant_wgs84_lat is None else plant_wgs84_lat
    lon = DEFAULT_PLANT_LON if plant_wgs84_lon is None else plant_wgs84_lon
    cmd.extend(["--plant-wgs84-lat", str(lat)])
    cmd.extend(["--plant-wgs84-lon", str(lon)])
    if disable_auto_plant_siting:
        cmd.append("--disable-auto-plant-siting")
    if optimize_convergence:
        cmd.append("--optimize-convergence")
    if verbose:
        cmd.append("--verbose")
    
    logger.info(f"[ADK Tool] Running CHA pipeline: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        output_dir = resolve_cluster_path(cluster_id, "cha")
        outputs = {
            "kpis": (output_dir / "cha_kpis.json").exists(),
            "network": (output_dir / "network.pickle").exists(),
            "map_velocity": (output_dir / "interactive_map.html").exists(),
            "map_temperature": (output_dir / "interactive_map_temperature.html").exists(),
            "map_pressure": (output_dir / "interactive_map_pressure.html").exists(),
        }
        
        # Load convergence status from KPIs
        convergence = None
        if outputs["kpis"]:
            try:
                with open(output_dir / "cha_kpis.json", "r") as f:
                    kpis = json.load(f)
                    convergence = kpis.get("convergence", {})
            except Exception:
                pass
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
            "convergence": convergence,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def run_dha_tool(
    cluster_id: str,
    cop: float = 2.8,
    base_load_source: str = "scenario_json",
    bdew_population_json: Optional[str] = None,
    hp_three_phase: bool = True,
    topn: int = 10,
    grid_source: str = "legacy_json",
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for DHA pipeline (02_run_dha.py).
    
    Args:
        cluster_id: Cluster identifier
        cop: Heat pump COP (default: 2.8)
        base_load_source: Base load source (scenario_json or bdew_timeseries)
        bdew_population_json: Path to BDEW population JSON (required for bdew_timeseries)
        hp_three_phase: Model HP loads as balanced 3-phase (default: True)
        topn: Number of top hours to include (default: 10)
        grid_source: Grid source (legacy_json or geodata)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    # Path calculation: tools.py is at src/branitz_heat_decision/adk/tools.py
    # parents[2] = src/, so scripts/ is at src/scripts/
    src_dir = Path(__file__).parents[2]
    cmd = [
        sys.executable,
        str(src_dir / "scripts" / "02_run_dha.py"),
        "--cluster-id", cluster_id,
        "--cop", str(cop),
        "--base-load-source", base_load_source,
        "--topn", str(topn),
        "--grid-source", grid_source,
    ]
    
    if base_load_source == "bdew_timeseries":
        if not bdew_population_json:
            return {
                "status": "error",
                "error": "bdew_population_json required for bdew_timeseries base load source",
            }
        cmd.extend(["--bdew-population-json", bdew_population_json])
    
    if hp_three_phase:
        cmd.append("--hp-three-phase")
    else:
        cmd.append("--single-phase")
    
    logger.info(f"[ADK Tool] Running DHA pipeline: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        output_dir = resolve_cluster_path(cluster_id, "dha")
        outputs = {
            "kpis": (output_dir / "dha_kpis.json").exists(),
            "buses": (output_dir / "buses_results.geojson").exists(),
            "lines": (output_dir / "lines_results.geojson").exists(),
            "violations": (output_dir / "violations.csv").exists(),
            "map": (output_dir / "hp_lv_map.html").exists(),
        }
        
        # Load violations count from KPIs
        violations = None
        if outputs["kpis"]:
            try:
                with open(output_dir / "dha_kpis.json", "r") as f:
                    kpis = json.load(f)
                    violations = {
                        "voltage": kpis.get("kpis", {}).get("voltage_violations_total", 0),
                        "line": kpis.get("kpis", {}).get("line_violations_total", 0),
                    }
            except Exception:
                pass
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
            "violations": violations,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def run_economics_tool(
    cluster_id: str,
    n_samples: int = 500,
    seed: int = 42,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for economics pipeline (03_run_economics.py or cli/economics.py).
    
    Args:
        cluster_id: Cluster identifier
        n_samples: Monte Carlo samples (default: 500)
        seed: Random seed (default: 42)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    # Path calculation: tools.py is at src/branitz_heat_decision/adk/tools.py
    # parents[2] = src/, so scripts/ is at src/scripts/
    src_dir = Path(__file__).parents[2]
    cmd = [
        sys.executable,
        str(src_dir / "scripts" / "03_run_economics.py"),
        "--cluster-id", cluster_id,
        "--n", str(n_samples),
        "--seed", str(seed),
    ]
    
    logger.info(f"[ADK Tool] Running economics pipeline: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        output_dir = resolve_cluster_path(cluster_id, "economics")
        outputs = {
            "deterministic": (output_dir / "economics_deterministic.json").exists(),
            "monte_carlo_summary": (output_dir / "monte_carlo_summary.json").exists(),
            "monte_carlo_samples": (output_dir / "monte_carlo_samples.parquet").exists(),
        }
        
        # Load win fractions from Monte Carlo summary
        win_fractions = None
        if outputs["monte_carlo_summary"]:
            try:
                with open(output_dir / "monte_carlo_summary.json", "r") as f:
                    summary = json.load(f)
                    win_fractions = summary.get("monte_carlo", {}).get("dh_wins_fraction", 0.0)
            except Exception:
                pass
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
            "win_fractions": win_fractions,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def run_decision_tool(
    cluster_id: str,
    llm_explanation: bool = True,
    explanation_style: str = "executive",
    no_fallback: bool = False,
    config_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for decision pipeline (cli/decision.py).
    
    Args:
        cluster_id: Cluster identifier
        llm_explanation: Use LLM explanation (default: True, falls back to template if unavailable)
        explanation_style: Explanation style (executive, technical, detailed)
        no_fallback: Fail if LLM unavailable (default: False, allows template fallback)
        config_path: Path to decision config JSON (optional)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    cmd = [
        sys.executable,
        "-m",
        "branitz_heat_decision.cli.decision",
        "--cluster-id", cluster_id,
        "--explanation-style", explanation_style,
    ]
    
    if llm_explanation:
        cmd.append("--llm-explanation")
    if no_fallback:
        cmd.append("--no-fallback")
    if config_path:
        cmd.extend(["--config", config_path])
    
    logger.info(f"[ADK Tool] Running decision pipeline: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        output_dir = resolve_cluster_path(cluster_id, "decision")
        outputs = {
            "contract": (output_dir / f"kpi_contract_{cluster_id}.json").exists(),
            "decision": (output_dir / f"decision_{cluster_id}.json").exists(),
            "explanation": (output_dir / f"explanation_{cluster_id}.md").exists(),
        }
        
        # Load decision result
        decision_result = None
        if outputs["decision"]:
            try:
                with open(output_dir / f"decision_{cluster_id}.json", "r") as f:
                    decision_result = json.load(f)
            except Exception:
                pass
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
            "decision": decision_result,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def run_uhdc_tool(
    cluster_id: str,
    out_dir: Optional[str] = None,
    llm: bool = True,
    style: str = "executive",
    format: str = "all",
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for UHDC report generation (cli/uhdc.py).
    
    Args:
        cluster_id: Cluster identifier
        out_dir: Output directory (default: results/uhdc/{cluster_id})
        llm: Use LLM explanation (default: True, falls back to template if unavailable)
        style: Explanation style (executive, technical, detailed)
        format: Output format (html, md, json, all)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    from branitz_heat_decision.config import resolve_cluster_path, RESULTS_ROOT
    
    if out_dir is None:
        out_dir = str(RESULTS_ROOT / "uhdc" / cluster_id)
    
    cmd = [
        sys.executable,
        "-m",
        "branitz_heat_decision.cli.uhdc",
        "--cluster-id", cluster_id,
        "--run-dir", str(RESULTS_ROOT),
        "--out-dir", out_dir,
        "--style", style,
        "--format", format,
    ]
    
    if llm:
        cmd.append("--llm")
    
    logger.info(f"[ADK Tool] Running UHDC report generation: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).parents[2])}
        )
        
        # Check outputs exist
        output_dir = Path(out_dir)
        outputs = {
            "html": (output_dir / f"uhdc_report_{cluster_id}.html").exists(),
            "markdown": (output_dir / f"uhdc_explanation_{cluster_id}.md").exists(),
            "json": (output_dir / f"uhdc_report_{cluster_id}.json").exists(),
        }
        
        return {
            "status": "success",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "outputs": outputs,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "stdout": e.stdout,
            "stderr": e.stderr,
            "returncode": e.returncode,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def get_available_tools() -> List[Dict[str, Any]]:
    """
    Get list of available ADK tools with descriptions.
    
    Returns:
        List of tool definitions (for agent tool registration)
    """
    return [
        {
            "name": "prepare_data",
            "description": "Run data preparation pipeline: load raw data, create clusters, generate profiles",
            "function": prepare_data_tool,
            "parameters": {
                "buildings_path": {"type": "string", "optional": True, "description": "Path to buildings GeoJSON"},
                "streets_path": {"type": "string", "optional": True, "description": "Path to streets GeoJSON"},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
        {
            "name": "run_cha",
            "description": "Run CHA pipeline: district heating network analysis",
            "function": run_cha_tool,
            "parameters": {
                "cluster_id": {"type": "string", "required": True, "description": "Cluster identifier"},
                "use_trunk_spur": {"type": "boolean", "optional": True, "default": True},
                "plant_wgs84_lat": {"type": "float", "optional": True, "description": "Fixed plant latitude (WGS84)"},
                "plant_wgs84_lon": {"type": "float", "optional": True, "description": "Fixed plant longitude (WGS84)"},
                "disable_auto_plant_siting": {"type": "boolean", "optional": True, "default": False},
                "optimize_convergence": {"type": "boolean", "optional": True, "default": True},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
        {
            "name": "run_dha",
            "description": "Run DHA pipeline: LV grid hosting analysis for heat pumps",
            "function": run_dha_tool,
            "parameters": {
                "cluster_id": {"type": "string", "required": True, "description": "Cluster identifier"},
                "cop": {"type": "float", "optional": True, "default": 2.8, "description": "Heat pump COP"},
                "base_load_source": {"type": "string", "optional": True, "default": "scenario_json", "choices": ["scenario_json", "bdew_timeseries"]},
                "bdew_population_json": {"type": "string", "optional": True, "description": "Path to BDEW population JSON (required for bdew_timeseries)"},
                "hp_three_phase": {"type": "boolean", "optional": True, "default": True},
                "topn": {"type": "integer", "optional": True, "default": 10},
                "grid_source": {"type": "string", "optional": True, "default": "legacy_json", "choices": ["legacy_json", "geodata"]},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
        {
            "name": "run_economics",
            "description": "Run economics pipeline: LCOH, CO₂, Monte Carlo analysis",
            "function": run_economics_tool,
            "parameters": {
                "cluster_id": {"type": "string", "required": True, "description": "Cluster identifier"},
                "n_samples": {"type": "integer", "optional": True, "default": 500, "description": "Monte Carlo samples"},
                "seed": {"type": "integer", "optional": True, "default": 42, "description": "Random seed"},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
        {
            "name": "run_decision",
            "description": "Run decision pipeline: build KPI contract, apply rules, generate recommendation",
            "function": run_decision_tool,
            "parameters": {
                "cluster_id": {"type": "string", "required": True, "description": "Cluster identifier"},
                "llm_explanation": {"type": "boolean", "optional": True, "default": True, "description": "Use LLM explanation (default: True, falls back to template if unavailable)"},
                "explanation_style": {"type": "string", "optional": True, "default": "executive", "choices": ["executive", "technical", "detailed"]},
                "no_fallback": {"type": "boolean", "optional": True, "default": False, "description": "Fail if LLM unavailable"},
                "config_path": {"type": "string", "optional": True, "description": "Path to decision config JSON"},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
        {
            "name": "run_uhdc",
            "description": "Generate UHDC report: comprehensive HTML/Markdown/JSON report from decision artifacts",
            "function": run_uhdc_tool,
            "parameters": {
                "cluster_id": {"type": "string", "required": True, "description": "Cluster identifier"},
                "out_dir": {"type": "string", "optional": True, "description": "Output directory"},
                "llm": {"type": "boolean", "optional": True, "default": True, "description": "Use LLM explanation (default: True, falls back to template if unavailable)"},
                "style": {"type": "string", "optional": True, "default": "executive", "choices": ["executive", "technical", "detailed"]},
                "format": {"type": "string", "optional": True, "default": "all", "choices": ["html", "md", "json", "all"]},
                "verbose": {"type": "boolean", "optional": True, "default": False},
            },
        },
    ]
