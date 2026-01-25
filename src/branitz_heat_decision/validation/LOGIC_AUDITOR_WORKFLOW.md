# TNLI Logic Auditor Workflow - Complete Reference Documentation

Complete documentation for the Validation module implementing TNLI (Tabular Natural Language Inference) logic auditing to validate LLM-generated decision rationales against KPI data.

**Module Location**: `src/branitz_heat_decision/validation/`  
**Total Lines of Code**: ~1,900 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: google-generativeai, python-dotenv, dataclasses, logging, pathlib

---

## Module Overview

The Validation module provides a comprehensive logic auditing system that validates AI-generated decision explanations against hard KPI data to prevent hallucinations:

1. **Deterministic Validation**: Rule-based validation of structured claims (100% deterministic, no AI)
2. **Semantic Validation**: LLM-based fact-checking for free-text explanations
3. **Feedback Loop**: Automatic regeneration of explanations when contradictions are detected
4. **Monitoring**: Metrics tracking and performance monitoring
5. **Structured Claims**: Support for structured explanation formats for maximum reliability

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Logic Auditor (Orchestrator)                               │
│  ├─ Validates rationale against KPI data                    │
│  ├─ Hybrid approach: Deterministic + Semantic               │
│  └─ Optional feedback loop for auto-correction              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Validation Components                                      │
│  ├─ ClaimValidator: Deterministic structured claim checks   │
│  ├─ TNLIModel: LLM-based semantic validation                │
│  ├─ FeedbackLoop: Automatic regeneration with context       │
│  └─ ValidationMonitor: Metrics and alerting                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Output                                                     │
│  ├─ ValidationReport: Comprehensive validation results      │
│  ├─ Contradiction details with evidence                     │
│  └─ Metrics and monitoring data                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Module Files & Functions

### `__init__.py` (32 lines) ⭐ **MODULE EXPORTS**
**Purpose**: Module initialization and public API exports

**Exports**:
```python
from .logic_auditor import LogicAuditor, ValidationReport, Contradiction
from .tnli_model import TNLIModel, LightweightResult as EntailmentResult, EntailmentLabel
from .config import ValidationConfig
from .feedback_loop import FeedbackLoop
from .claims import (
    ClaimType, Claim, ClaimResult, ClaimValidator, 
    StructuredExplanation, Operator
)
```

**Public API**:
- `LogicAuditor`: Main entry point for validation
- `ValidationReport`: Validation results dataclass
- `Contradiction`: Contradiction details dataclass
- `TNLIModel`: LLM-based validation model wrapper
- `ValidationConfig`: Configuration dataclass
- `FeedbackLoop`: Automatic regeneration handler
- `ClaimValidator`: Deterministic claim validation
- `StructuredExplanation`: Structured explanation format

---

### `logic_auditor.py` (445 lines) ⭐ **MAIN ORCHESTRATOR**
**Purpose**: Main validation orchestrator that coordinates all validation components

**Classes**:

#### `Contradiction` (Dataclass)
```python
@dataclass
class Contradiction:
    statement: str              # The contradictory statement
    context: str                # Which KPI/metric it contradicts
    confidence: float           # Confidence score (0.0-1.0)
    evidence: Optional[Dict[str, Any]] = None  # Additional evidence
```
**Purpose**: Represents a detected contradiction between a statement and KPI data.

#### `ValidationReport` (Dataclass)
```python
@dataclass
class ValidationReport:
    cluster_id: str
    timestamp: datetime
    validation_status: str      # "pass", "warning", "fail"
    overall_confidence: float
    statements_validated: int = 0
    contradictions: List[Contradiction] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    feedback_iterations: int = 0
    
    # Scoring metrics (Edit C: Proper semantics)
    verified_count: int = 0     # ENTAILED statements
    unverified_count: int = 0   # NEUTRAL statements
    contradiction_count: int = 0  # CONTRADICTION statements
    
    # Properties
    @property
    def verified_rate(self) -> float: ...
    @property
    def unverified_rate(self) -> float: ...
    @property
    def contradiction_rate(self) -> float: ...
    @property
    def has_contradictions(self) -> bool: ...
    
    def to_dict(self) -> Dict[str, Any]: ...
```
**Purpose**: Comprehensive validation report with scoring metrics and contradictions.

