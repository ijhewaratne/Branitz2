# Validation Output Format - Sentence-by-Sentence Results

This document explains what the validation output currently shows and how to access sentence-by-sentence details.

---

## Current Output Structure

### What's Currently in JSON Output (`to_dict()`)

The `ValidationReport.to_dict()` method currently returns:

```python
{
    "cluster_id": "ST010",
    "timestamp": "2026-01-19T12:00:00",
    "validation_status": "pass",  # or "warning" or "fail"
    "overall_confidence": 0.85,
    "statements_validated": 3,
    
    # Aggregated counts
    "verified_count": 2,
    "unverified_count": 1,
    "contradiction_count": 0,
    "verified_rate": 0.67,
    "unverified_rate": 0.33,
    "contradiction_rate": 0.0,
    
    # Only contradictions are detailed
    "contradictions": [],  # Empty if no contradictions
    
    # Warnings (truncated statements)
    "warnings": [],
    
    # Feedback iterations
    "feedback_iterations": 1,
    
    # KPI data used
    "evidence": {
        "kpis": {
            "lcoh_dh_median": "75.2",
            "lcoh_hp_median": "82.5"
        }
    }
}
```

**❌ Problem**: The current output does NOT show each sentence with its TRUE/FALSE/NEUTRAL status and evidence.

---

## What's Available in the Report Object (Not in JSON)

The `ValidationReport` object actually **DOES contain** sentence-by-sentence results in `entailment_results`, but it's not included in `to_dict()`:

```python
report = auditor.validate_rationale(kpis, rationale, cluster_id)

# This IS available in the object:
report.entailment_results  # List[LightweightResult]

# Each result contains:
for result in report.entailment_results:
    result.statement    # "The recommended choice is DH"
    result.label        # EntailmentLabel.ENTAILMENT (or NEUTRAL, CONTRADICTION)
    result.confidence   # 0.95
    result.reason       # "Recommended choice is DH (verified)"
    
    # Properties:
    result.is_valid         # True if ENTAILMENT
    result.is_contradiction # True if CONTRADICTION
    result.is_neutral       # True if NEUTRAL
```

**✅ The data is there**, but not serialized to JSON!

---

## Example: Accessing Sentence-by-Sentence Results

### Python Code

```python
from branitz_heat_decision.validation import LogicAuditor

auditor = LogicAuditor()

kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5,
    "choice": "DH",
    "dh_feasible": True,
    "hp_feasible": True
}

rationale = """
The recommended choice is District Heating (DH).
DH is cheaper with LCOH of 75.2 EUR/MWh.
This is a robust decision.
"""

# Validate
report = auditor.validate_rationale(kpis, rationale, "ST010")

# Access sentence-by-sentence results
print("=== SENTENCE-BY-SENTENCE RESULTS ===\n")
for i, result in enumerate(report.entailment_results, 1):
    # Determine status
    if result.is_valid:
        status = "✅ TRUE (ENTAILMENT)"
    elif result.is_contradiction:
        status = "❌ FALSE (CONTRADICTION)"
    else:
        status = "⚪ NEUTRAL (UNVERIFIED)"
    
    print(f"Sentence {i}:")
    print(f"  Statement: {result.statement}")
    print(f"  Status: {status}")
    print(f"  Confidence: {result.confidence:.2f}")
    print(f"  Evidence: {result.reason}")
    print()
```

### Output

```
=== SENTENCE-BY-SENTENCE RESULTS ===

Sentence 1:
  Statement: The recommended choice is District Heating (DH)
  Status: ✅ TRUE (ENTAILMENT)
  Confidence: 0.95
  Evidence: Recommended choice is DH (verified)

Sentence 2:
  Statement: DH is cheaper with LCOH of 75.2 EUR/MWh
  Status: ✅ TRUE (ENTAILMENT)
  Confidence: 0.90
  Evidence: DH LCOH (75.2) < HP LCOH (82.5), diff=7.3

Sentence 3:
  Statement: This is a robust decision
  Status: ⚪ NEUTRAL (UNVERIFIED)
  Confidence: 0.50
  Evidence: Could not verify against KPIs with rules
```

---

## Complete Example with All Details

```python
from branitz_heat_decision.validation import LogicAuditor

auditor = LogicAuditor()

kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5,
    "choice": "DH",
    "dh_feasible": True,
    "hp_feasible": True,
    "dh_wins_fraction": 0.78
}

rationale = """
The recommended choice is District Heating (DH).
DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh.
This is a robust decision with DH winning in 78% of scenarios.
"""

report = auditor.validate_rationale(kpis, rationale, "ST010")

# Print summary
print(f"Validation Status: {report.validation_status}")
print(f"Overall Confidence: {report.overall_confidence:.2f}")
print(f"Statements Validated: {report.statements_validated}")
print(f"Verified: {report.verified_count} ({report.verified_rate:.1%})")
print(f"Unverified: {report.unverified_count} ({report.unverified_rate:.1%})")
print(f"Contradictions: {report.contradiction_count} ({report.contradiction_rate:.1%})")
print()

# Print sentence-by-sentence details
print("=== DETAILED SENTENCE RESULTS ===\n")
for i, result in enumerate(report.entailment_results, 1):
    # Map label to status
    label_map = {
        "Entailment": "✅ TRUE (ENTAILMENT)",
        "Contradiction": "❌ FALSE (CONTRADICTION)",
        "Neutral": "⚪ NEUTRAL (UNVERIFIED)"
    }
    status = label_map.get(result.label.value, "❓ UNKNOWN")
    
    print(f"[{i}/{len(report.entailment_results)}] {status}")
    print(f"  Statement: \"{result.statement}\"")
    print(f"  Confidence: {result.confidence:.2f}")
    print(f"  Evidence: {result.reason}")
    print()
```

