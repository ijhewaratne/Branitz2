"""
ADK Agent Module

Root ADK agent/team definition for Branitz Heat Decision pipeline orchestration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .tools import (
    prepare_data_tool,
    run_cha_tool,
    run_dha_tool,
    run_economics_tool,
    run_decision_tool,
    run_uhdc_tool,
    get_available_tools,
)
from .policies import validate_agent_action, enforce_guardrails, PolicyViolation

logger = logging.getLogger(__name__)


@dataclass
class AgentAction:
    """Represents an agent action with its result."""
    
    name: str
    phase: str
    parameters: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    status: str = "pending"  # pending, success, error
    error: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class AgentTrajectory:
    """Represents an agent's execution trajectory."""
    
    cluster_id: str
    actions: List[AgentAction] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed


class BaseADKAgent:
    """
    Base ADK agent providing shared functionality for policy enforcement and tool execution.
    """
    
    def __init__(
        self,
        cluster_id: Optional[str] = None,
        enforce_policies: bool = True,
        verbose: bool = False,
    ):
        """
        Initialize Base ADK agent.
        
        Args:
            cluster_id: Cluster identifier (optional for some agents like DataPrep)
            enforce_policies: Whether to enforce guardrails/policies (default: True)
            verbose: Enable verbose logging
        """
        self.cluster_id = cluster_id
        self.enforce_policies = enforce_policies
        self.verbose = verbose
        # If cluster_id is None, we can still have a trajectory, but it might be less meaningful
        self.trajectory = AgentTrajectory(cluster_id=cluster_id or "global")
        
        # Available tools (wrapped from existing modules)
        self.tools = {
            tool["name"]: tool["function"]
            for tool in get_available_tools()
        }
        
        if verbose:
            logging.getLogger(__name__).setLevel(logging.DEBUG)

    def _execute_tool(
        self,
        tool_name: str,
        phase: str,
        **kwargs,
    ) -> AgentAction:
        """
        Execute a tool with policy validation.
        
        Args:
            tool_name: Tool name (e.g., "run_cha")
            phase: Phase name (e.g., "cha")
            **kwargs: Tool parameters
        
        Returns:
            AgentAction with result
        """
        from datetime import datetime
        
        # Validate action against policies
        if self.enforce_policies:
            context = {
                "cluster_id": self.cluster_id,
                "parameters": kwargs,
            }
            try:
                enforce_guardrails(tool_name, context)
            except PolicyViolation as e:
                logger.error(f"[ADK Agent] Policy violation: {e}")
                return AgentAction(
                    name=tool_name,
                    phase=phase,
                    parameters=kwargs,
                    status="error",
                    error=str(e),
                    timestamp=datetime.now().isoformat(),
                )
        
        # Execute tool
        if tool_name not in self.tools:
            return AgentAction(
                name=tool_name,
                phase=phase,
                parameters=kwargs,
                status="error",
                error=f"Tool '{tool_name}' not found",
                timestamp=datetime.now().isoformat(),
            )
        
        tool_func = self.tools[tool_name]
        logger.info(f"[ADK Agent] Executing tool: {tool_name}" + (f" for cluster {self.cluster_id}" if self.cluster_id else ""))
        
        try:
            result = tool_func(**kwargs)
            
            # Determine status from result
            status = result.get("status", "error")
            error = result.get("error") if status == "error" else None
            
            action = AgentAction(
                name=tool_name,
                phase=phase,
                parameters=kwargs,
                result=result,
                status=status,
                error=error,
                timestamp=datetime.now().isoformat(),
            )
            
            logger.info(f"[ADK Agent] Tool '{tool_name}' completed with status: {status}")
            return action
        
        except Exception as e:
            logger.error(f"[ADK Agent] Tool '{tool_name}' failed: {e}")
            return AgentAction(
                name=tool_name,
                phase=phase,
                parameters=kwargs,
                status="error",
                error=str(e),
                timestamp=datetime.now().isoformat(),
            )


