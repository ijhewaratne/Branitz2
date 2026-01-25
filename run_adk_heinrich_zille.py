#!/usr/bin/env python3
"""
Run ADK pipeline for Heinrich Zille Strasse cluster.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from branitz_heat_decision.adk import BranitzADKAgent
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    # Cluster ID for Heinrich Zille Strasse
    cluster_id = "ST010_HEINRICH_ZILLE_STRASSE"
    
    logger.info(f"Starting ADK pipeline for cluster: {cluster_id}")
    
    # Create agent
    agent = BranitzADKAgent(
        cluster_id=cluster_id,
        enforce_policies=True,
        verbose=True,
    )
    
    # Run full pipeline
    trajectory = agent.run_full_pipeline(
        skip_data_prep=True,  # Set to False if data needs to be prepared
        cha_params={
            "use_trunk_spur": True,
            "plant_wgs84_lat": 51.76274,
            "plant_wgs84_lon": 14.3453979,
            "disable_auto_plant_siting": True,
            "optimize_convergence": True,
        },
        dha_params={
            "cop": 2.8,
            "base_load_source": "scenario_json",
            "hp_three_phase": True,
            "topn": 10,
        },
        economics_params={
            "n_samples": 500,
            "seed": 42,
        },
        decision_params={
            # llm_explanation defaults to True - will try LLM, fallback to template if unavailable
            "explanation_style": "executive",
        },
        uhdc_params={
            "format": "all",
            # llm defaults to True - will try LLM, fallback to template if unavailable
            "style": "executive",
        },
    )
    
    # Print summary
    print("\n" + "=" * 60)
    print("Pipeline Execution Summary")
    print("=" * 60)
    print(f"Cluster ID: {cluster_id}")
    print(f"Status: {trajectory.status}")
    print(f"Started: {trajectory.started_at}")
    print(f"Completed: {trajectory.completed_at}")
    print(f"Total Actions: {len(trajectory.actions)}")
    print("\nAction Details:")
    
    for i, action in enumerate(trajectory.actions, 1):
        print(f"\n{i}. {action.phase.upper()}: {action.name}")
        print(f"   Status: {action.status}")
        if action.error:
            print(f"   Error: {action.error}")
        if action.result:
            if action.result.get("stderr"):
                print(f"   Stderr: {action.result['stderr'][:500]}")
            if action.result.get("stdout"):
                print(f"   Stdout: {action.result['stdout'][:500]}")
        elif action.result and action.result.get("outputs"):
            outputs = action.result["outputs"]
            print(f"   Outputs: {sum(1 for v in outputs.values() if v)}/{len(outputs)} created")
            if action.phase == "cha" and action.result.get("convergence"):
                conv = action.result["convergence"]
                print(f"   Convergence: {conv}")
            elif action.phase == "dha" and action.result.get("violations"):
                viol = action.result["violations"]
                print(f"   Violations: {viol}")
            elif action.phase == "decision" and action.result.get("decision"):
                dec = action.result["decision"]
                print(f"   Decision: {dec.get('choice', 'N/A')}")
                print(f"   Reason Codes: {dec.get('reason_codes', [])}")
    
    print("\n" + "=" * 60)
    
    if trajectory.status == "completed":
        print("✓ Pipeline completed successfully!")
    elif trajectory.status == "failed":
        print("✗ Pipeline failed. Check errors above.")
    else:
        print(f"Pipeline status: {trajectory.status}")
    
    return trajectory

if __name__ == "__main__":
    main()
