import pandas as pd
import geopandas as gpd
import json
import logging
import threading
import subprocess
import shlex
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
import os
import sys
import streamlit as st

# Ensure src is in path for imports to work if running as script
sys.path.append(str(Path(__file__).parents[3]))

from branitz_heat_decision.config import (
    DATA_PROCESSED, 
    BUILDING_CLUSTER_MAP_PATH, 
    DESIGN_TOPN_PATH,
    HOURLY_PROFILES_PATH
)
from branitz_heat_decision.ui.registry import SCENARIO_REGISTRY


logger = logging.getLogger(__name__)

CLUSTER_INDEX_PATH = DATA_PROCESSED / "cluster_ui_index.parquet"
STREET_CLUSTERS_PATH = DATA_PROCESSED / "street_clusters.parquet"
BUILDINGS_PATH_PROCESSED = DATA_PROCESSED / "buildings.parquet"
RESULTS_DIR = Path("results")

# --- Cached Data Loaders ---

@st.cache_data(show_spinner=False)
def _load_cluster_index() -> pd.DataFrame:
    if not CLUSTER_INDEX_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(CLUSTER_INDEX_PATH)

@st.cache_data(show_spinner=False)
def _load_street_clusters() -> gpd.GeoDataFrame:
    if not STREET_CLUSTERS_PATH.exists():
        return gpd.GeoDataFrame()
    return gpd.read_parquet(STREET_CLUSTERS_PATH)

@st.cache_data(show_spinner=False)
def _load_building_map() -> pd.DataFrame:
    if not BUILDING_CLUSTER_MAP_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)

@st.cache_data(show_spinner=False)
def _load_buildings_processed() -> gpd.GeoDataFrame:
    if not BUILDINGS_PATH_PROCESSED.exists():
        return gpd.GeoDataFrame()
    return gpd.read_parquet(BUILDINGS_PATH_PROCESSED)

@st.cache_data(show_spinner=False)
def _load_hourly_profiles() -> pd.DataFrame:
    if not HOURLY_PROFILES_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(HOURLY_PROFILES_PATH)

