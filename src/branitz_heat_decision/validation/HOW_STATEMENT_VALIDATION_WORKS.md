# How Statement Validation Works

This document explains **exactly how** the validation system validates statements against KPI data.

---

## Overview: Two Validation Paths

The validation system uses **two complementary approaches**:

1. **Rule-Based Validation** (Deterministic, Fast, 100% Reliable)
   - Pattern matching against KPI data
   - No AI/LLM needed
   - Instant results

2. **LLM-Based Validation** (Semantic, Flexible, Handles Complexity)
   - Uses Gemini API for natural language understanding
   - Handles complex statements rules can't cover
   - Falls back to rules if LLM unavailable

**Validation Strategy**: Try rules first, use LLM only if rules return NEUTRAL.

---

## Step-by-Step Validation Process

### Step 1: Parse the Rationale into Statements

When you provide a rationale (free-text explanation), it's first parsed into individual statements:

```python
# Input rationale:
rationale = """
The recommended choice is District Heating (DH).
DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh.
This is a robust decision with DH winning in 78% of Monte Carlo scenarios.
"""

# Parsed into statements:
statements = [
    "The recommended choice is District Heating (DH)",
    "DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh",
    "This is a robust decision with DH winning in 78% of Monte Carlo scenarios"
]
```

**Parsing Logic** (`logic_auditor.py`):
- Splits on sentence boundaries (`.`, `!`, `?`)
- Filters out very short sentences (< 15 characters)
- Ensures sentences contain letters

---

### Step 2: Validate Each Statement

Each statement is validated individually against the KPI data:

```python
kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5,
    "choice": "DH",
    "dh_feasible": True,
    "hp_feasible": True,
    "dh_wins_fraction": 0.78,
    "hp_wins_fraction": 0.22
}

# Validate each statement
for statement in statements:
    result = validate_statement(kpis, statement)
    # result is one of: ENTAILMENT, CONTRADICTION, or NEUTRAL
```

---

## Validation Method 1: Rule-Based Validation (Deterministic)

Rule-based validation uses **pattern matching** and **direct KPI lookups** to validate statements. This is **100% deterministic** - no AI needed.

### How It Works

