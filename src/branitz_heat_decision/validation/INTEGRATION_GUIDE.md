# Integration Guide: Using TNLI Logic Auditor with Branitz Heat Decision System

## **Overview**

The TNLI (Tabular Natural Language Inference) Logic Auditor validates LLM-generated explanations against KPI data to ensure factual accuracy. Here's how to integrate it with your Branitz system.

---

## **1. INSTALLATION & SETUP**

### 1.1 Install Dependencies

```bash
# Add to requirements.txt
google-generativeai>=0.3.0
python-dotenv>=1.0.0

# Install
pip install google-generativeai python-dotenv
```

### 1.2 Environment Configuration

**Add to `.env`:**
```bash
# For TNLI Validator (uses Gemini for semantic validation)
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash  # or gemini-1.5-pro for better accuracy

# Optional: Force rule-based validation only (no LLM)
USE_LLM_VALIDATION=true  # set to false to disable LLM validation
```

### 1.3 Bootstrap Environment Loading

**Ensure your `utils/env.py` or equivalent loads environment:**

```python
# utils/env.py (already exists from earlier recommendations)
from pathlib import Path
from dotenv import load_dotenv

def bootstrap_env():
    """Load .env from project root"""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            print(f"✓ Loaded environment from {env_file}")
            return True
    return False
```

---

## **2. QUICK START: VALIDATE A DECISION EXPLANATION**

### 2.1 Basic Usage (No Feedback Loop)

```python
from branitz_heat_decision.validation import LogicAuditor

# Initialize validator
auditor = LogicAuditor()

# Your KPIs from decision pipeline
kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5,
    "co2_dh_median": 45.3,
    "co2_hp_median": 52.1,
    "dh_feasible": True,
    "hp_feasible": True,
    "choice": "DH",
    "dh_wins_fraction": 0.78,
    "hp_wins_fraction": 0.22
}

# LLM-generated explanation to validate
explanation = """
The recommended choice is District Heating (DH).
DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh.
This is a robust decision with DH winning in 78% of Monte Carlo scenarios.
"""

# Validate
report = auditor.validate_rationale(
    kpis=kpis,
    rationale=explanation,
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE"
)

# Check results
print(f"Validation Status: {report.validation_status}")
print(f"Verified Rate: {report.verified_rate:.1%}")
print(f"Contradictions: {len(report.contradictions)}")

if report.has_contradictions:
    for contra in report.contradictions:
        print(f"❌ {contra.statement}")
        print(f"   Reason: {contra.reason}")
```

### 2.2 With Automatic Feedback Loop

```python
from branitz_heat_decision.validation import create_feedback_loop

# Create feedback loop
feedback_loop = create_feedback_loop()

# Define regeneration function (calls your LLM)
def regenerate_explanation(kpis, additional_context):
    """Regenerate explanation with corrected context"""
    prompt = f"""
Based on these KPIs:
{kpis}

{additional_context}

Generate a factually correct explanation for the heating decision.
"""
    # response = your_llm_client.generate(prompt)
    # return response.text
    return "Regenerated explanation..."

# Validate with automatic refinement
final_explanation, report = feedback_loop.validate_with_feedback(
    kpis=kpis,
    initial_rationale=explanation,
    regenerate_fn=regenerate_explanation,
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE"
)

print(f"Final explanation (after {report.feedback_iterations} iterations):")
print(final_explanation)
```

---

## **3. INTEGRATION WITH YOUR EXISTING SYSTEM**

### 3.1 Add to UHDC Report Generation

**File:** `uhdc/explainer.py` (or wherever you generate explanations)

```python
from branitz_heat_decision.validation import LogicAuditor

def explain_with_llm(contract: dict, config) -> dict:
    """Generate explanation with automatic validation"""
    
    # Existing LLM generation
    raw_explanation = _call_gemini_api(contract, config)
    
    # NEW: Validate explanation
    if config.validate_explanations:
        auditor = LogicAuditor()
        
        # Extract KPIs for validation
        kpis = {
            "lcoh_dh": contract.get("lcoh_dh"),
            "lcoh_hp": contract.get("lcoh_hp"),
            "co2_dh": contract.get("co2_dh"),
            "co2_hp": contract.get("co2_hp"),
            "choice": contract.get("choice"),
            "dh_feasible": contract.get("dh_feasible"),
            "hp_feasible": contract.get("hp_feasible"),
        }
        
        report = auditor.validate_rationale(
            kpis=kpis,
            rationale=raw_explanation,
            cluster_id=contract.get("cluster_id", "unknown")
        )
        
        # Log validation results
        logger.info(f"Explanation validation: {report.validation_status}")
        
        if report.has_contradictions:
            logger.warning(f"⚠️  {len(report.contradictions)} contradictions detected")
        
        return {
            "explanation": raw_explanation,
            "validation_status": report.validation_status,
            "validation_confidence": report.overall_confidence,
            "contradictions": len(report.contradictions),
            "validated_at": report.timestamp.isoformat()
        }
    
    return {"explanation": raw_explanation}
```