**Scoring Semantics (Edit C)**:
- **verified_rate**: Fraction of statements that are ENTAILED (supported by data)
- **unverified_rate**: Fraction that are NEUTRAL (cannot be proven)
- **contradiction_rate**: Fraction that CONTRADICT the data

**Status Logic**:
- **FAIL**: Any contradictions detected
- **WARNING**: >50% unverified statements or low confidence
- **PASS**: High verification rate and no contradictions

#### `LogicAuditor` (Main Class)
```python
class LogicAuditor:
    def __init__(self, config: Optional[ValidationConfig] = None)
    def validate_rationale(
        self,
        kpis: Dict[str, Any],
        rationale: str,
        cluster_id: str = "unknown",
        regenerate_fn: Optional[Callable[[Dict[str, Any], str], str]] = None
    ) -> ValidationReport
    def validate_structured_claims(
        self,
        kpis: Dict[str, Any],
        explanation: StructuredExplanation,
        cluster_id: str = "unknown"
    ) -> ValidationReport
    def validate_decision_explanation(
        self,
        decision_data: Dict[str, Any]
    ) -> ValidationReport
```

**Main Methods**:

##### `validate_rationale()` ⭐ **PRIMARY VALIDATION METHOD**
**Purpose**: Validate a free-text rationale against KPI data.

**Workflow**:
1. Parse rationale into individual statements
2. Validate each statement using TNLIModel (rule-based + LLM)
3. Aggregate results and compute scores
4. Optionally regenerate if contradictions found (feedback loop)

**Parameters**:
- `kpis`: Dictionary of KPI metrics and values
- `rationale`: Natural language explanation to validate
- `cluster_id`: Identifier for the cluster
- `regenerate_fn`: Optional function to regenerate rationale on contradictions

**Returns**: `ValidationReport` with validation results

**Feedback Loop (Edit D)**:
- If `regenerate_fn` provided and `enable_feedback=True`
- Automatically regenerates rationale up to `max_iterations` times
- Stops when no contradictions or max iterations reached

##### `validate_structured_claims()` ⭐ **DETERMINISTIC VALIDATION**
**Purpose**: Validate structured claims (100% deterministic, no LLM).

**Parameters**:
- `kpis`: Dictionary of KPI metrics
- `explanation`: `StructuredExplanation` with claims
- `cluster_id`: Identifier

**Returns**: `ValidationReport` with deterministic results (confidence=1.0)

##### `validate_decision_explanation()` ⭐ **DECISION PIPELINE INTEGRATION**
**Purpose**: Validate a complete decision explanation from decision pipeline.

**Features**:
- **Issue A Fix**: Injects choice/reason_codes into KPIs for validation
- **Correctness Fix**: Uses structured claims for reason_codes (validates each individually)
- Automatically infers feasibility from reason_codes if not in KPIs
- Falls back to free-text validation if no structured data

**Parameters**:
- `decision_data`: Dictionary with keys:
  - `kpis` or `metrics_used`: KPI data
  - `choice` or `recommendation`: Decision choice (DH/HP/UNDECIDED)
  - `reason_codes`: List of reason codes
  - `robust`: Robustness flag
  - `explanation`: Optional free-text explanation
  - `claims`: Optional structured claims

**Returns**: `ValidationReport`

**Helper Methods**:
- `_validate_once()`: Single validation pass (no feedback)
- `_parse_statements()`: Parse rationale into statements (sentence splitting)
- `_identify_contradiction_context()`: Identify which KPI(s) a contradiction relates to
- `_build_feedback_context()`: Build enriched context for regeneration

---

### `claims.py` (358 lines) ⭐ **STRUCTURED CLAIMS SYSTEM**
**Purpose**: Deterministic validation system using structured claims (no LLM needed)

**Enums**:

#### `ClaimType`
```python
class ClaimType(str, Enum):
    LCOH_COMPARE = "LCOH_COMPARE"      # Compare LCOH values
    CO2_COMPARE = "CO2_COMPARE"         # Compare CO2 emissions
    ROBUSTNESS = "ROBUSTNESS"           # Monte Carlo win fraction check
    FEASIBILITY = "FEASIBILITY"         # Feasibility flag check
    THRESHOLD = "THRESHOLD"             # Generic threshold comparison
    CHOICE_VALID = "CHOICE_VALID"       # Validate choice against data
```