1. **Extract KPI Values**: Look up relevant KPIs from the data dictionary
2. **Pattern Match**: Check if statement contains specific keywords/phrases
3. **Compare Values**: Perform direct numerical/boolean comparisons
4. **Return Result**: ENTAILMENT (verified), CONTRADICTION (false), or NEUTRAL (can't verify)

### Rule Categories

#### 1. Recommended Choice Validation

**Pattern**: Statement mentions "recommended choice" and "DH" or "HP"

**Example**:
```python
statement = "The recommended choice is District Heating"
choice = kpis.get("choice")  # "DH"

# Rule checks:
if "recommended" in statement.lower() and "choice" in statement.lower():
    if "dh" in statement.lower() or "district" in statement.lower():
        if choice == "DH":
            return ENTAILMENT (✅ Verified)
        else:
            return CONTRADICTION (❌ False - choice is not DH)
```

**Real Code** (`tnli_model.py` lines 217-231):
```python
# 1. RECOMMENDED CHOICE VALIDATION
if "recommended" in statement_lower and "choice" in statement_lower:
    if "dh" in statement_lower or "district" in statement_lower:
        if choice == "DH":
            return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
                f"Recommended choice is DH (verified)")
        elif choice:
            return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
                f"Recommended choice is {choice}, not DH")
```

---

#### 2. Feasibility Claims

**Pattern**: Statement mentions "only DH feasible" or "only HP feasible"

**Example**:
```python
statement = "Only district heating is feasible"
dh_feasible = kpis.get("dh_feasible")  # True
hp_feasible = kpis.get("hp_feasible")  # False

# Rule checks:
if "only_dh_feasible" in statement.lower():
    if dh_feasible is True and hp_feasible is False:
        return ENTAILMENT (✅ Verified)
    elif dh_feasible is not None and hp_feasible is not None:
        return CONTRADICTION (❌ False)
```

**Real Code** (`tnli_model.py` lines 234-248):
```python
# 2. FEASIBILITY CLAIMS
if "only_dh_feasible" in statement_lower or "only dh feasible" in statement_lower:
    if dh_feasible is True and hp_feasible is False:
        return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
            "DH feasible=True, HP feasible=False")
    elif dh_feasible is not None and hp_feasible is not None:
        return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
            f"DH feasible={dh_feasible}, HP feasible={hp_feasible}")
```

---

#### 3. Robustness Claims

**Pattern**: Statement mentions "robust" or "robust decision"

**Example**:
```python
statement = "This is a robust decision"
dh_wins = kpis.get("dh_wins_fraction")  # 0.78
choice = kpis.get("choice")  # "DH"

# Rule checks:
if "robust" in statement.lower():
    if dh_wins >= 0.7 and choice == "DH":
        return ENTAILMENT (✅ Verified - win fraction ≥ 70%)
    elif dh_wins < 0.7:
        return CONTRADICTION (❌ False - win fraction < 70%)
```

**Real Code** (`tnli_model.py` lines 251-262):
```python
# 3. ROBUSTNESS CLAIMS
if "robust" in statement_lower:
    if dh_wins is not None and dh_wins >= 0.7 and ("dh" in statement_lower or choice == "DH"):
        return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
            f"DH win fraction = {dh_wins:.1%} ≥ 70%")
    elif dh_wins is not None and hp_wins is not None:
        winner_fraction = dh_wins if choice == "DH" else hp_wins
        if winner_fraction < 0.7:
            return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.85,
                f"Win fraction = {winner_fraction:.1%} < 70% (not robust)")
```

---

#### 4. Cost/LCOH Comparisons

**Pattern**: Statement mentions "cheaper", "lower cost", "lower lcoh", or "cost dominant"

**Example**:
```python
statement = "DH is cheaper than HP"
lcoh_dh = kpis.get("lcoh_dh_median")  # 75.2
lcoh_hp = kpis.get("lcoh_hp_median")  # 82.5

# Rule checks:
if "cheaper" in statement.lower() and "dh" in statement.lower():
    if lcoh_dh < lcoh_hp:
        return ENTAILMENT (✅ Verified - 75.2 < 82.5)
    else:
        return CONTRADICTION (❌ False - DH is not cheaper)
```

**Real Code** (`tnli_model.py` lines 264-287):
```python
# 4. LCOH/COST COMPARISONS
is_dh_ref = "district" in statement_lower or "dh" in statement_lower
is_hp_ref = "heat pump" in statement_lower or "hp" in statement_lower

if ("cheaper" in statement_lower or "lower cost" in statement_lower or 
    "lower lcoh" in statement_lower or "cost dominant" in statement_lower):
    
    if is_dh_ref and lcoh_dh is not None and lcoh_hp is not None:
        if lcoh_dh < lcoh_hp:
            diff = lcoh_hp - lcoh_dh
            return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                f"DH LCOH ({lcoh_dh:.1f}) < HP LCOH ({lcoh_hp:.1f}), diff={diff:.1f}")
        else:
            return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.9,
                f"DH LCOH ({lcoh_dh:.1f}) ≥ HP LCOH ({lcoh_hp:.1f})")
```

---

#### 5. CO2 Emission Comparisons

**Pattern**: Statement mentions "lower co2", "lower emission", or "co2 tiebreaker"

**Example**:
```python
statement = "District heating has lower CO2 emissions"
co2_dh = kpis.get("co2_dh_median")  # 45.3
co2_hp = kpis.get("co2_hp_median")  # 52.1

# Rule checks:
if "lower co2" in statement.lower() and "dh" in statement.lower():
    if co2_dh < co2_hp:
        return ENTAILMENT (✅ Verified - 45.3 < 52.1)
    else:
        return CONTRADICTION (❌ False)
```

**Real Code** (`tnli_model.py` lines 289-305):
```python
# 5. CO2 COMPARISONS
if "lower co2" in statement_lower or "lower emission" in statement_lower or "co2 tiebreaker" in statement_lower:
    if is_dh_ref and co2_dh is not None and co2_hp is not None:
        if co2_dh < co2_hp:
            return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                f"DH CO2 ({co2_dh:.1f}) < HP CO2 ({co2_hp:.1f})")
        else:
            return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.9,
                f"DH CO2 ({co2_dh:.1f}) ≥ HP CO2 ({co2_hp:.1f})")
```

---

#### 6. Specific Numerical Values

**Pattern**: Statement mentions specific numbers that should match KPI values

**Example**:
```python
statement = "DH has LCOH of 75.2 EUR/MWh"
lcoh_dh = kpis.get("lcoh_dh_median")  # 75.2

# Rule checks:
numbers = extract_numbers(statement)  # [75.2]
for num in numbers:
    for kpi_name, kpi_val in kpis.items():
        if isinstance(kpi_val, (int, float)):
            if abs(num - kpi_val) < 1.0:  # Match within 1.0 tolerance
                return ENTAILMENT (✅ Verified - 75.2 matches lcoh_dh_median)
```

**Real Code** (`tnli_model.py` lines 307-318):
```python
# 6. Specific numerical values mentioned
numbers_in_statement = re.findall(r'\d+\.?\d*', statement)
for num_str in numbers_in_statement:
    try:
        num = float(num_str)
        for kpi_name, kpi_val in kpis.items():
            if isinstance(kpi_val, (int, float)):
                if abs(num - kpi_val) < 1.0:  # Match within 1.0 tolerance
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.85,
                        f"Value {num} matches {kpi_name}={kpi_val:.2f}")
    except ValueError:
        continue
```

---

### Rule-Based Validation Result

If **any rule matches** and validates:
- ✅ **ENTAILMENT**: Statement is verified (confidence: 0.85-0.95)
- ❌ **CONTRADICTION**: Statement is proven false (confidence: 0.85-0.95)
- ⚪ **NEUTRAL**: No matching rules (confidence: 0.5)

If result is **NEUTRAL**, the system proceeds to **LLM-based validation** (if available).

---

## Validation Method 2: LLM-Based Validation (Semantic)

If rule-based validation returns **NEUTRAL** (can't verify with rules), the system uses **Gemini LLM API** for semantic validation.

### How It Works

1. **Format KPIs**: Convert KPI data into a readable format
2. **Create Prompt**: Build a prompt asking LLM to validate the statement
3. **Call LLM API**: Send prompt to Gemini API
4. **Parse Response**: Extract verdict (ENTAILED/CONTRADICTION/NEUTRAL)
5. **Return Result**: Return validation result with confidence

### LLM Prompt Structure

**Input to LLM**:
```
You are a fact-checker for a district heating decision system.

Given the KPI data and a statement, determine if the statement is:
- ENTAILED: The statement is clearly supported by the data
- CONTRADICTION: The statement clearly contradicts the data
- NEUTRAL: Cannot determine from the data alone

KPI Data:
- lcoh_dh_median: 75.2
- lcoh_hp_median: 82.5
- choice: DH
- dh_feasible: True
- hp_feasible: True
- dh_wins_fraction: 0.78

Statement: "District heating is the recommended solution because it offers better long-term economic benefits."

Respond in this exact format:
VERDICT: [ENTAILED/CONTRADICTION/NEUTRAL]
REASON: [Brief explanation why]
```

**LLM Response** (Example):
```
VERDICT: ENTAILED
REASON: The statement is supported because DH has lower LCOH (75.2 vs 82.5), is the recommended choice (DH), and has a robust win fraction (78%).
```

### LLM Validation Code

**Real Code** (`tnli_model.py` lines 131-183):
```python
def _validate_with_llm(
    self,
    kpis: Dict[str, Any],
    statement: str
) -> LightweightResult:
    """Validate using LLM API."""
    try:
        prompt = f"""You are a fact-checker for a district heating decision system.

Given the KPI data and a statement, determine if the statement is:
- ENTAILED: The statement is clearly supported by the data
- CONTRADICTION: The statement clearly contradicts the data
- NEUTRAL: Cannot determine from the data alone

KPI Data:
{self._format_kpis(kpis)}

Statement: "{statement}"

Respond in this exact format:
VERDICT: [ENTAILED/CONTRADICTION/NEUTRAL]
REASON: [Brief explanation why]"""

        response = self.llm_client.generate_content(prompt)
        text = response.text.strip()
        
        # Parse response
        verdict = "NEUTRAL"
        reason = ""
        
        for line in text.split("\n"):
            if line.startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip().upper()
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
        
        if "ENTAILED" in verdict or "ENTAIL" in verdict:
            return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.85, reason)
        elif "CONTRADICTION" in verdict or "CONTRADICT" in verdict:
            return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.85, reason)
        else:
            return LightweightResult(statement, EntailmentLabel.NEUTRAL, 0.5, reason or "LLM uncertain")
            
    except Exception as e:
        # Disable LLM on exception to prevent repeated failures
        logger.warning(f"LLM validation failed: {e}. Disabling LLM for remaining validations.")
        self.llm_client = None  # Fail closed - use rules for rest of run
        return LightweightResult(statement, EntailmentLabel.NEUTRAL, 0.5, 
            "LLM unavailable, falling back to rules")
```

---

## Complete Validation Flow Example

Let's trace through a complete example:

### Input

```python
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
This is a robust decision with DH winning in 78% of Monte Carlo scenarios.
"""
```

### Step 1: Parse into Statements

```python
statements = [
    "The recommended choice is District Heating (DH)",
    "DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh",
    "This is a robust decision with DH winning in 78% of Monte Carlo scenarios"
]
```

### Step 2: Validate Each Statement

#### Statement 1: "The recommended choice is District Heating (DH)"

**Rule-Based Validation**:
1. ✅ Matches pattern: "recommended" + "choice" + "dh"
2. ✅ Checks `choice == "DH"` → True
3. **Result**: ✅ ENTAILMENT (confidence: 0.95)
4. **Reason**: "Recommended choice is DH (verified)"

#### Statement 2: "DH is cheaper with LCOH of 75.2 EUR/MWh compared to HP at 82.5 EUR/MWh"

**Rule-Based Validation**:
1. ✅ Matches pattern: "cheaper" + "dh"
2. ✅ Extracts numbers: [75.2, 82.5]
3. ✅ Checks `lcoh_dh < lcoh_hp`: 75.2 < 82.5 → True
4. ✅ Matches numerical value: 75.2 matches `lcoh_dh_median`
5. **Result**: ✅ ENTAILMENT (confidence: 0.9)
6. **Reason**: "DH LCOH (75.2) < HP LCOH (82.5), diff=7.3"

#### Statement 3: "This is a robust decision with DH winning in 78% of Monte Carlo scenarios"

**Rule-Based Validation**:
1. ✅ Matches pattern: "robust"
2. ✅ Checks `dh_wins_fraction >= 0.7`: 0.78 >= 0.7 → True
3. ✅ Checks `choice == "DH"`: True
4. ✅ Extracts number: 78 (matches 0.78 when converted)
5. **Result**: ✅ ENTAILMENT (confidence: 0.9)
6. **Reason**: "DH win fraction = 78.0% ≥ 70%"

### Step 3: Aggregate Results

```python
results = [
    ENTAILMENT (confidence: 0.95),  # Statement 1
    ENTAILMENT (confidence: 0.9),   # Statement 2
    ENTAILMENT (confidence: 0.9)    # Statement 3
]

# Aggregate:
verified_count = 3
unverified_count = 0
contradiction_count = 0
overall_confidence = (0.95 + 0.9 + 0.9) / 3 = 0.917
validation_status = "pass"  # No contradictions
```

### Final Validation Report

```python
ValidationReport(
    cluster_id="ST010",
    timestamp=datetime.now(),
    validation_status="pass",
    overall_confidence=0.917,
    statements_validated=3,
    verified_count=3,
    unverified_count=0,
    contradiction_count=0,
    verified_rate=1.0,  # 100% verified
    contradictions=[]
)
```

---

## Contradiction Example

Let's see what happens when a statement contradicts the data:

### Input

```python
kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5,
    "choice": "DH"
}

statement = "Heat pumps are cheaper than district heating"
```

### Validation

**Rule-Based Validation**:
1. ✅ Matches pattern: "cheaper" + "hp"
2. ✅ Gets values: `lcoh_hp = 82.5`, `lcoh_dh = 75.2`
3. ❌ Checks `lcoh_hp < lcoh_dh`: 82.5 < 75.2 → False
4. **Result**: ❌ CONTRADICTION (confidence: 0.9)
5. **Reason**: "HP LCOH (82.5) ≥ DH LCOH (75.2)"

### Result

```python
Contradiction(
    statement="Heat pumps are cheaper than district heating",
    context="KPIs: lcoh_dh_median, lcoh_hp_median",
    confidence=0.9,
    evidence={
        "kpis_checked": ["lcoh_dh_median", "lcoh_hp_median"],
        "reason": "HP LCOH (82.5) ≥ DH LCOH (75.2)"
    }
)

# Validation Status: FAIL (contradiction detected)
```

---

## Neutral Example (No Rules Match)

Sometimes a statement can't be validated with rules:

### Input

```python
kpis = {
    "lcoh_dh_median": 75.2,
    "lcoh_hp_median": 82.5
}

statement = "District heating is preferred by the local community"
```

### Rule-Based Validation

1. ❌ No pattern matches: "preferred by local community" not in rules
2. ❌ No numerical values to check
3. **Result**: ⚪ NEUTRAL (confidence: 0.5)
4. **Reason**: "Could not verify against KPIs with rules"

### LLM-Based Validation (If Available)

**Prompt to LLM**:
```
KPI Data:
- lcoh_dh_median: 75.2
- lcoh_hp_median: 82.5

Statement: "District heating is preferred by the local community"

VERDICT: [ENTAILED/CONTRADICTION/NEUTRAL]
REASON: [Brief explanation why]
```

**LLM Response**:
```
VERDICT: NEUTRAL
REASON: The statement mentions community preference, which cannot be verified from cost/technical KPIs alone.
```

**Final Result**: ⚪ NEUTRAL (unverified, but not contradictory)

---

## Structured Claims Validation (Alternative Path)

For structured claims (from reason codes), validation is **100% deterministic**:

### Example

```python
# Decision result with reason codes
decision_data = {
    "choice": "DH",
    "reason_codes": ["COST_DOMINANT_DH", "ROBUST_DECISION"],
    "metrics_used": {
        "lcoh_dh_median": 75.2,
        "lcoh_hp_median": 82.5,
        "dh_wins_fraction": 0.78
    }
}

# Convert to structured claims
structured = StructuredExplanation.from_decision_result(decision_data)

# Claims generated:
claims = [
    Claim(
        claim_type=ClaimType.LCOH_COMPARE,
        lhs="lcoh_dh_median",
        op=Operator.LT,  # <
        rhs="lcoh_hp_median",
        description="DH has lower LCOH than HP"
    ),
    Claim(
        claim_type=ClaimType.ROBUSTNESS,
        lhs="dh_wins_fraction",
        op=Operator.GE,  # >=
        rhs=0.7,
        description="DH has robust win fraction (≥70%)"
    )
]
```

### Validation

```python
# Validate each claim
for claim in claims:
    # Get LHS value
    lhs_val = get_value(claim.lhs, kpis)  # 75.2 or 0.78
    
    # Get RHS value
    rhs_val = get_value(claim.rhs, kpis)  # 82.5 or 0.7
    
    # Perform comparison
    if claim.op == Operator.LT:
        is_valid = lhs_val < rhs_val  # 75.2 < 82.5 → True
    elif claim.op == Operator.GE:
        is_valid = lhs_val >= rhs_val  # 0.78 >= 0.7 → True
    
    # Result
    if is_valid:
        return ClaimResult(is_valid=True, ...)
    else:
        return ClaimResult(is_valid=False, ...)
```

**Advantages**:
- ✅ 100% deterministic (no AI needed)
- ✅ Fast execution (< 1ms per claim)
- ✅ High reliability
- ✅ Fully auditable

---

## Summary: How Validation Works

1. **Parse**: Split rationale into individual statements

2. **Validate Each Statement**:
   - **Try Rules First**: Pattern match + direct KPI comparison
   - **Try LLM If Neutral**: Semantic validation if rules can't verify
   - **Return Result**: ENTAILMENT, CONTRADICTION, or NEUTRAL

3. **Aggregate Results**:
   - Count verified/unverified/contradictions
   - Calculate confidence scores
   - Determine overall status (PASS/WARNING/FAIL)

4. **Report**: Generate comprehensive validation report

**Key Principles**:
- ✅ Deterministic rules for known patterns (fast, reliable)
- ✅ LLM fallback for complex statements (flexible, handles edge cases)
- ✅ Fail-safe: Falls back to rules if LLM unavailable
- ✅ Transparent: All validation logic is auditable

---

**Last Updated**: 2026-01-19  
**Author**: Validation Module Development Team
