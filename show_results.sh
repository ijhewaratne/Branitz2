#!/bin/bash
echo "=== CHA PIPELINE RESULTS ==="
echo ""
echo "To run the pipeline:"
echo "  conda activate branitz_env"
echo "  python src/scripts/01_run_cha.py --cluster-id ST001_TEST_CLUSTER --optimize-convergence"
echo ""
echo "=== EXISTING RESULTS ==="
if [ -d "results/cha/ST001_TEST_CLUSTER" ]; then
    echo "Results directory: results/cha/ST001_TEST_CLUSTER/"
    ls -lh results/cha/ST001_TEST_CLUSTER/ 2>/dev/null
    echo ""
    if [ -f "results/cha/ST001_TEST_CLUSTER/cha_kpis.json" ]; then
        echo "=== CONVERGENCE STATUS ==="
        python3 -c "
import json
try:
    with open('results/cha/ST001_TEST_CLUSTER/cha_kpis.json', 'r') as f:
        kpis = json.load(f)
        if 'convergence' in kpis:
            conv = kpis['convergence']
            print(f'Initial Converged: {conv.get(\"initial_converged\", \"N/A\")}')
            print(f'Final Converged: {conv.get(\"final_converged\", \"N/A\")}')
            print(f'Optimized: {conv.get(\"optimized\", \"N/A\")}')
        else:
            print('No convergence info in KPIs')
except Exception as e:
    print(f'Error reading KPIs: {e}')
" 2>/dev/null || echo "Could not read KPIs (pandas/json may not be available)"
    fi
else
    echo "No results directory found. Run the pipeline first."
fi