#### `Operator`
```python
class Operator(str, Enum):
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    NE = "!="
```

**Classes**:

#### `Claim` (Dataclass)
```python
@dataclass
class Claim:
    claim_type: ClaimType
    lhs: str                      # Left-hand side (KPI key or value)
    op: Operator                  # Comparison operator
    rhs: str | float              # Right-hand side (KPI key or literal)
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Claim": ...
```
**Purpose**: Represents a verifiable claim about KPI data.

**Example**:
```python
Claim(
    claim_type=ClaimType.LCOH_COMPARE,
    lhs="lcoh_dh_median",
    op=Operator.LT,
    rhs="lcoh_hp_median",
    description="DH has lower LCOH than HP"
)
```

#### `ClaimResult` (Dataclass)
```python
@dataclass
class ClaimResult:
    claim: Claim
    is_valid: bool
    actual_lhs: Optional[float] = None
    actual_rhs: Optional[float] = None
    reason: str = ""
```
**Purpose**: Result of validating a single claim.

#### `StructuredExplanation` (Dataclass)
```python
@dataclass
class StructuredExplanation:
    choice: str                   # "DH", "HP", or "UNDECIDED"
    claims: List[Claim]           # List of verifiable claims
    rationale_text: str           # Human-readable summary
    
    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredExplanation": ...
    @classmethod
    def from_decision_result(cls, decision_result: Dict[str, Any]) -> "StructuredExplanation": ...
```
**Purpose**: Structured explanation format for deterministic validation.

**Key Method**: `from_decision_result()`
- Converts decision result (reason_codes + metrics) into structured claims
- Maps reason codes to specific claim types:
  - `COST_DOMINANT_DH` → LCOH comparison claim
  - `COST_DOMINANT_HP` → LCOH comparison claim
  - `CO2_TIEBREAKER_DH` → CO2 comparison claim
  - `ROBUST_DECISION` → Robustness claim
  - `ONLY_DH_FEASIBLE` → Feasibility claims
  - `ONLY_HP_FEASIBLE` → Feasibility claims

#### `ClaimValidator` (Main Class)
```python
class ClaimValidator:
    KEY_ALIASES = {
        "dh_feasible": ["dh_feasible", "cha_feasible", "feasible_dh"],
        "hp_feasible": ["hp_feasible", "dha_feasible", "feasible_hp", "grid_feasible"],
        "recommended_choice": ["choice", "recommendation", "recommended_choice"],
        "dh_wins_fraction": ["dh_wins_fraction", "dh_win_fraction", "mc_dh_wins"],
        "hp_wins_fraction": ["hp_wins_fraction", "hp_win_fraction", "mc_hp_wins"],
        "lcoh_dh": ["lcoh_dh_median", "lcoh_dh"],
        "lcoh_hp": ["lcoh_hp_median", "lcoh_hp"],
        "co2_dh": ["co2_dh_median", "co2_dh"],
        "co2_hp": ["co2_hp_median", "co2_hp"],
    }
    
    def validate_claim(self, claim: Claim, kpis: Dict[str, Any]) -> ClaimResult
    def validate_all(self, explanation: StructuredExplanation, kpis: Dict[str, Any]) -> List[ClaimResult]
```

**Methods**:

##### `validate_claim()` ⭐ **SINGLE CLAIM VALIDATION**
**Purpose**: Validate a single claim against KPI data (100% deterministic).

**Workflow**:
1. Get LHS value from KPIs (with alias mapping)
2. Get RHS value (literal or KPI reference)
3. Perform comparison using operator
4. Return `ClaimResult` with validation outcome

##### `validate_all()` ⭐ **BATCH VALIDATION**
**Purpose**: Validate all claims in a structured explanation.

**Returns**: List of `ClaimResult` objects

**Helper Methods**:
- `_get_value()`: Get value from KPIs with alias and suffix fallback
- `_compare()`: Perform comparison operation (handles type conversion)

---

### `tnli_model.py` (363 lines) ⭐ **LLM-BASED VALIDATION**
**Purpose**: Lightweight LLM-based validation (no large model download required)

**Enums**:

#### `EntailmentLabel`
```python
class EntailmentLabel(str, Enum):
    ENTAILMENT = "Entailment"      # Statement is supported by data
    NEUTRAL = "Neutral"             # Cannot determine from data
    CONTRADICTION = "Contradiction" # Statement contradicts data
```

