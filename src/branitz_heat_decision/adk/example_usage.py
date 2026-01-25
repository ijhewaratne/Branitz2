#!/usr/bin/env python3
"""
Example ADK Usage

Demonstrates how to use the ADK module for Branitz Heat Decision pipeline orchestration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parents[3]))

from branitz_heat_decision.adk import BranitzADKAgent, BranitzADKTeam
from branitz_heat_decision.adk.evals import validate_trajectory, validate_artifacts
from branitz_heat_decision.adk.policies import PolicyViolation


def example_single_cluster():
    """Example: Run pipeline for a single cluster."""
    print("=" * 60)
    print("Example 1: Single Cluster Pipeline")
    print("=" * 60)
    
    # Create agent
    agent = BranitzADKAgent(
        cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
        enforce_policies=True,
        verbose=True,
    )
    
    # Run full pipeline
    trajectory = agent.run_full_pipeline(
        skip_data_prep=False,  # Set to True if data already prepared
        cha_params={
            "use_trunk_spur": True,
            "plant_wgs84_lat": 51.76274,
            "plant_wgs84_lon": 14.3453979,
            "disable_auto_plant_siting": True,
        },
        dha_params={
            "cop": 2.8,
            "base_load_source": "scenario_json",
            "hp_three_phase": True,
        },
        economics_params={"n_samples": 500, "seed": 42},
        decision_params={"llm_explanation": False},
        uhdc_params={"format": "all", "llm": False},
    )
    
    # Print summary
    print(f"\nPipeline Status: {trajectory.status}")
    print(f"Started: {trajectory.started_at}")
    print(f"Completed: {trajectory.completed_at}")
    print(f"Actions: {len(trajectory.actions)}")
    
    for action in trajectory.actions:
        print(f"  {action.phase}: {action.name} - {action.status}")
        if action.error:
            print(f"    Error: {action.error}")


def example_individual_phases():
    """Example: Run phases individually."""
    print("\n" + "=" * 60)
    print("Example 2: Individual Phases")
    print("=" * 60)
    
    # Create agent
    agent = BranitzADKAgent(
        cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
        enforce_policies=True,
        verbose=True,
    )
    
    # Run phases individually
    print("\nPhase 0: Data Preparation")
    action = agent.prepare_data()
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    
    print("\nPhase 1: CHA Pipeline")
    action = agent.run_cha(
        use_trunk_spur=True,
        optimize_convergence=True,
    )
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    print(f"  Convergence: {action.result.get('convergence', 'N/A')}")
    
    print("\nPhase 2: DHA Pipeline")
    action = agent.run_dha(cop=2.8)
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    print(f"  Violations: {action.result.get('violations', 'N/A')}")
    
    print("\nPhase 3: Economics Pipeline")
    action = agent.run_economics(n_samples=500)
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    print(f"  Win Fractions: {action.result.get('win_fractions', 'N/A')}")
    
    print("\nPhase 4: Decision Pipeline")
    action = agent.run_decision(llm_explanation=False)
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    if action.result and "decision" in action.result:
        decision = action.result["decision"]
        print(f"  Choice: {decision.get('choice', 'N/A')}")
        print(f"  Reason Codes: {decision.get('reason_codes', [])}")
    
    print("\nPhase 5: UHDC Report Generation")
    action = agent.run_uhdc(format="all")
    if action.status == "error":
        print(f"  Error: {action.error}")
        return
    print(f"  Outputs: {action.result.get('outputs', {})}")


def example_trajectory_validation():
    """Example: Validate trajectory and artifacts."""
    print("\n" + "=" * 60)
    print("Example 3: Trajectory Validation")
    print("=" * 60)
    
    # Create agent
    agent = BranitzADKAgent(
        cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
        enforce_policies=True,
        verbose=False,
    )
    
    # Run pipeline
    trajectory = agent.run_full_pipeline(
        skip_data_prep=True,  # Assume data already prepared
        cha_params={"use_trunk_spur": True},
        dha_params={"cop": 2.8},
        economics_params={"n_samples": 500},
        decision_params={"llm_explanation": False},
        uhdc_params={"format": "html"},
    )
    
    # Convert trajectory to list for validation
    trajectory_list = [
        {
            "phase": action.phase,
            "status": action.status,
            "name": action.name,
            "error": action.error,
        }
        for action in trajectory.actions
    ]
    
    # Validate trajectory
    valid, issues = validate_trajectory(
        trajectory=trajectory_list,
        cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    )
    
    print(f"\nTrajectory Valid: {valid}")
    if not valid:
        print("Issues:")
        for issue in issues:
            print(f"  - {issue}")
    
    # Validate artifacts
    all_valid, issues_by_phase = validate_artifacts(
        cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    )
    
    print(f"\nArtifacts Valid: {all_valid}")
    if not all_valid:
        print("Issues by Phase:")
        for phase, issues in issues_by_phase.items():
            print(f"  {phase}:")
            for issue in issues:
                print(f"    - {issue}")


def example_batch_processing():
    """Example: Batch processing with team."""
    print("\n" + "=" * 60)
    print("Example 4: Batch Processing")
    print("=" * 60)
    
    # Create team
    team = BranitzADKTeam(
        cluster_ids=[
            "ST010_HEINRICH_ZILLE_STRASSE",
            "ST001_AN_DEN_WEINBERGEN",
            # Add more cluster IDs as needed
        ],
        enforce_policies=True,
        verbose=True,
    )
    
    # Run batch
    results = team.run_batch(
        skip_data_prep=True,  # Assume data already prepared
        cha_params={"use_trunk_spur": True},
        dha_params={"cop": 2.8},
        economics_params={"n_samples": 500},
        decision_params={"llm_explanation": False},
        uhdc_params={"format": "html"},
    )
    
    # Print summary
    print(f"\nBatch Processing Results:")
    for cluster_id, trajectory in results.items():
        print(f"  {cluster_id}: {trajectory.status}")
        print(f"    Actions: {len(trajectory.actions)}")
        print(f"    Completed: {trajectory.completed_at}")


def example_policy_enforcement():
    """Example: Policy enforcement."""
    print("\n" + "=" * 60)
    print("Example 5: Policy Enforcement")
    print("=" * 60)
    
    from branitz_heat_decision.adk.policies import validate_agent_action, PolicyViolation
    
    # Test policy enforcement
    print("\nTest 1: Valid action (run_decision)")
    allowed, reason = validate_agent_action(
        action="run_decision",
        context={"cluster_id": "ST010_HEINRICH_ZILLE_STRASSE"},
    )
    print(f"  Allowed: {allowed}")
    if reason:
        print(f"  Reason: {reason}")
    
    print("\nTest 2: Blocked action (modify_kpi_contract)")
    allowed, reason = validate_agent_action(
        action="modify_kpi_contract",
        context={"cluster_id": "ST010_HEINRICH_ZILLE_STRASSE"},
    )
    print(f"  Allowed: {allowed}")
    if reason:
        print(f"  Reason: {reason}")
    
    print("\nTest 3: Blocked action (delete_artifacts)")
    allowed, reason = validate_agent_action(
        action="delete_artifacts",
        context={"cluster_id": "ST010_HEINRICH_ZILLE_STRASSE"},
    )
    print(f"  Allowed: {allowed}")
    if reason:
        print(f"  Reason: {reason}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ADK Usage Examples")
    parser.add_argument(
        "--example",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="Example number (1-5)",
    )
    
    args = parser.parse_args()
    
    if args.example == 1:
        example_single_cluster()
    elif args.example == 2:
        example_individual_phases()
    elif args.example == 3:
        example_trajectory_validation()
    elif args.example == 4:
        example_batch_processing()
    elif args.example == 5:
        example_policy_enforcement()
    else:
        # Run all examples
        print("Running all examples...")
        print("(Note: Some examples may fail if data/pipeline not set up)")
        print()
        
        try:
            example_policy_enforcement()
        except Exception as e:
            print(f"Example 5 failed: {e}")
        
        print("\n" + "=" * 60)
        print("To run specific examples:")
        print("  python src/branitz_heat_decision/adk/example_usage.py --example 1")
        print("  python src/branitz_heat_decision/adk/example_usage.py --example 2")
        print("  python src/branitz_heat_decision/adk/example_usage.py --example 3")
        print("  python src/branitz_heat_decision/adk/example_usage.py --example 4")
        print("  python src/branitz_heat_decision/adk/example_usage.py --example 5")
        print("=" * 60)