class DataPrepAgent(BaseADKAgent):
    """
    Agent responsible for data preparation (Phase 0).
    Wraps src/scripts/00_prepare_data.py.
    """
    
    def run(
        self,
        buildings_path: Optional[str] = None,
        streets_path: Optional[str] = None,
    ) -> AgentAction:
        """
        Execute data preparation.
        
        Args:
            buildings_path: Path to buildings GeoJSON (optional)
            streets_path: Path to streets GeoJSON (optional)
        """
        action = self._execute_tool(
            "prepare_data",
            phase="data",
            buildings_path=buildings_path,
            streets_path=streets_path,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class CHAAgent(BaseADKAgent):
    """
    Agent responsible for Cluster Heat Assessment (Phase 1).
    Wraps src/scripts/01_run_cha.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        use_trunk_spur: bool = True,
        plant_wgs84_lat: Optional[float] = 51.76274,
        plant_wgs84_lon: Optional[float] = 14.3453979,
        disable_auto_plant_siting: bool = True,
        optimize_convergence: bool = True,
    ) -> AgentAction:
        """
        Execute CHA pipeline.
        
        Args:
            use_trunk_spur: Use trunk-spur network builder (default: True)
            plant_wgs84_lat: Fixed plant latitude (WGS84, default: Cottbus CHP)
            plant_wgs84_lon: Fixed plant longitude (WGS84, default: Cottbus CHP)
            disable_auto_plant_siting: Disable automatic re-siting (default: True)
            optimize_convergence: Enable convergence optimization
        """
        action = self._execute_tool(
            "run_cha",
            phase="cha",
            cluster_id=self.cluster_id,
            use_trunk_spur=use_trunk_spur,
            plant_wgs84_lat=plant_wgs84_lat,
            plant_wgs84_lon=plant_wgs84_lon,
            disable_auto_plant_siting=disable_auto_plant_siting,
            optimize_convergence=optimize_convergence,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class DHAAgent(BaseADKAgent):
    """
    Agent responsible for District Heat Assessment (Phase 2).
    Wraps src/scripts/02_run_dha.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        cop: float = 2.8,
        base_load_source: str = "scenario_json",
        bdew_population_json: Optional[str] = None,
        hp_three_phase: bool = True,
        topn: int = 10,
        grid_source: str = "legacy_json",
    ) -> AgentAction:
        """
        Execute DHA pipeline.
        
        Args:
            cop: Heat pump COP (default: 2.8)
            base_load_source: Base load source (scenario_json or bdew_timeseries)
            bdew_population_json: Path to BDEW population JSON
            hp_three_phase: Model HP loads as balanced 3-phase
            topn: Number of top hours to include
            grid_source: Grid source (legacy_json or geodata)
        """
        action = self._execute_tool(
            "run_dha",
            phase="dha",
            cluster_id=self.cluster_id,
            cop=cop,
            base_load_source=base_load_source,
            bdew_population_json=bdew_population_json,
            hp_three_phase=hp_three_phase,
            topn=topn,
            grid_source=grid_source,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class EconomicsAgent(BaseADKAgent):
    """
    Agent responsible for Economics (Phase 3).
    Wraps src/scripts/03_run_economics.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        n_samples: int = 500,
        seed: int = 42,
    ) -> AgentAction:
        """
        Execute economics pipeline.
        
        Args:
            n_samples: Monte Carlo samples
            seed: Random seed
        """
        action = self._execute_tool(
            "run_economics",
            phase="economics",
            cluster_id=self.cluster_id,
            n_samples=n_samples,
            seed=seed,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class DecisionAgent(BaseADKAgent):
    """
    Agent responsible for Decision Making (Phase 4).
    Wraps cli/decision.py (deterministic rules engine).
    """

    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)
    
    def run(
        self,
        llm_explanation: bool = True,
        explanation_style: str = "executive",
        no_fallback: bool = False,
        config_path: Optional[str] = None,
    ) -> AgentAction:
        """
        Execute decision pipeline.
        
        Args:
            llm_explanation: Use LLM explanation (default: True, falls back to template if unavailable)
            explanation_style: Explanation style (executive, technical, detailed)
            no_fallback: Fail if LLM unavailable (default: False, allows template fallback)
            config_path: Path to decision config JSON
        """
        action = self._execute_tool(
            "run_decision",
            phase="decision",
            cluster_id=self.cluster_id,
            llm_explanation=llm_explanation,
            explanation_style=explanation_style,
            no_fallback=no_fallback,
            config_path=config_path,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class UHDCAgent(BaseADKAgent):
    """
    Agent responsible for UHDC Reporting (Phase 5).
    Wraps cli/uhdc.py.
    """

    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        out_dir: Optional[str] = None,
        llm: bool = True,
        style: str = "executive",
        format: str = "all",
    ) -> AgentAction:
        """
        Execute UHDC report generation.
        
        Args:
            out_dir: Output directory
            llm: Use LLM explanation (default: True, falls back to template if unavailable)
            style: Explanation style
            format: Output format
        """
        action = self._execute_tool(
            "run_uhdc",
            phase="uhdc",
            cluster_id=self.cluster_id,
            out_dir=out_dir,
            llm=llm,
            style=style,
            format=format,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action


class BranitzADKAgent(BaseADKAgent):
    """
    Root ADK agent for Branitz Heat Decision pipeline orchestration.
    
    This agent orchestrates the complete pipeline without modifying existing modules.
    It can now delegate to specialized agents or use the base tool execution logic.
    For backward compatibility and simplicity, it retains the direct tool execution logic
    inherited from BaseADKAgent helper.
    """
    
    def __init__(
        self,
        cluster_id: str,
        enforce_policies: bool = True,
        verbose: bool = False,
    ):
        super().__init__(cluster_id=cluster_id, enforce_policies=enforce_policies, verbose=verbose)
    
    def prepare_data(
        self,
        buildings_path: Optional[str] = None,
        streets_path: Optional[str] = None,
    ) -> AgentAction:
        agent = DataPrepAgent(enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(buildings_path=buildings_path, streets_path=streets_path)
        self.trajectory.actions.append(action)
        return action
    
    def run_cha(
        self,
        use_trunk_spur: bool = True,
        plant_wgs84_lat: Optional[float] = 51.76274,
        plant_wgs84_lon: Optional[float] = 14.3453979,
        disable_auto_plant_siting: bool = True,
        optimize_convergence: bool = True,
    ) -> AgentAction:
        agent = CHAAgent(cluster_id=self.cluster_id, enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(
            use_trunk_spur=use_trunk_spur,
            plant_wgs84_lat=plant_wgs84_lat,
            plant_wgs84_lon=plant_wgs84_lon,
            disable_auto_plant_siting=disable_auto_plant_siting,
            optimize_convergence=optimize_convergence
        )
        self.trajectory.actions.append(action)
        return action
    
    def run_dha(
        self,
        cop: float = 2.8,
        base_load_source: str = "scenario_json",
        bdew_population_json: Optional[str] = None,
        hp_three_phase: bool = True,
        topn: int = 10,
        grid_source: str = "legacy_json",
    ) -> AgentAction:
        agent = DHAAgent(cluster_id=self.cluster_id, enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(
            cop=cop,
            base_load_source=base_load_source,
            bdew_population_json=bdew_population_json,
            hp_three_phase=hp_three_phase,
            topn=topn,
            grid_source=grid_source
        )
        self.trajectory.actions.append(action)
        return action
    
    def run_economics(
        self,
        n_samples: int = 500,
        seed: int = 42,
    ) -> AgentAction:
        agent = EconomicsAgent(cluster_id=self.cluster_id, enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(n_samples=n_samples, seed=seed)
        self.trajectory.actions.append(action)
        return action
    
    def run_decision(
        self,
        llm_explanation: bool = True,
        explanation_style: str = "executive",
        no_fallback: bool = False,
        config_path: Optional[str] = None,
    ) -> AgentAction:
        agent = DecisionAgent(cluster_id=self.cluster_id, enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(
            llm_explanation=llm_explanation,
            explanation_style=explanation_style,
            no_fallback=no_fallback,
            config_path=config_path
        )
        self.trajectory.actions.append(action)
        return action
    
    def run_uhdc(
        self,
        out_dir: Optional[str] = None,
        llm: bool = True,
        style: str = "executive",
        format: str = "all",
    ) -> AgentAction:
        agent = UHDCAgent(cluster_id=self.cluster_id, enforce_policies=self.enforce_policies, verbose=self.verbose)
        action = agent.run(out_dir=out_dir, llm=llm, style=style, format=format)
        self.trajectory.actions.append(action)
        return action
    
    def run_full_pipeline(
        self,
        skip_data_prep: bool = False,
        cha_params: Optional[Dict[str, Any]] = None,
        dha_params: Optional[Dict[str, Any]] = None,
        economics_params: Optional[Dict[str, Any]] = None,
        decision_params: Optional[Dict[str, Any]] = None,
        uhdc_params: Optional[Dict[str, Any]] = None,
    ) -> AgentTrajectory:
        """
        Run complete pipeline (all phases).
        
        Args:
            skip_data_prep: Skip data preparation if already done
            cha_params: CHA parameters (optional)
            dha_params: DHA parameters (optional)
            economics_params: Economics parameters (optional)
            decision_params: Decision parameters (optional)
            uhdc_params: UHDC parameters (optional)
        
        Returns:
            AgentTrajectory with all actions
        """
        from datetime import datetime
        
        self.trajectory.started_at = datetime.now().isoformat()
        self.trajectory.status = "running"
        
        logger.info(f"[ADK Agent] Starting full pipeline for cluster {self.cluster_id}")
        
        # Phase 0: Data Preparation
        if not skip_data_prep:
            logger.info("[ADK Agent] Phase 0: Data Preparation")
            # For full pipeline, allow empty args if None passed, DataPrepAgent handles defaults
            action = self.prepare_data()
            if action.status == "error":
                self.trajectory.status = "failed"
                self.trajectory.completed_at = datetime.now().isoformat()
                return self.trajectory
        
        # Phase 1: CHA
        logger.info("[ADK Agent] Phase 1: CHA Pipeline")
        cha_kwargs = cha_params or {}
        action = self.run_cha(**cha_kwargs)
        if action.status == "error":
            self.trajectory.status = "failed"
            self.trajectory.completed_at = datetime.now().isoformat()
            return self.trajectory
        
        # Phase 2: DHA
        logger.info("[ADK Agent] Phase 2: DHA Pipeline")
        dha_kwargs = dha_params or {}
        action = self.run_dha(**dha_kwargs)
        if action.status == "error":
            self.trajectory.status = "failed"
            self.trajectory.completed_at = datetime.now().isoformat()
            return self.trajectory
        
        # Phase 3: Economics
        logger.info("[ADK Agent] Phase 3: Economics Pipeline")
        economics_kwargs = economics_params or {}
        action = self.run_economics(**economics_kwargs)
        if action.status == "error":
            self.trajectory.status = "failed"
            self.trajectory.completed_at = datetime.now().isoformat()
            return self.trajectory
        
        # Phase 4: Decision
        logger.info("[ADK Agent] Phase 4: Decision Pipeline")
        decision_kwargs = decision_params or {}
        action = self.run_decision(**decision_kwargs)
        if action.status == "error":
            self.trajectory.status = "failed"
            self.trajectory.completed_at = datetime.now().isoformat()
            return self.trajectory
        
        # Phase 5: UHDC
        logger.info("[ADK Agent] Phase 5: UHDC Report Generation")
        uhdc_kwargs = uhdc_params or {}
        action = self.run_uhdc(**uhdc_kwargs)
        if action.status == "error":
            self.trajectory.status = "failed"
            self.trajectory.completed_at = datetime.now().isoformat()
            return self.trajectory
        
        self.trajectory.status = "completed"
        self.trajectory.completed_at = datetime.now().isoformat()
        
        logger.info(f"[ADK Agent] Full pipeline completed for cluster {self.cluster_id}")
        
        return self.trajectory


class BranitzADKTeam:
    """
    Multi-agent team for parallel cluster processing.
    
    This class orchestrates multiple ADK agents for batch processing.
    """
    
    def __init__(
        self,
        cluster_ids: List[str],
        enforce_policies: bool = True,
        verbose: bool = False,
    ):
        """
        Initialize ADK team.
        
        Args:
            cluster_ids: List of cluster identifiers
            enforce_policies: Whether to enforce guardrails/policies (default: True)
            verbose: Enable verbose logging
        """
        self.cluster_ids = cluster_ids
        self.enforce_policies = enforce_policies
        self.verbose = verbose
        self.agents = {
            cluster_id: BranitzADKAgent(
                cluster_id=cluster_id,
                enforce_policies=enforce_policies,
                verbose=verbose,
            )
            for cluster_id in cluster_ids
        }
    
    def run_batch(
        self,
        **pipeline_params,
    ) -> Dict[str, AgentTrajectory]:
        """
        Run pipeline for all clusters in batch.
        
        Args:
            **pipeline_params: Pipeline parameters (same as run_full_pipeline)
        
        Returns:
            Dict mapping cluster_id to AgentTrajectory
        """
        results = {}
        
        for cluster_id, agent in self.agents.items():
            logger.info(f"[ADK Team] Processing cluster {cluster_id}")
            trajectory = agent.run_full_pipeline(**pipeline_params)
            results[cluster_id] = trajectory
        
        return results