**Classes**:

#### `LightweightResult` (Dataclass)
```python
@dataclass
class LightweightResult:
    statement: str
    label: EntailmentLabel
    confidence: float
    reason: str = ""
    
    @property
    def is_valid(self) -> bool: ...
    @property
    def is_contradiction(self) -> bool: ...
    @property
    def is_neutral(self) -> bool: ...
```
**Purpose**: Result from lightweight validation.

#### `LightweightValidator` (Main Class)
```python
class LightweightValidator:
    def __init__(self, use_llm: bool = True)
    def validate_statement(
        self,
        kpis: Dict[str, Any],
        statement: str
    ) -> LightweightResult
    def batch_validate(
        self,
        kpis: Dict[str, Any],
        statements: List[str]
    ) -> List[LightweightResult]
```

**Validation Strategy**:
1. **Rule-based first**: Try deterministic rule-based validation
2. **LLM fallback**: If rules return NEUTRAL and LLM available, use LLM

**Methods**:

##### `validate_statement()` ⭐ **SINGLE STATEMENT VALIDATION**
**Purpose**: Validate a single statement against KPIs.

**Workflow**:
1. Try rule-based validation first
2. If NEUTRAL and LLM available, try LLM
3. Return result with label and confidence

##### `_validate_with_rules()` ⭐ **ENHANCED RULE ENGINE (Edit B)**
**Purpose**: Deterministic rule-based validation covering common cases.

**Supported Rules**:
1. **Recommended Choice Validation**: Checks if statement matches actual choice
2. **Feasibility Claims**: Validates ONLY_DH_FEASIBLE / ONLY_HP_FEASIBLE
3. **Robustness Claims**: Checks win fraction ≥ 70%
4. **LCOH/COST Comparisons**: Validates "cheaper", "lower cost", etc.
5. **CO2 Comparisons**: Validates "lower emissions", "CO2 tiebreaker"
6. **Numerical Values**: Matches specific numbers mentioned in statement

**Returns**: `LightweightResult` with ENTAILMENT, CONTRADICTION, or NEUTRAL

##### `_validate_with_llm()` ⭐ **LLM-BASED VALIDATION**
**Purpose**: Use Gemini API for semantic fact-checking.

**Model Configuration**:
- Default: `gemini-1.5-flash` (configurable via `GEMINI_MODEL` env var)
- API Key: `GOOGLE_API_KEY` or `GEMINI_API_KEY` from `.env`
- Falls back to rules if LLM unavailable

**Prompt Format**:
```
You are a fact-checker for a district heating decision system.

Given the KPI data and a statement, determine if the statement is:
- ENTAILED: The statement is clearly supported by the data
- CONTRADICTION: The statement clearly contradicts the data
- NEUTRAL: Cannot determine from the data alone

KPI Data:
{formatted KPIs}

Statement: "{statement}"

Respond in this exact format:
VERDICT: [ENTAILED/CONTRADICTION/NEUTRAL]
REASON: [Brief explanation why]
```

**Issue B Fix**: Disables LLM client on exception to prevent repeated failures.

#### `TNLIModel` (Wrapper Class)
```python
class TNLIModel:
    def __init__(self, config=None)
    def validate_statement(self, table_data: Dict[str, Any], statement: str)
    def batch_validate(self, table_data: Dict[str, Any], statements: List[str])
```
**Purpose**: Wrapper that uses `LightweightValidator` (compatible with original TNLI interface).

---

### `feedback_loop.py` (169 lines) ⭐ **AUTOMATIC REGENERATION**
**Purpose**: Manages feedback loop for automatic rationale regeneration when contradictions are detected

**Classes**:

#### `FeedbackLoop` (Main Class)
```python
class FeedbackLoop:
    def __init__(self, auditor: LogicAuditor, config: Optional[ValidationConfig] = None)
    def validate_with_feedback(
        self,
        kpis: Dict[str, Any],
        initial_rationale: str,
        regenerate_fn: Callable[[Dict[str, Any], str], str],
        cluster_id: str = "unknown"
    ) -> tuple[str, ValidationReport]
```

**Methods**:

##### `validate_with_feedback()` ⭐ **FEEDBACK LOOP ORCHESTRATION**
**Purpose**: Validate rationale with automatic regeneration on contradictions.