### 3.2 Add to Decision Pipeline

**File:** `decision/rules.py` (enhance DecisionResult)

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class DecisionResult:
    choice: str
    robust: bool
    reason_codes: List[str]
    metrics_used: Dict[str, float]
    explanation: Optional[str] = None
    validation_report: Optional[Dict[str, Any]] = None
    validation_status: Optional[str] = None
    
    def to_dict(self):
        result = {
            "choice": self.choice,
            "robust": self.robust,
            "reason_codes": self.reason_codes,
            "metrics_used": self.metrics_used
        }
        if self.explanation:
            result["explanation"] = self.explanation
        if self.validation_report:
            result["validation"] = self.validation_report
        return result
```

### 3.3 Display in Streamlit UI

```python
# After displaying decision results
if decision_result.get("validation"):
    st.divider()
    st.subheader("🔍 Explanation Validation")
    
    validation = decision_result["validation"]
    status = validation["validation_status"]
    
    if status == "pass":
        st.success(f"✅ Validation Passed ({validation['verified_rate']:.0%} verified)")
    elif status == "warning":
        st.warning(f"⚠️  Validation Warnings ({validation['unverified_rate']:.0%} unverified)")
    else:
        st.error(f"❌ Validation Failed ({len(validation['contradictions'])} contradictions)")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Statements", validation["statements_validated"])
    col2.metric("Verified", validation["verified_count"])
    col3.metric("Contradictions", validation["contradiction_count"])
```

---

## **4. CONFIGURATION OPTIONS**

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ValidationConfig:
    """Validation system configuration"""
    validate_explanations: bool = True
    use_llm_validation: bool = True
    min_confidence: float = 0.7
    enable_feedback: bool = False
    max_iterations: int = 3
    save_reports: bool = True
    report_dir: Path = Path("results/validation")
    
    @classmethod
    def from_env(cls):
        import os
        return cls(
            validate_explanations=os.getenv("VALIDATE_EXPLANATIONS", "true").lower() == "true",
            use_llm_validation=os.getenv("USE_LLM_VALIDATION", "true").lower() == "true",
            enable_feedback=os.getenv("ENABLE_VALIDATION_FEEDBACK", "false").lower() == "true"
        )
```

---

## **5. TESTING**

### Unit Test

```python
import pytest
from branitz_heat_decision.validation import LogicAuditor

def test_validation_pass():
    auditor = LogicAuditor()
    kpis = {"lcoh_dh_median": 75.0, "lcoh_hp_median": 82.0, "choice": "DH"}
    explanation = "The recommended choice is DH. DH is cheaper with LCOH of 75.0 EUR/MWh."
    
    report = auditor.validate_rationale(kpis, explanation, "test")
    
    assert report.validation_status == "pass"
    assert len(report.contradictions) == 0

def test_validation_fail():
    auditor = LogicAuditor()
    kpis = {"lcoh_dh_median": 75.0, "lcoh_hp_median": 82.0, "choice": "DH"}
    explanation = "Heat pumps are cheaper than district heating."
    
    report = auditor.validate_rationale(kpis, explanation, "test")
    
    assert report.validation_status == "fail"
    assert len(report.contradictions) > 0
```

---

## **6. TROUBLESHOOTING**

| Issue | Solution |
|-------|----------|
| "No GOOGLE_API_KEY found" | Ensure `.env` is loaded via `bootstrap_env()` |
| "LLM validation failed" | Expected fallback to rules - set `USE_LLM_VALIDATION=false` to force rules |
| Validation too strict | Lower `min_confidence` threshold |

---

## **QUICK REFERENCE**

```python
from branitz_heat_decision.validation import LogicAuditor

auditor = LogicAuditor()
kpis = {"lcoh_dh": 75.0, "lcoh_hp": 82.0, "choice": "DH"}
explanation = "DH is recommended because it's cheaper."

report = auditor.validate_rationale(kpis, explanation, "ST010")

print(f"Status: {report.validation_status}")
print(f"Verified: {report.verified_rate:.0%}")
print(f"Contradictions: {len(report.contradictions)}")
```

This validation system ensures your LLM-generated explanations are **factually grounded** in the actual KPI data, preventing hallucinations and maintaining auditability.