@st.cache_data(show_spinner=False)
def _load_design_topn() -> Dict:
    if not DESIGN_TOPN_PATH.exists():
        return {}
    try:
        with open(DESIGN_TOPN_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to cache design topn: {e}")
        return {}


class ClusterService:
    """Service for loading cluster data."""
    
    def __init__(self):
        # No manual cache needed, relying on st.cache_data
        pass

    def get_cluster_index(self) -> pd.DataFrame:
        """Load the lightweight cluster index."""
        return _load_cluster_index()

    def get_cluster_summary(self, cluster_id: str) -> Dict[str, Any]:
        """Get summary details for a specific cluster."""
        idx = self.get_cluster_index()
        if idx.empty:
            return {}
            
        row = idx[idx["cluster_id"] == cluster_id]
        if row.empty:
            return {}
            
        return row.iloc[0].to_dict()

    def get_cluster_geometry(self, cluster_id: str) -> Optional[gpd.GeoSeries]:
        """Get the geometry (street polygon) for a cluster."""
        gdf = _load_street_clusters()
        if gdf.empty:
            return None
        
        row = gdf[gdf["cluster_id"] == cluster_id]
        if row.empty:
            return None
        return row.geometry.iloc[0]

    def get_buildings_for_cluster(self, cluster_id: str) -> gpd.GeoDataFrame:
        """Get all buildings belonging to a cluster."""
        b_map = _load_building_map()
        if b_map.empty:
            return gpd.GeoDataFrame()
            
        b_ids = b_map[b_map["cluster_id"] == cluster_id]["building_id"]
        
        if b_ids.empty:
            return gpd.GeoDataFrame()
            
        # Extract from cached big dataframe
        buildings = _load_buildings_processed()
        if buildings.empty:
            return gpd.GeoDataFrame()
            
        return buildings[buildings["building_id"].isin(b_ids)]

    def get_hourly_load(self, cluster_id: str) -> Optional[pd.Series]:
        """Get aggregated hourly load profile for the cluster."""
        profiles = _load_hourly_profiles()
        if profiles.empty:
             return None
        
        # Identify buildings in cluster
        b_map = _load_building_map()
            
        if not b_map.empty:
             b_ids = b_map[b_map["cluster_id"] == cluster_id]["building_id"]
             # Filter columns that exist in profiles
             valid_cols = [b for b in b_ids if b in profiles.columns]
             
             if not valid_cols:
                 return None
                 
             # Aggregate
             cluster_profile = profiles[valid_cols].sum(axis=1)
             return cluster_profile
             
        return None

    def get_design_topn(self, cluster_id: str) -> Dict[str, Any]:
        """Get design and top-N load metrics for the cluster."""
        data = _load_design_topn()
        clusters = data.get("clusters", {})
        return clusters.get(cluster_id, {})

    def check_data_readiness(self, cluster_id: str) -> Dict[str, Any]:
        """
        Check if data exists to run simulations for this cluster.
        Returns: {'ready': bool, 'issues': List[str], 'stats': Dict}
        """
        issues = []
        stats = {}
        
        # 1. Check Index/Street Clusters
        idx = self.get_cluster_index()
        if idx.empty or cluster_id not in idx["cluster_id"].values:
            return {"ready": False, "issues": ["Cluster ID not found in index"], "stats": {}}
            
        # 2. Check Buildings
        buildings = self.get_buildings_for_cluster(cluster_id)
        if buildings.empty:
            issues.append("No buildings mapped to this cluster")
        else:
            stats["building_count"] = len(buildings)
            # Check demand
            if "annual_heat_demand_kwh_a" in buildings.columns:
                 with_demand = buildings[buildings["annual_heat_demand_kwh_a"] > 0]
                 stats["buildings_with_demand"] = len(with_demand)
                 if len(with_demand) == 0:
                     issues.append("Zero buildings with heat demand > 0")
            else:
                 issues.append("Missing heat demand column in building data")

        # 3. Check Profiles
        profiles = _load_hourly_profiles()
        if profiles.empty:
            issues.append("Hourly profiles parquet missing")
        elif not buildings.empty:
             # Check coverage
             b_ids = buildings["building_id"].astype(str).tolist()
             available_profs = [b for b in b_ids if b in profiles.columns]
             stats["profiles_available"] = len(available_profs)
             if len(available_profs) == 0:
                 issues.append("No hourly profiles found for these buildings")
             elif len(available_profs) < len(b_ids):
                 # Not a blocker, but a warning
                 stats["fraction_with_profile"] = len(available_profs) / len(b_ids)
        
        # 4. Check Design Data
        design = self.get_design_topn(cluster_id)
        if not design:
             issues.append("Design TopN data missing (cluster_design_topn.json)")
        else:
             stats["design_load_kw"] = design.get("design_load_kw", 0)

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "stats": stats
        }