**Workflow**:
1. Validate initial rationale
2. If contradictions found and feedback enabled:
   - Build enriched context with contradictions and KPIs
   - Call `regenerate_fn` to generate new rationale
   - Re-validate new rationale
   - Repeat up to `max_iterations` times
3. Return final rationale and validation report

**Parameters**:
- `kpis`: KPI data table
- `initial_rationale`: Initial LLM-generated rationale
- `regenerate_fn`: Function to regenerate rationale
  - Signature: `(kpis: dict, additional_context: str) -> str`
- `cluster_id`: Cluster identifier

**Returns**: Tuple of `(final_rationale, validation_report)`

**Stopping Conditions**:
- No contradictions found
- Max iterations reached
- Regenerated rationale unchanged
- Regeneration function raises exception

##### `_build_enriched_context()` ⭐ **CONTEXT ENRICHMENT**
**Purpose**: Build enriched context for LLM regeneration.

**Context Includes**:
- **Verified KPI Values**: All relevant KPIs
- **Detected Contradictions**: List of contradictions with evidence
- **Guidelines**: Instructions for generating factually correct explanation

**Example Context**:
```
IMPORTANT: Previous explanation contained contradictions with the data.
Please regenerate ensuring all statements are consistent with these KPIs:

**Verified KPI Values:**
- lcoh_dh_median: 75.2
- lcoh_hp_median: 82.5
- choice: DH

**Detected Contradictions:**
1. "Heat pumps are cheaper"
   Context: KPIs: lcoh_dh_median, lcoh_hp_median
   Evidence: {'kpis_checked': ['lcoh_dh_median', 'lcoh_hp_median']}

**Guidelines:**
- Only make statements that can be directly verified from the KPIs
- Use exact values from the KPI table
- Avoid speculation or unsupported conclusions
- Be precise with numbers and comparisons
```

**Factory Function**:
```python
def create_feedback_loop(
    config: Optional[ValidationConfig] = None
) -> FeedbackLoop
```
**Purpose**: Factory function to create a configured `FeedbackLoop` instance.

---

### `monitoring.py` (193 lines) ⭐ **METRICS & MONITORING**
**Purpose**: Tracks validation performance, logs results, and generates alerts

**Classes**:

#### `ValidationMetrics` (Dataclass)
```python
@dataclass
class ValidationMetrics:
    total_validations: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    
    total_statements: int = 0
    total_contradictions: int = 0
    
    avg_confidence: float = 0.0
    avg_pass_rate: float = 0.0
    
    feedback_loop_triggers: int = 0
    avg_iterations_to_success: float = 0.0
    
    @property
    def overall_pass_rate(self) -> float: ...
    def to_dict(self) -> Dict[str, Any]: ...
```
**Purpose**: Aggregated metrics across multiple validations.

#### `ValidationMonitor` (Main Class)
```python
class ValidationMonitor:
    def __init__(self, config: Optional[ValidationConfig] = None)
    def record_validation(self, report: ValidationReport)
    def get_metrics(self) -> ValidationMetrics
    def get_summary(self) -> Dict[str, Any]
    def export_metrics(self, output_path: Path)
```

**Methods**:

##### `record_validation()` ⭐ **RECORD VALIDATION RESULT**
**Purpose**: Record a validation result and update aggregated metrics.

**Actions**:
- Update counters (pass/warning/fail)
- Update running averages (confidence, pass rate)
- Track feedback loop iterations
- Log result
- Check for alerts
- Save report if configured

##### `_check_alerts()` ⭐ **ALERT DETECTION**
**Purpose**: Check if validation result triggers any alerts.

**Alert Conditions**:
1. **Contradictions**: Warns on any contradictions detected
2. **Low Confidence**: Warns if confidence < `min_confidence`
3. **Max Iterations**: Warns if feedback loop reached max iterations

##### `_save_report()` ⭐ **REPORT PERSISTENCE**
**Purpose**: Save validation report to disk (JSON format).

**Location**: `{report_dir}/{cluster_id}/validation_{timestamp}.json`

##### `get_metrics()` / `get_summary()` / `export_metrics()`
**Purpose**: Access aggregated metrics and export to JSON.

---

### `config.py` (48 lines) ⭐ **CONFIGURATION**
**Purpose**: Configuration dataclass for validation system