### Output

```
Validation Status: pass
Overall Confidence: 0.88
Statements Validated: 3
Verified: 3 (100.0%)
Unverified: 0 (0.0%)
Contradictions: 0 (0.0%)

=== DETAILED SENTENCE RESULTS ===

[1/3] ✅ TRUE (ENTAILMENT)
  Statement: "The recommended choice is District Heating (DH)"
  Confidence: 0.95
  Evidence: Recommended choice is DH (verified)

[2/3] ✅ TRUE (ENTAILMENT)
  Statement: "DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh"
  Confidence: 0.90
  Evidence: DH LCOH (75.2) < HP LCOH (82.5), diff=7.3

[3/3] ✅ TRUE (ENTAILMENT)
  Statement: "This is a robust decision with DH winning in 78% of scenarios"
  Confidence: 0.90
  Evidence: DH win fraction = 78.0% ≥ 70%
```

---

## Including Sentence Results in JSON Output

If you want sentence-by-sentence results in the JSON output, you need to update the `to_dict()` method:

### Current Implementation (Missing Sentence Results)

```python
def to_dict(self) -> Dict[str, Any]:
    return {
        "cluster_id": self.cluster_id,
        # ... other fields ...
        # ❌ entailment_results is NOT included
    }
```

### Enhanced Implementation (Include Sentence Results)

```python
def to_dict(self) -> Dict[str, Any]:
    return {
        "cluster_id": self.cluster_id,
        "timestamp": self.timestamp.isoformat(),
        "validation_status": self.validation_status,
        "overall_confidence": self.overall_confidence,
        "statements_validated": self.statements_validated,
        
        # ✅ NEW: Include sentence-by-sentence results
        "sentence_results": [
            {
                "statement": result.statement,
                "status": "ENTAILMENT" if result.is_valid else 
                         "CONTRADICTION" if result.is_contradiction else 
                         "NEUTRAL",
                "confidence": result.confidence,
                "evidence": result.reason,
                "label": result.label.value
            }
            for result in self.entailment_results
        ],
        
        # Aggregated counts
        "verified_count": self.verified_count,
        "unverified_count": self.unverified_count,
        "contradiction_count": self.contradiction_count,
        "verified_rate": self.verified_rate,
        "unverified_rate": self.unverified_rate,
        "contradiction_rate": self.contradiction_rate,
        
        # Contradictions (detailed)
        "contradictions": [
            {
                "statement": c.statement,
                "context": c.context,
                "confidence": c.confidence,
                "evidence": c.evidence
            }
            for c in self.contradictions
        ],
        
        "warnings": self.warnings,
        "feedback_iterations": self.feedback_iterations,
        "evidence": self.evidence
    }
```

### Example JSON Output (Enhanced)

```json
{
  "cluster_id": "ST010",
  "timestamp": "2026-01-19T12:00:00",
  "validation_status": "pass",
  "overall_confidence": 0.88,
  "statements_validated": 3,
  
  "sentence_results": [
    {
      "statement": "The recommended choice is District Heating (DH)",
      "status": "ENTAILMENT",
      "confidence": 0.95,
      "evidence": "Recommended choice is DH (verified)",
      "label": "Entailment"
    },
    {
      "statement": "DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh",
      "status": "ENTAILMENT",
      "confidence": 0.90,
      "evidence": "DH LCOH (75.2) < HP LCOH (82.5), diff=7.3",
      "label": "Entailment"
    },
    {
      "statement": "This is a robust decision with DH winning in 78% of scenarios",
      "status": "ENTAILMENT",
      "confidence": 0.90,
      "evidence": "DH win fraction = 78.0% ≥ 70%",
      "label": "Entailment"
    }
  ],
  
  "verified_count": 3,
  "unverified_count": 0,
  "contradiction_count": 0,
  "verified_rate": 1.0,
  "unverified_rate": 0.0,
  "contradiction_rate": 0.0,
  
  "contradictions": [],
  "warnings": [],
  "feedback_iterations": 1,
  
  "evidence": {
    "kpis": {
      "lcoh_dh_median": "75.2",
      "lcoh_hp_median": "82.5",
      "choice": "DH"
    }
  }
}
```

---

## Summary

### Current State

- ✅ **Data Available**: Sentence-by-sentence results ARE stored in `report.entailment_results`
- ❌ **Not in JSON**: `to_dict()` does NOT include `entailment_results`
- ✅ **Accessible in Python**: You can iterate through `report.entailment_results` to see all details
- ❌ **Limited in JSON**: Only contradictions are detailed; verified/neutral statements are aggregated

### What You Get Currently

**In Python**:
```python
for result in report.entailment_results:
    # Full access to each statement's status, evidence, confidence
```

**In JSON** (via `to_dict()`):
```json
{
  "verified_count": 2,
  "unverified_count": 1,
  "contradiction_count": 0,
  "contradictions": []  // Only contradictions are detailed
}
```

### To Get Sentence-by-Sentence in JSON

You need to:
1. Update `ValidationReport.to_dict()` to include `entailment_results`
2. Or access the report object directly instead of using `to_dict()`
3. Or create a custom serialization method that includes sentence results

---

**Last Updated**: 2026-01-19  
**Note**: The validation system DOES validate each sentence and stores the results, but the default JSON output only includes aggregated counts. Full sentence-by-sentence details are available in the `entailment_results` field when accessing the report object in Python.