class JobService:
    """Service for managing background simulation jobs."""
    
    def __init__(self):
        self.jobs = {}  # In-memory job store (job_id -> info)
        self.lock = threading.Lock()
        
    def start_job(self, scenario: str, cluster_id: str, **kwargs) -> str:
        """Start a simulation job in the background, with dependency resolution."""
        job_id = f"{scenario}_{cluster_id}_{int(time.time())}"
        
        # 1. Check & Queue Dependencies
        wait_list = []
        if scenario in SCENARIO_REGISTRY:
            deps = SCENARIO_REGISTRY[scenario].get("dependencies", [])
            if deps:
                # Need ResultService to check valid results
                rs = ResultService() 
                status = rs.get_result_status(cluster_id)
                
                for dep in deps:
                    # If result exists, we don't need to re-run
                    if status.get(dep):
                        continue
                        
                    # Check if already running
                    existing = self.get_latest_job_for_cluster(cluster_id)
                    dep_running_id = None
                    if existing and existing.get("scenario") == dep and existing.get("status") == "running":
                        dep_running_id = existing["id"]
                    
                    if dep_running_id:
                        wait_list.append(dep_running_id)
                    else:
                        # Auto-start missing dependency
                        logger.info(f"Auto-starting dependency {dep} for {job_id}")
                        new_dep_id = self.start_job(dep, cluster_id)
                        wait_list.append(new_dep_id)

        cmd = self._build_command(scenario, cluster_id, **kwargs)
        
        log_dir = RESULTS_DIR / "jobs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{job_id}.log"
        
        # Pass wait_list to process
        thread = threading.Thread(target=self._run_process, args=(job_id, cmd, log_file, scenario, cluster_id, wait_list))
        thread.start()

        with self.lock:
            self.jobs[job_id] = {
                "id": job_id,
                "cluster_id": cluster_id,
                "scenario": scenario,
                "status": "running",
                "start_time": datetime.now(),
                "log_file": str(log_file),
                "cmd": cmd,
                "waiting_for": wait_list
            }
            
        return job_id

    def _build_command(self, scenario: str, cluster_id: str, **kwargs) -> List[str]:
        # Ensure we use the current python environment
        python_exe = sys.executable
        
        if scenario not in SCENARIO_REGISTRY:
             raise ValueError(f"Unknown scenario: {scenario}")
             
        spec = SCENARIO_REGISTRY[scenario]
        template = spec["command_template"]
        kwargs_map = spec.get("kwargs_map", {})
        
        # Resolve placeholders
        cmd = [part.format(python=python_exe, cluster_id=cluster_id) for part in template]
        
        # Append kwargs flags
        for key, flag in kwargs_map.items():
             if kwargs.get(key):
                 cmd.append(flag)
                 
        return cmd

    def _run_process(self, job_id: str, cmd: List[str], log_file: Path, scenario: str, cluster_id: str, wait_list: List[str] = None):
        try:
            with open(log_file, "w") as f:
                # 0. Wait for dependencies
                if wait_list:
                    f.write(f"Waiting for dependencies: {wait_list}\n")
                    f.flush()
                    while True:
                        all_done = True
                        failed = False
                        for dep_id in wait_list:
                            dep_stat = self.get_job_status(dep_id)
                            # If job not found, assume finished/expired?? Safe to assume active tracking.
                            if not dep_stat: continue 
                            
                            status = dep_stat.get("status", "unknown")
                            if status in ["failed", "error"]:
                                failed = True
                                f.write(f"Dependency {dep_id} failed. Aborting.\n")
                                break
                            if status != "completed":
                                all_done = False
                        
                        if failed:
                            raise Exception("Dependencies failed")
                        
                        if all_done:
                            f.write("All dependencies completed. Starting main process.\n")
                            f.flush()
                            break
                        
                        time.sleep(2)

                # Need to set PYTHONPATH to src so scripts can import modules
                env = os.environ.copy()
                src_path = str(Path(__file__).parents[2]) # src/branitz.../ui/ -> src
                env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
                
                subprocess.run(
                    cmd, 
                    stdout=f, 
                    stderr=subprocess.STDOUT, 
                    check=True,
                    cwd=os.getcwd(), # Assume running from root
                    env=env
                )
            
            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "completed"
                    self.jobs[job_id]["end_time"] = datetime.now()
                    
        except Exception as e:
            # Capture error details
            error_type = type(e).__name__
            error_msg = str(e)
            suggestion = "Check logs for details."
            
            if isinstance(e, subprocess.CalledProcessError):
                suggestion = "The simulation script failed. Use the logs to identify the exact step (e.g., Network Build, Solver)."
                # Could parse tail of log file here for hints
            
            # Write structured error.json to results dir
            try:
                # Assume standard results path structure based on registry (kinda)
                # results/{scenario}/{cluster_id}/
                out_dir = RESULTS_DIR / scenario / cluster_id
                out_dir.mkdir(parents=True, exist_ok=True)
                
                err_data = {
                    "job_id": job_id,
                    "timestamp": datetime.now().isoformat(),
                    "error_type": error_type,
                    "message": error_msg,
                    "suggested_fix": suggestion,
                    "log_path": str(log_file)
                }
                with open(out_dir / "error.json", "w") as ef:
                    json.dump(err_data, ef, indent=2)
            except Exception as write_err:
                logger.error(f"Failed to write error.json: {write_err}")

            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "failed" if isinstance(e, subprocess.CalledProcessError) else "error"
                    self.jobs[job_id]["error"] = error_msg
                    self.jobs[job_id]["end_time"] = datetime.now()

    def get_job_error_details(self, job_id: str) -> Optional[Dict]:
        """Read structured error info if available."""
        job = self.get_job_status(job_id)
        if not job or job["status"] not in ["failed", "error"]:
            return None
            
        scenario = job.get("scenario")
        cid = job.get("cluster_id")
        if scenario and cid:
            err_path = RESULTS_DIR / scenario / cid / "error.json"
            if err_path.exists():
                try:
                    return json.load(open(err_path))
                except:
                    pass
        return None


    def get_job_status(self, job_id: str) -> Dict:
        with self.lock:
            return self.jobs.get(job_id, {}).copy()
    
    def get_latest_job_for_cluster(self, cluster_id: str) -> Optional[Dict]:
        """Get most recent job for a cluster."""
        with self.lock:
            relevant = [j for j in self.jobs.values() if j["cluster_id"] == cluster_id]
            if not relevant:
                return None
            return sorted(relevant, key=lambda x: x["start_time"], reverse=True)[0]