**Classes**:

#### `ValidationConfig` (Dataclass)
```python
@dataclass
class ValidationConfig:
    # Model settings
    model_name: str = "google/tapas-large-finetuned-tabfact"
    use_cpu: bool = False
    model_cache_dir: Optional[Path] = None
    
    # Validation thresholds
    min_confidence: float = 0.7              # Minimum confidence for entailment
    contradiction_threshold: float = 0.5     # Above this = contradiction
    
    # Feedback loop settings
    max_iterations: int = 3                  # Max re-generation attempts
    enable_feedback: bool = True             # Enable automatic re-generation
    
    # Monitoring and logging
    log_level: str = "INFO"
    save_reports: bool = True
    report_dir: Path = Path("results/validation")
    
    # Performance
    batch_size: int = 8                      # For batch validation
    max_sequence_length: int = 512           # Token limit
```

**Configuration Options**:

| Option | Default | Description |
|--------|---------|-------------|
| `min_confidence` | 0.7 | Minimum confidence for entailment (0.0-1.0) |
| `contradiction_threshold` | 0.5 | Above this confidence = contradiction |
| `max_iterations` | 3 | Maximum feedback loop iterations |
| `enable_feedback` | True | Enable automatic regeneration |
| `save_reports` | True | Save validation reports to disk |
| `report_dir` | `results/validation` | Directory for saved reports |
| `log_level` | "INFO" | Logging level (DEBUG/INFO/WARNING/ERROR) |

**Factory Function**:
```python
def get_default_config() -> ValidationConfig
```
**Purpose**: Get default validation configuration.

---

### `integration_example.py` (190 lines) ⭐ **INTEGRATION EXAMPLES**
**Purpose**: Example integration code demonstrating how to use the validation system

**Functions**:

#### `validate_decision_explanation()`
```python
def validate_decision_explanation(
    cluster_id: str,
    kpis: Dict[str, Any],
    explanation: str,
    validation_config: Optional[ValidationConfig] = None,
    enable_feedback: bool = True
) -> tuple[str, Dict[str, Any]]
```
**Purpose**: Validate and potentially refine an LLM-generated decision explanation.

**Usage Example**:
```python
final_explanation, report_dict = validate_decision_explanation(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    kpis={"lcoh_dh_median": 75.2, "lcoh_hp_median": 82.5, "choice": "DH"},
    explanation="DH is recommended because it's cheaper.",
    enable_feedback=True
)
```

#### `make_decision_with_validation()`
```python
def make_decision_with_validation(
    cluster_id: str,
    results_dir: Path = Path("results"),
    validate_explanation: bool = True
) -> Dict[str, Any]
```
**Purpose**: Run decision pipeline with optional TNLI validation.

**Workflow**:
1. Build KPI contract
2. Make deterministic decision
3. Validate LLM explanation (if available and enabled)
4. Save decision with validation report

**CLI Usage**:
```bash
python integration_example.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE
python integration_example.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --no-validation
```

---

### `INTEGRATION_GUIDE.md` (340 lines) ⭐ **INTEGRATION DOCUMENTATION**
**Purpose**: Comprehensive integration guide for using the TNLI Logic Auditor

**Sections**:
1. **Installation & Setup**: Dependencies, environment configuration
2. **Quick Start**: Basic usage examples
3. **Integration with Existing System**: UHDC, Decision Pipeline, Streamlit UI
4. **Configuration Options**: Environment variables and config
5. **Testing**: Unit test examples
6. **Troubleshooting**: Common issues and solutions
7. **Quick Reference**: API summary

---

## Validation Process Flow

### 1. Deterministic Validation (Primary Path)

```
Reason Codes → Structured Claims → Claim Validator → Validation Report
```

**Advantages**:
- 100% deterministic (no AI involved)
- Fast execution
- High reliability
- Auditable

**When Used**:
- Decision results have `reason_codes`
- Structured explanation format available
- Deterministic validation preferred

### 2. Semantic Validation (Fallback Path)

```
Free Text → Statement Parser → Rule Validator → LLM Validator → Validation Report
```

**Workflow**:
1. Parse rationale into individual statements
2. Try rule-based validation first (deterministic)
3. If NEUTRAL and LLM available, use LLM
4. Aggregate results

