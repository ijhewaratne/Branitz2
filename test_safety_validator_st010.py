#!/usr/bin/env python3
"""
Test script for safety_validator.py on ST010_HEINRICH_ZILLE_STRASSE
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from branitz_heat_decision.uhdc.safety_validator import LogicAuditor, generate_safe_explanation

def main():
    cluster_id = "ST010_HEINRICH_ZILLE_STRASSE"
    
    # Load KPI contract
    contract_path = Path(f"results/decision/{cluster_id}/kpi_contract_{cluster_id}.json")
    if not contract_path.exists():
        print(f"❌ KPI contract not found: {contract_path}")
        return
    
    with open(contract_path, 'r') as f:
        contract = json.load(f)
    
    # Load decision
    decision_path = Path(f"results/decision/{cluster_id}/decision_{cluster_id}.json")
    if not decision_path.exists():
        print(f"❌ Decision file not found: {decision_path}")
        return
    
    with open(decision_path, 'r') as f:
        decision = json.load(f)
    
    print(f"✅ Loaded data for {cluster_id}")
    print(f"   DH LCOH: {contract['district_heating']['lcoh']['median']:.2f} €/MWh")
    print(f"   HP LCOH: {contract['heat_pumps']['lcoh']['median']:.2f} €/MWh")
    print(f"   DH Feasible: {contract['district_heating']['feasible']}")
    print(f"   HP Feasible: {contract['heat_pumps']['feasible']}")
    print(f"   Decision: {decision['choice']}")
    print()
    
    # Test 1: Valid explanation
    print("=" * 70)
    print("TEST 1: Valid Explanation")
    print("=" * 70)
    valid_explanation = """
    District Heating is recommended for this cluster.
    Only district heating meets technical standards (HP has 116 grid violations).
    Economics clearly favor DH (LCOH difference: 32 €/MWh).
    DH LCOH is 92.6 EUR/MWh, while HP LCOH is 124.5 EUR/MWh.
    Velocity is within limits (v_share_within_limits = 1.0).
    """
    
    auditor = LogicAuditor(contract)
    is_valid, violations = auditor.validate_explanation(valid_explanation)
    
    print(f"Explanation:\n{valid_explanation}\n")
    print(f"✅ Valid: {is_valid}")
    print(f"Claims extracted: {len(auditor.extracted_claims)}")
    for i, claim in enumerate(auditor.extracted_claims, 1):
        print(f"  {i}. {claim.claim_type.value}: {claim.subject} = {claim.value}")
    if violations:
        print(f"⚠️  Violations: {violations}")
    print()
    
    # Test 2: Invalid explanation (hallucinated numbers)
    print("=" * 70)
    print("TEST 2: Invalid Explanation (Hallucinated Numbers)")
    print("=" * 70)
    invalid_explanation = """
    District Heating is recommended for this cluster.
    DH LCOH is 150.0 EUR/MWh, while HP LCOH is 80.0 EUR/MWh.
    HP is cheaper than DH.
    """
    
    auditor2 = LogicAuditor(contract)
    is_valid2, violations2 = auditor2.validate_explanation(invalid_explanation)
    
    print(f"Explanation:\n{invalid_explanation}\n")
    print(f"❌ Valid: {is_valid2}")
    print(f"Claims extracted: {len(auditor2.extracted_claims)}")
    for i, claim in enumerate(auditor2.extracted_claims, 1):
        print(f"  {i}. {claim.claim_type.value}: {claim.subject} = {claim.value}")
    if violations2:
        print(f"⚠️  Violations:")
        for v in violations2:
            print(f"     - {v}")
    print()
    
    # Test 3: Comparison validation
    print("=" * 70)
    print("TEST 3: Comparison Claim Validation")
    print("=" * 70)
    comparison_explanation = """
    District Heating is cheaper than Heat Pumps.
    DH LCOH is 92.6 EUR/MWh and HP LCOH is 124.5 EUR/MWh.
    """
    
    auditor3 = LogicAuditor(contract)
    is_valid3, violations3 = auditor3.validate_explanation(comparison_explanation)
    
    print(f"Explanation:\n{comparison_explanation}\n")
    print(f"✅ Valid: {is_valid3}")
    print(f"Claims extracted: {len(auditor3.extracted_claims)}")
    for i, claim in enumerate(auditor3.extracted_claims, 1):
        print(f"  {i}. {claim.claim_type.value}: {claim.subject} = {claim.value}")
    if violations3:
        print(f"⚠️  Violations: {violations3}")
    print()
    
    # Test 4: Threshold validation
    print("=" * 70)
    print("TEST 4: Threshold Claim Validation")
    print("=" * 70)
    threshold_explanation = """
    District Heating velocity is within limits.
    The maximum velocity is 0.95 m/s, which is below the 1.5 m/s threshold.
    """
    
    auditor4 = LogicAuditor(contract)
    is_valid4, violations4 = auditor4.validate_explanation(threshold_explanation)
    
    print(f"Explanation:\n{threshold_explanation}\n")
    print(f"✅ Valid: {is_valid4}")
    print(f"Claims extracted: {len(auditor4.extracted_claims)}")
    for i, claim in enumerate(auditor4.extracted_claims, 1):
        print(f"  {i}. {claim.claim_type.value}: {claim.subject} = {claim.value}")
    if violations4:
        print(f"⚠️  Violations: {violations4}")
    print()
    
    # Test 5: Categorical validation
    print("=" * 70)
    print("TEST 5: Categorical Claim Validation")
    print("=" * 70)
    categorical_explanation = """
    District Heating is feasible for this cluster.
    Heat Pumps are not feasible due to grid violations.
    """
    
    auditor5 = LogicAuditor(contract)
    is_valid5, violations5 = auditor5.validate_explanation(categorical_explanation)
    
    print(f"Explanation:\n{categorical_explanation}\n")
    print(f"✅ Valid: {is_valid5}")
    print(f"Claims extracted: {len(auditor5.extracted_claims)}")
    for i, claim in enumerate(auditor5.extracted_claims, 1):
        print(f"  {i}. {claim.claim_type.value}: {claim.subject} = {claim.value}")
    if violations5:
        print(f"⚠️  Violations: {violations5}")
    print()
    
    print("=" * 70)
    print("✅ All tests completed!")
    print("=" * 70)

if __name__ == "__main__":
    main()