class ResultService:
    """Service for checking/loading results."""
    
    def get_result_status(self, cluster_id: str) -> Dict[str, bool]:
        """Check which results exist based on registry."""
        status = {}
        for scenario, spec in SCENARIO_REGISTRY.items():
             # Consider done if ALL outputs exist? Or at least one?
             # Let's say at least the first one (primary result)
             if not spec["outputs"]:
                 status[scenario] = False
                 continue
                 
             primary_out = spec["outputs"][0].format(cluster_id=cluster_id)
             status[scenario] = Path(primary_out).exists()
        return status

    def get_existing_artifacts(self, cluster_id: str, scenario: str) -> List[Path]:
        """Get list of existing artifact paths for a scenario."""
        if scenario not in SCENARIO_REGISTRY:
            return []
            
        spec = SCENARIO_REGISTRY[scenario]
        existing = []
        for out_pattern in spec["outputs"]:
            path = Path(out_pattern.format(cluster_id=cluster_id))
            if path.exists():
                existing.append(path)
        return existing

    def get_report_path(self, cluster_id: str) -> Optional[Path]:
        path = RESULTS_DIR / "uhdc" / cluster_id / f"uhdc_report_{cluster_id}.html"
        return path if path.exists() else None
    
    def get_cha_map_path(self, cluster_id: str, map_type="velocity") -> Optional[Path]:
        # Maps are saved directly in CHA cluster directory
        if map_type == "velocity":
            path = RESULTS_DIR / "cha" / cluster_id / "interactive_map.html"
        elif map_type == "temperature":
            path = RESULTS_DIR / "cha" / cluster_id / "interactive_map_temperature.html"
        elif map_type == "pressure":
            path = RESULTS_DIR / "cha" / cluster_id / "interactive_map_pressure.html"
        else:
            path = RESULTS_DIR / "cha" / cluster_id / f"interactive_map_{map_type}.html"
        return path if path.exists() else None
    
    def get_decision_explanation_path(self, cluster_id: str, format="md") -> Optional[Path]:
        """Get path to decision explanation file (MD or HTML)."""
        if format == "html":
            path = RESULTS_DIR / "decision" / cluster_id / f"explanation_{cluster_id}.html"
        else:
            path = RESULTS_DIR / "decision" / cluster_id / f"explanation_{cluster_id}.md"
        return path if path.exists() else None