**Advantages**:
- Works with free-text explanations
- Handles complex semantic relationships
- Fallback to rules if LLM unavailable

### 3. Feedback Loop (Optional)

```
Initial Rationale → Validation → Contradictions? → Enriched Context → Regenerate → Re-validate
```

**When Enabled**:
- `enable_feedback=True` in config
- `regenerate_fn` provided
- Contradictions detected

**Stopping Conditions**:
- No contradictions found
- Max iterations reached
- Rationale unchanged
- Exception in regeneration

---

## Scoring & Reporting

### Validation Metrics

**Statement-Level Metrics**:
- **Verified Count**: Number of ENTAILED statements
- **Unverified Count**: Number of NEUTRAL statements
- **Contradiction Count**: Number of CONTRADICTION statements

**Aggregate Metrics**:
- **Verified Rate**: `verified_count / statements_validated`
- **Unverified Rate**: `unverified_count / statements_validated`
- **Contradiction Rate**: `contradiction_count / statements_validated`

### Status Determination

**FAIL**: Any contradictions detected
- `contradiction_count > 0`

**WARNING**: Low confidence or many unverified statements
- `unverified_count > statements_validated * 0.5` OR
- `warnings` list non-empty

**PASS**: High verification and no contradictions
- `verified_count / statements_validated >= 0.5` AND
- `contradiction_count == 0` AND
- No warnings

### Validation Report Structure

```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "timestamp": "2026-01-19T12:00:00",
  "validation_status": "pass",
  "overall_confidence": 0.85,
  "statements_validated": 5,
  "verified_count": 4,
  "unverified_count": 1,
  "contradiction_count": 0,
  "verified_rate": 0.8,
  "unverified_rate": 0.2,
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

## Key Features & Recent Updates

### 1. **Hybrid Validation Approach**
- Deterministic validation for structured claims (fast, reliable)
- Semantic validation for free-text (flexible, handles complexity)
- Automatic fallback from LLM to rules if LLM unavailable

### 2. **Structured Claims System (Edit A)**
- Convert reason codes to verifiable claims
- 100% deterministic validation
- Supports: LCOH comparisons, CO2 comparisons, robustness checks, feasibility checks

### 3. **Enhanced Rule Engine (Edit B)**
- Comprehensive rule-based validation covering common cases
- Handles: choice validation, feasibility claims, robustness claims, cost comparisons, CO2 comparisons
- Configurable model name via `GEMINI_MODEL` env var

### 4. **Proper Scoring Semantics (Edit C)**
- Verified = ENTAILED (supported by data)
- Unverified = NEUTRAL (cannot be proven)
- Contradiction = CONTRADICTED (proven false)
- Status determined by contradiction presence (not just low verification)

### 5. **Feedback Loop (Edit D)**
- Automatic regeneration when contradictions detected
- Enriched context with KPIs and contradiction details
- Iterative refinement up to max iterations
- Configurable via `enable_feedback` and `max_iterations`

### 6. **Monitoring & Metrics**
- Aggregated metrics across multiple validations
- Alert detection for contradictions, low confidence, max iterations
- Report persistence to disk (JSON format)
- Performance tracking

---

## Usage Examples

### Basic Validation

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

explanation = "The recommended choice is District Heating. DH is cheaper with LCOH of 75.2 EUR/MWh."

report = auditor.validate_rationale(kpis, explanation, "ST010")

print(f"Status: {report.validation_status}")
print(f"Verified: {report.verified_rate:.1%}")
print(f"Contradictions: {len(report.contradictions)}")
```

### With Feedback Loop

```python
from branitz_heat_decision.validation import create_feedback_loop

feedback_loop = create_feedback_loop()

def regenerate(kpis, context):
    # Call your LLM with enriched context
    return llm.generate_explanation(kpis, context)

final_explanation, report = feedback_loop.validate_with_feedback(
    kpis=kpis,
    initial_rationale=explanation,
    regenerate_fn=regenerate,
    cluster_id="ST010"
)
```

### Structured Claims Validation

