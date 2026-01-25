from pathlib import Path

# Paths are relative from the project root when running via subprocess
# or resolving artifact existence.

SCENARIO_REGISTRY = {
    "cha": {
        "title": "Check District Heating Feasibility",
        "description": "Runs a hydraulic simulation (CHA) to determine if a District Heating network is technically viable based on pressure, velocity, and temperature constraints.",
        "command_template": [
            "{python}", "src/scripts/01_run_cha.py", 
            "--cluster-id", "{cluster_id}",
            "--use-trunk-spur",  # Default: use trunk-spur builder (required for convergence)
            "--optimize-convergence"  # Default: optimize for numerical stability
        ],
        "kwargs_map": {
            # Additional kwargs can be added here, but trunk-spur is now always used
        },
        "outputs": [
            "results/cha/{cluster_id}/cha_kpis.json",
            "results/cha/{cluster_id}/interactive_map.html",
            "results/cha/{cluster_id}/network.pickle"
        ],
        "estimated_runtime": "medium"
    },
    "dha": {
        "title": "Check Heat Pump Grid Feasibility",
        "description": "Analyzes the Low Voltage (LV) grid hosting capacity to see if Heat Pumps can be installed without grid reinforcement violations.",
        "command_template": [
            "{python}", "src/scripts/02_run_dha.py", 
            "--cluster-id", "{cluster_id}"
        ],
        "kwargs_map": {},
        "outputs": [
            "results/dha/{cluster_id}/dha_kpis.json",
            "results/dha/{cluster_id}/hp_lv_map.html"
        ],
        "estimated_runtime": "medium"
    },
    "economics": {
        "title": "Estimate Costs & CO₂",
        "description": "Calculates Levelized Cost of Heat (LCoH) for both DH and HP scenarios, including Monte Carlo simulation and robustness validation (sensitivity analysis + stress testing).",
        "command_template": [
            "{python}", "src/scripts/03_run_economics.py", 
            "--cluster-id", "{cluster_id}",
            "--full-validation"  # Default: run all validation
        ],
        "kwargs_map": {
            "sensitivity": "--sensitivity",
            "stress_tests": "--stress-tests"
        },
        "outputs": [
            "results/economics/{cluster_id}/economics_deterministic.json",
            "results/economics/{cluster_id}/economics_monte_carlo.json",
            "results/economics/{cluster_id}/sensitivity_analysis.json",
            "results/economics/{cluster_id}/stress_tests.json"
        ],
        "estimated_runtime": "medium"
    },
    "decision": {
        "title": "Compare & Recommend",
        "description": "Evaluates technical and economic results to recommend the best heating solution (DH vs HP) based on robustness and cost.",
        "command_template": [
            "{python}", "-m", "branitz_heat_decision.cli.decision", 
            "--cluster-id", "{cluster_id}"
        ],
        "kwargs_map": {
            "llm_explanation": "--llm-explanation"
        },
        "outputs": [
            "results/decision/{cluster_id}/decision_{cluster_id}.json"
        ],
        "estimated_runtime": "fast"
    },
    "uhdc": {
        "title": "Generate Stakeholder Report",
        "description": "Compiles all findings into a comprehensive HTML report suitable for stakeholders.",
        "command_template": [
            "{python}", "-m", "branitz_heat_decision.cli.uhdc", 
            "--cluster-id", "{cluster_id}"
        ],
        "kwargs_map": {
            "llm": "--llm"
        },
        "outputs": [
            "results/uhdc/{cluster_id}/uhdc_report_{cluster_id}.html"
        ],
        "estimated_runtime": "medium"
    }
}
