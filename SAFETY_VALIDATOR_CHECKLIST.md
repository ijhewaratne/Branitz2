# Safety Validator Implementation Checklist

## 1. File Structure
- [x] `src/branitz_heat_decision/uhdc/safety_validator.py` exists
- [ ] `src/branitz_heat_decision/uhdc/explainer.py` imports from safety_validator

**Status**: File exists but explainer.py does NOT import LogicAuditor yet. It has its own `_validate_explanation_safety` function.

## 2. LogicAuditor Class
- [x] ClaimType Enum: NUMERICAL, COMPARISON, THRESHOLD, CATEGORICAL
- [x] `parse_claims()` method: Extracts claims from explanation text using regex
- [x] `validate_claim()` method: Routes to specific validators by type
- [x] `validate_explanation()` method: Main entry point returning (bool, violations)

**Status**: ✅ All implemented correctly

## 3. Four Claim Validators
- [x] Numerical: Validates values within ±1% tolerance (e.g., "LCOH is 145.2" vs contract)
- [x] Comparison: Validates ordering claims (e.g., "DH cheaper than HP")
- [x] Threshold: Validates range claims (e.g., "velocity within limits" → checks v_share ≥ 0.95)
- [ ] Categorical: Validates status claims (e.g., "feasible" vs contract boolean) - **PARTIAL**: Only checks DH, not HP

**Status**: ✅ Mostly complete, but categorical validator needs HP feasibility check

## 4. Integration with Explainer
- [ ] Explainer calls LogicAuditor.validate_explanation() before returning
- [ ] Falls back to template if violations detected
- [ ] Logs violations for audit trail

**Status**: ❌ NOT INTEGRATED - explainer.py uses its own `_validate_explanation_safety` function instead

## 5. KPI Contract Mapping
- [x] Maps claim subjects to contract paths (e.g., "LCOH" → district_heating.lcoh.median)
- [x] Handles both DH and HP blocks
- [x] Validates hydraulic KPIs (velocity)
- [x] Validates electrical KPIs (loading %)

**Status**: ✅ Complete

## Summary
- **Implemented**: 8/10 items ✅
- **Missing**: 2/10 items ❌
  1. Integration with explainer.py
  2. HP feasibility check in categorical validator