```python
from branitz_heat_decision.validation import LogicAuditor, StructuredExplanation, Claim, ClaimType, Operator

auditor = LogicAuditor()

structured = StructuredExplanation(
    choice="DH",
    claims=[
        Claim(
            claim_type=ClaimType.LCOH_COMPARE,
            lhs="lcoh_dh_median",
            op=Operator.LT,
            rhs="lcoh_hp_median",
            description="DH has lower LCOH than HP"
        )
    ],
    rationale_text="DH is recommended because it has lower costs."
)

report = auditor.validate_structured_claims(kpis, structured, "ST010")
```

### Decision Pipeline Integration

```python
decision_data = {
    "cluster_id": "ST010",
    "choice": "DH",
    "reason_codes": ["COST_DOMINANT_DH", "ROBUST_DECISION"],
    "metrics_used": {
        "lcoh_dh_median": 75.2,
        "lcoh_hp_median": 82.5,
        "dh_wins_fraction": 0.78
    },
    "explanation": "DH is recommended because it's cheaper."
}

report = auditor.validate_decision_explanation(decision_data)
```

---

## Integration with Other Modules

### Decision Module
- Validates LLM-generated explanations
- Checks reason codes against KPI data
- Ensures choice matches feasibility and cost data

### UHDC Module
- Validates explanations before including in reports
- Adds validation status to reports
- Flags contradictions for review

### UI Module
- Displays validation status in Compare & Decide tab
- Shows contradiction details
- Highlights unverified statements

---

## File Dependencies

### Internal Dependencies
```
logic_auditor.py
  ├─→ uses TNLIModel (tnli_model.py)
  ├─→ uses ValidationConfig (config.py)
  └─→ uses ClaimValidator (claims.py)

feedback_loop.py
  ├─→ uses LogicAuditor (logic_auditor.py)
  └─→ uses ValidationConfig (config.py)

monitoring.py
  ├─→ uses ValidationReport (logic_auditor.py)
  └─→ uses ValidationConfig (config.py)

claims.py
  └─→ (standalone, no internal dependencies)

tnli_model.py
  └─→ (standalone, uses google-generativeai)
```

### External Dependencies
- **google-generativeai**: LLM API client (optional, with fallback)
- **python-dotenv**: Environment variable loading (optional)
- **dataclasses**: Data structure definitions
- **logging**: Logging framework
- **pathlib**: Path handling

---

## Environment Configuration

**Required (Optional)**:
```bash
# For LLM-based validation (optional, falls back to rules if not set)
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here  # Alternative name

# Optional: Model selection
GEMINI_MODEL=gemini-1.5-flash  # or gemini-1.5-pro
```

**Loading Environment**:
- Automatically loads `.env` via `bootstrap_env()` from `ui.env`
- Falls back to `python-dotenv` if bootstrap unavailable
- Gracefully handles missing API key (uses rule-based validation)

---

## Performance Considerations

### Deterministic Validation
- **Speed**: Very fast (<1ms per claim)
- **Reliability**: 100% deterministic
- **Use When**: Structured data available, maximum reliability needed

### LLM-Based Validation
- **Speed**: Moderate (100-500ms per statement, API dependent)
- **Reliability**: High (with fallback to rules)
- **Use When**: Free-text explanations, complex semantic relationships

### Batch Processing
- Supports batch validation of multiple statements
- Uses `batch_size` config for efficient processing

---

## Troubleshooting

### Issue: "No GOOGLE_API_KEY found"
**Solution**: Ensure `.env` file is loaded via `bootstrap_env()` or `load_dotenv()`. Falls back to rule-based validation.

### Issue: "LLM validation failed"
**Solution**: Expected behavior - falls back to rules. Set `USE_LLM_VALIDATION=false` to force rule-based only.

### Issue: Validation too strict
**Solution**: Lower `min_confidence` threshold in `ValidationConfig`.

### Issue: Too many NEUTRAL results
**Solution**: Normal for statements not verifiable from KPIs. Consider using structured claims format for better verification.

---

## Testing

See `integration_example.py` for usage examples and test patterns.

**Unit Test Example**:
```python
def test_validation_pass():
    auditor = LogicAuditor()
    kpis = {"lcoh_dh_median": 75.0, "lcoh_hp_median": 82.0, "choice": "DH"}
    explanation = "DH is cheaper with LCOH of 75.0 EUR/MWh."
    
    report = auditor.validate_rationale(kpis, explanation, "test")
    
    assert report.validation_status == "pass"
    assert len(report.contradictions) == 0
```

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.0  
**Primary Maintainer**: Validation Module Development Team
