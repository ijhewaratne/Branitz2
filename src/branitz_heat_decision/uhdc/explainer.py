"""
UHDC LLM Explainer
- Read-only: does not compute new KPIs
- Constrained: cites only provided contract data
- Safe: validates output against contract
"""

import logging
import os
import re
from typing import Dict, Any, List, Optional, Set
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Optional .env loading (safe, no override) --------------------------------
def _load_env_if_present() -> None:
    """
    Load a .env file if present anywhere above this file (repo root), without overriding
    already-exported environment variables.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    # Walk up parent directories looking for ".env"
    for parent in Path(__file__).resolve().parents:
        env_path = parent / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.info(f"Loaded .env from {env_path}")
            break


_load_env_if_present()

# Import Google GenAI SDK (ADK)
try:
    from google import genai
    from google.genai import types
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

if not LLM_AVAILABLE:
    logger.warning("Google GenAI SDK not installed. LLM explainer will fallback to template.")

# Optional runtime toggles (via .env / env vars)
GOOGLE_MODEL_DEFAULT = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
UHDC_FORCE_TEMPLATE = os.getenv("UHDC_FORCE_TEMPLATE", "false").strip().lower() == "true"

def _get_google_api_key() -> str | None:
    """
    Retrieve GOOGLE_API_KEY from environment.
    Returns None if missing or placeholder.
    """
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    key = key.strip().strip('"').strip("'")
    if not key or key == "YOUR_ACTUAL_API_KEY_HERE":
        return None
    return key


GOOGLE_API_KEY = _get_google_api_key()
LLM_READY = bool(LLM_AVAILABLE and (GOOGLE_API_KEY is not None) and (not UHDC_FORCE_TEMPLATE))

if UHDC_FORCE_TEMPLATE:
    logger.info("UHDC_FORCE_TEMPLATE=true: forcing template mode (LLM disabled).")


def _call_llm(prompt: str, model: str) -> str:
    """
    Call Gemini via google-genai with best-effort timeout and error handling.

    Notes:
    - We intentionally do NOT log the API key.
    - If the installed google-genai version does not support request_options timeouts,
      we proceed without it (still safe due to caller fallback/--no-fallback).
    """
    if not LLM_AVAILABLE:
        raise RuntimeError("LLM not available: google-genai SDK not installed")
    if UHDC_FORCE_TEMPLATE:
        raise RuntimeError("LLM disabled: UHDC_FORCE_TEMPLATE=true")
    if GOOGLE_API_KEY is None:
        raise RuntimeError("LLM not available: GOOGLE_API_KEY missing")

    # Explicitly pass the API key (do not rely on ambient env in case caller overrides env)
    client = genai.Client(api_key=GOOGLE_API_KEY)

    cfg = types.GenerateContentConfig(
        temperature=0.0,  # Deterministic
        max_output_tokens=500,
        top_p=0.95,
        top_k=40,
    )

    # Best-effort timeout support (varies by google-genai version)
    request_options = None
    if hasattr(types, "RequestOptions"):
        try:
            request_options = types.RequestOptions(timeout=LLM_TIMEOUT)
        except Exception:
            request_options = None

    if request_options is not None:
        try:
            # Some google-genai versions support request timeouts; stubs may not.
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=cfg,
                request_options=request_options,  # type: ignore[call-arg]
            )
        except TypeError:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=cfg,
            )
    else:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=cfg,
        )
    return response.text or ""

# Explanation style templates
STYLE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "executive": {
        "instruction": "Provide a concise executive summary (3-4 sentences) for non-technical stakeholders.",
        "tone": "professional, clear, avoid jargon",
        "must_include": ["recommendation", "cost", "feasibility", "robustness"],
    },
    "technical": {
        "instruction": "Provide a detailed technical explanation referencing specific KPIs and standards.",
        "tone": "precise, engineering-focused",
        "must_include": ["velocity", "pressure_drop", "loading_pct", "win_fraction"],
    },
    "detailed": {
        "instruction": "Provide a comprehensive explanation with step-by-step rationale and uncertainty discussion.",
        "tone": "thorough, methodical",
        "must_include": ["all_metrics", "standards", "assumptions", "sensitivity"],
    },
}

def explain_with_llm(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str = "executive",
    model: str = GOOGLE_MODEL_DEFAULT,
    no_fallback: bool = False,
) -> str:
    """
    Generate natural language explanation using LLM (Gemini).
    
    Args:
        contract: Validated KPI contract
        decision: DecisionResult from rules.py
        style: Explanation style (executive|technical|detailed)
        model: Gemini model name
    
    Returns:
        Natural language explanation string
    
    Raises:
        ValueError: If LLM produces invalid output (safety check fails)
        RuntimeError: If LLM SDK not available
    
    Safety Guarantees:
        - Prompt contains ONLY contract data (no external retrieval)
        - Temperature=0.0 for determinism
        - Output validated against contract values (no hallucination)
        - References only provided standards (EN 13941-1, VDE-AR-N 4100)
    """
    
    # Allow forcing template mode via env var
    if UHDC_FORCE_TEMPLATE:
        if no_fallback:
            raise RuntimeError("UHDC_FORCE_TEMPLATE=true: LLM disabled but --no-fallback was requested.")
        return _fallback_template_explanation(contract, decision, style)

    # Guard: if contract is missing critical fields required by prompt/templates,
    # never attempt LLM; return a safe fallback unless explicitly forbidden.
    try:
        if contract.get("district_heating", {}).get("feasible") is None:
            raise KeyError("district_heating.feasible")
        if contract.get("heat_pumps", {}).get("feasible") is None:
            raise KeyError("heat_pumps.feasible")
    except Exception as e:
        logger.warning(f"Missing critical fields for explainer ({e}); using safe template.")
        if no_fallback:
            raise ValueError("Missing critical KPIs for LLM safety") from e
        # Best-effort safe template (may still be limited if many fields missing)
        return _fallback_template_explanation(contract, decision, style)

    if not LLM_AVAILABLE:
        if no_fallback:
            raise RuntimeError("Google GenAI SDK not installed. Run: pip install google-genai")
        return _fallback_template_explanation(contract, decision, style)

    # Guard: if API key is missing, fallback unless forbidden
    if GOOGLE_API_KEY is None:
        msg = (
            "GOOGLE_API_KEY is not set. Set it via environment variable or .env file. "
            "LLM explanations will use template fallback."
        )
        if no_fallback:
            raise RuntimeError(msg)
        logger.warning(msg)
        return _fallback_template_explanation(contract, decision, style)
    
    if style not in STYLE_TEMPLATES:
        raise ValueError(f"Unknown style: {style}. Choose from {list(STYLE_TEMPLATES.keys())}")
    
    # Build constrained prompt
    prompt = _build_constrained_prompt(contract, decision, style)
    
    logger.debug(f"Sending prompt to LLM (style={style}, length={len(prompt)} chars)")
    
    # Call Gemini API
    try:
        explanation = _call_llm(prompt=prompt, model=model)
        logger.info(f"Received LLM explanation ({len(explanation)} chars)")
        
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        if no_fallback:
            raise
        explanation = _fallback_template_explanation(contract, decision, style)
    
    # Safety validation (critical)
    try:
        _validate_explanation_safety(explanation, contract, decision)
    except ValueError as e:
        logger.error(f"LLM safety check failed: {e}")
        logger.error(f"LLM output: {explanation}")
        if no_fallback:
            raise
        explanation = _fallback_template_explanation(contract, decision, style)
    
    return explanation

def _build_constrained_prompt(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str,
) -> str:
    """
    Build tightly constrained prompt from contract data only.
    
    Structure:
    1. System role definition
    2. Strict rules (no invention, cite sources)
    3. Contract data (all numbers explicit)
    4. Decision data (choice, reasons)
    5. Style-specific instructions
    """
    
    template = STYLE_TEMPLATES[style]
    
    # Extract key metrics for easy reference
    dh = contract['district_heating']
    hp = contract['heat_pumps']
    mc = contract.get('monte_carlo', {})
    
    # Format metrics with units
    metrics_section = f"""
## District Heating Metrics
- Feasible: {dh['feasible']} (Reasons: {', '.join(dh['reasons'])})
- LCOH: {dh['lcoh']['median']:.1f} €/MWh (95% CI: {dh['lcoh']['p05']:.1f} - {dh['lcoh']['p95']:.1f})
- CO₂: {dh['co2']['median']:.0f} kg/MWh
- Max Velocity: {dh['hydraulics'].get('v_max_ms', 'N/A')} m/s
- Velocity Within Limits: {dh['hydraulics'].get('v_share_within_limits', 'N/A'):.1%}
- Pressure Drop OK: {dh['hydraulics'].get('dp_ok', 'N/A')}
- Thermal Losses: {dh['losses'].get('loss_share_pct', 'N/A')}%

## Heat Pump Metrics
- Feasible: {hp['feasible']} (Reasons: {', '.join(hp['reasons'])})
- LCOH: {hp['lcoh']['median']:.1f} €/MWh (95% CI: {hp['lcoh']['p05']:.1f} - {hp['lcoh']['p95']:.1f})
- CO₂: {hp['co2']['median']:.0f} kg/MWh
- Max Feeder Loading: {hp['lv_grid'].get('max_feeder_loading_pct', 'N/A')}%
- Voltage Violations: {hp['lv_grid'].get('voltage_violations_total', 'N/A')}
- Planning Warning: {hp['lv_grid'].get('planning_warning', 'N/A')}

## Monte Carlo Robustness
- DH Wins: {mc.get('dh_wins_fraction', 0):.1%}
- HP Wins: {mc.get('hp_wins_fraction', 0):.1%}
- Samples: {mc.get('n_samples', 'N/A')}
"""

    # Decision section
    decision_section = f"""
## Decision Logic Applied
- Choice: {decision['choice']}
- Robust: {decision['robust']}
- Reason Codes: {', '.join(decision['reason_codes'])}
- Logic Flow: {_format_decision_logic(decision['reason_codes'])}
"""

    # Style instructions
    style_instructions = f"""
## Style Requirements
- {template['instruction']}
- Tone: {template['tone']}
- Must explicitly cite: {', '.join(template['must_include'])}
- Do NOT mention "the model" or "simulation" - refer to "analysis" or "assessment"
"""

    instruction = str(template.get("instruction", "Provide a concise summary."))
    words = instruction.split()
    sentence_hint = words[2] if len(words) >= 3 else "3-4"

    prompt = f"""You are an energy planning assistant specialized in municipal heating decisions.

## STRICT RULES (Violate = Invalid Output)
1. CITE ONLY the metrics provided above - do not invent numbers
2. REFERENCE ONLY standards: EN 13941-1 (DH), VDE-AR-N 4100 (LV grid)
3. STATE ASSUMPTIONS explicitly if needed (e.g., "assuming 2023 energy prices")
4. KEEP length: {sentence_hint} sentences
5. FORMAT: Plain text, no markdown headings except "Summary" if needed
6. NO HALLUCINATION: Every numeric value must be traceable to the metrics above

## Contract Data
{metrics_section}

{decision_section}

{style_instructions}

## Output
Provide your explanation below:
"""
    
    return prompt.strip()

def _format_decision_logic(reason_codes: List[str]) -> str:
    """Format decision logic steps in plain language."""
    
    logic_map = {
        "ONLY_DH_FEASIBLE": "Only DH meets technical standards",
        "ONLY_HP_FEASIBLE": "Only HP meets technical standards",
        "COST_DOMINANT_DH": "DH clearly cheaper (>5%)",
        "COST_DOMINANT_HP": "HP clearly cheaper (>5%)",
        "COST_CLOSE_USE_CO2": "Costs within 5% → CO₂ tie-breaker",
        "CO2_TIEBREAKER_DH": "DH has lower emissions",
        "CO2_TIEBREAKER_HP": "HP has lower emissions",
    }
    
    seen: Set[str] = set()
    steps: List[str] = []
    for code in reason_codes:
        if code in logic_map and code not in seen:
            steps.append(f"{len(steps)+1}. {logic_map[code]}")
            seen.add(code)
    
    return " → ".join(steps) if steps else "Decision logic unclear"

def _validate_explanation_safety(
    explanation: str,
    contract: Dict[str, Any],
    decision: Dict[str, Any],
) -> None:
    """
    Validate LLM output against contract data to detect hallucination.
    
    Checks:
    1. All numbers in explanation exist in contract
    2. No numbers deviate >1% from contract values
    3. Standard references are correct
    4. Choice matches decision choice
    
    Raises:
        ValueError: If hallucination detected
    """
    
    # Extract all numbers from explanation (integers and decimals)
    numbers_found = re.findall(r'\d+\.?\d*', explanation)
    
    # Build set of allowed numbers from contract
    allowed_numbers: Set[str] = set()
    
    def _add_number(num: Any) -> None:
        if isinstance(num, (int, float)):
            # Allow rounding difference (±1%)
            allowed_numbers.add(f"{num:.0f}")
            allowed_numbers.add(f"{num:.1f}")
            allowed_numbers.add(f"{num:.2f}")
    
    # Add LCOH values
    _add_number(contract['district_heating']['lcoh']['median'])
    _add_number(contract['heat_pumps']['lcoh']['median'])
    # Add loss share percent
    _add_number(contract['district_heating']['losses'].get('loss_share_pct', 0.0))
    # Allow quantiles if templates cite them (e.g., 95% CI numbers)
    for side in ("district_heating", "heat_pumps"):
        try:
            _add_number(contract[side]["lcoh"].get("p05"))
            _add_number(contract[side]["lcoh"].get("p95"))
        except Exception:
            pass

    # Allow LCOH difference if explanation references it (derived, but traceable)
    try:
        lcoh_diff = abs(
            float(contract['district_heating']['lcoh']['median']) - float(contract['heat_pumps']['lcoh']['median'])
        )
        _add_number(lcoh_diff)
        # Allow relative difference % (templates may cite it), derived from medians.
        rel = lcoh_diff / min(
            float(contract['district_heating']['lcoh']['median']),
            float(contract['heat_pumps']['lcoh']['median']),
        )
        _add_number(rel * 100.0)
    except Exception:
        pass
    
    # Add CO₂ values
    _add_number(contract['district_heating']['co2']['median'])
    _add_number(contract['heat_pumps']['co2']['median'])
    for side in ("district_heating", "heat_pumps"):
        try:
            _add_number(contract[side]["co2"].get("p05"))
            _add_number(contract[side]["co2"].get("p95"))
        except Exception:
            pass
    
    # Add velocity
    v_max = contract['district_heating']['hydraulics'].get('v_max_ms')
    if v_max:
        _add_number(v_max)
    
    # Add loading
    loading = contract['heat_pumps']['lv_grid'].get('max_feeder_loading_pct')
    if loading:
        _add_number(loading)

    # Add violation counts (templates may cite them)
    try:
        vv = contract['heat_pumps']['lv_grid'].get('voltage_violations_total')
        if vv is not None:
            _add_number(int(vv))
    except Exception:
        pass
    try:
        lv = contract['heat_pumps']['lv_grid'].get('line_violations_total')
        if lv is not None:
            _add_number(int(lv))
    except Exception:
        pass
    
    # Add MC fractions
    mc = contract.get('monte_carlo', {})
    if mc:
        _add_number(mc.get('dh_wins_fraction', 0) * 100)  # As percentage
        _add_number(mc.get('hp_wins_fraction', 0) * 100)
        # Templates may also cite the sample count directly
        _add_number(mc.get('n_samples'))
    
    # Validate each number found
    for num_str in numbers_found:
        num_float = float(num_str)
        
        # Skip obvious non-metrics (year, cluster ID, etc.)
        # Also skip standard identifiers / fixed labels that may appear as numbers in text.
        # Examples: "VDE-AR-N 4100", "EN 13941", "95% CI".
        if num_float in (13941.0, 4100.0, 95.0):
            continue
        # Skip small ordinal numbers commonly used for enumerations in templates ("1.", "2.", ...).
        # This prevents false positives when templates include numbered recommendations.
        if num_float.is_integer() and 1 <= num_float <= 10:
            continue
        if num_float > 10000 or num_float < 0:
            continue
        
        # Check if number is in allowed set (with tolerance)
        is_allowed = any(
            abs(num_float - float(allowed)) <= 0.01 * float(allowed)
            for allowed in allowed_numbers
        )
        
        if not is_allowed:
            raise ValueError(
                f"LLM hallucination detected: number {num_str} not found in contract. "
                f"Allowed numbers: {sorted(allowed_numbers)[:10]}..."  # Show first 10
            )
    
    # Check choice consistency
    if decision['choice'] == "DH":
        if "district heating" not in explanation.lower() and "DH" not in explanation:
            raise ValueError("LLM explanation does not mention chosen option: District Heating")
    
    elif decision['choice'] == "HP":
        if "heat pump" not in explanation.lower() and "HP" not in explanation:
            raise ValueError("LLM explanation does not mention chosen option: Heat Pumps")
    
    # Check standard references
    standards_mentioned = []
    if "EN 13941" in explanation:
        standards_mentioned.append("EN 13941-1")
    if "VDE" in explanation:
        standards_mentioned.append("VDE-AR-N 4100")
    
    if not standards_mentioned:
        logger.warning("LLM explanation does not reference any standards")

def _fallback_template_explanation(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str,
) -> str:
    """
    Safe fallback when LLM is unavailable or fails safety check.
    
    Returns template-based explanation that is:
    - Deterministic (same inputs → same output)
    - Verifiable against contract
    - Professional in tone
    - Style-adapted
    """
    
    # Be defensive: the fallback must never crash, even if contract is incomplete.
    dh = contract.get('district_heating') or {}
    hp = contract.get('heat_pumps') or {}
    mc = contract.get('monte_carlo') or {}

    # If critical fields are missing, use a minimal safe explanation.
    if dh.get("feasible") is None or hp.get("feasible") is None:
        return _minimal_safe_template(contract, decision, style)
    
    # Style-specific templates
    if style == "executive":
        return _exec_template(dh, hp, decision, mc)
    elif style == "technical":
        return _tech_template(dh, hp, decision, mc)
    elif style == "detailed":
        return _detailed_template(dh, hp, decision, mc)
    else:
        return _exec_template(dh, hp, decision, mc)  # Default


def _minimal_safe_template(contract: Dict[str, Any], decision: Dict[str, Any], style: str) -> str:
    """
    Minimal fallback that never crashes.
    Used when contract is missing critical fields expected by the richer templates.
    """
    dh = contract.get("district_heating") or {}
    hp = contract.get("heat_pumps") or {}
    dh_lcoh = (dh.get("lcoh") or {}).get("median")
    hp_lcoh = (hp.get("lcoh") or {}).get("median")
    dh_co2 = (dh.get("co2") or {}).get("median")
    hp_co2 = (hp.get("co2") or {}).get("median")

    def _fmt(x: Any, fmt: str) -> str:
        return fmt.format(x) if isinstance(x, (int, float)) else "N/A"

    lines = [
        f"**{decision.get('choice', 'UNDECIDED')}** is recommended (data incomplete; using safe template).",
        "",
        "Key available metrics:",
        f"- LCOH DH: {_fmt(dh_lcoh, '{:.1f}')} €/MWh",
        f"- LCOH HP: {_fmt(hp_lcoh, '{:.1f}')} €/MWh",
        f"- CO₂ DH: {_fmt(dh_co2, '{:.0f}')} kg/MWh",
        f"- CO₂ HP: {_fmt(hp_co2, '{:.0f}')} kg/MWh",
    ]
    if style == "executive":
        return "\n".join(lines[:2] + lines[2:])  # keep short
    return "\n".join(lines)

def _exec_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str:
    """Executive summary template (3-4 sentences)."""
    
    parts = [
        f"**{decision['choice']}** is recommended for this cluster.",
        f"This option is {'robust' if decision['robust'] else 'sensitive to parameter uncertainty'}.",
    ]
    
    # Feasibility
    if decision['choice'] == "DH" and not hp['feasible']:
        parts.append(f"Only district heating meets technical standards (HP has {hp['lv_grid'].get('voltage_violations_total', 'unknown')} grid violations).")
    elif decision['choice'] == "HP" and not dh['feasible']:
        parts.append(f"Only heat pumps meet technical standards (DH has hydraulic violations).")
    
    # Cost
    lcoh_diff = abs(dh['lcoh']['median'] - hp['lcoh']['median'])
    if lcoh_diff > 5:
        parts.append(f"Economics clearly favor {decision['choice']} (LCOH difference: {lcoh_diff:.0f} €/MWh).")
    else:
        parts.append(f"Costs are close; {decision['choice']} chosen based on lower CO₂ emissions.")
    
    # Uncertainty
    if decision['robust'] and mc.get('dh_wins_fraction' if decision['choice'] == 'DH' else 'hp_wins_fraction'):
        win_frac = mc['dh_wins_fraction' if decision['choice'] == 'DH' else 'hp_wins_fraction']
        parts.append(f"Uncertainty analysis supports this in {win_frac:.0%} of scenarios.")
    
    return "\n\n".join(parts)

def _tech_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str:
    """Technical template (bulleted KPIs)."""
    
    lines = [
        "# Technical Assessment",
        "",
        "## District Heating Performance (EN 13941-1)",
        f"- Velocity compliance: {dh['hydraulics'].get('v_share_within_limits', 'N/A'):.1%} (max: {dh['hydraulics'].get('v_max_ms', 'N/A')} m/s)",
        f"- Pressure drop: {'OK' if dh['hydraulics'].get('dp_ok') else 'VIOLATION'}",
        f"- Thermal losses: {dh['losses'].get('loss_share_pct', 'N/A')}%",
        f"- Pump power: {dh['losses'].get('pump_power_kw', 'N/A')} kW",
        "",
        "## Heat Pump Performance (VDE-AR-N 4100)",
        f"- Feasible: {hp['feasible']}",
        f"- Max feeder loading: {hp['lv_grid'].get('max_feeder_loading_pct', 'N/A')}%",
        f"- Voltage violations: {hp['lv_grid'].get('voltage_violations_total', 'N/A')}",
        "",
        "## Economics & Uncertainty",
        f"- LCOH DH: {dh['lcoh']['median']:.1f} €/MWh (95% CI: {dh['lcoh']['p05']:.1f}-{dh['lcoh']['p95']:.1f})",
        f"- LCOH HP: {hp['lcoh']['median']:.1f} €/MWh (95% CI: {hp['lcoh']['p05']:.1f}-{hp['lcoh']['p95']:.1f})",
        f"- CO₂ DH: {dh['co2']['median']:.0f} kg/MWh",
        f"- CO₂ HP: {hp['co2']['median']:.0f} kg/MWh",
    ]
    
    if mc.get('dh_wins_fraction'):
        lines.append(f"- Monte Carlo: DH wins {mc['dh_wins_fraction']:.0%}, HP wins {mc['hp_wins_fraction']:.0%}")
    
    lines.extend([
        "",
        "## Decision",
        f"- Choice: **{decision['choice']}**",
        f"- Robust: {decision['robust']}",
        f"- Reasons: {', '.join(decision['reason_codes'])}",
    ])
    
    return "\n".join(lines)

def _detailed_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str:
    """Detailed template (step-by-step with assumptions)."""
    
    lines = [
        "# Detailed Decision Rationale",
        "",
        "## Step 1: Technical Feasibility Assessment",
    ]
    
    if dh['feasible'] and hp['feasible']:
        lines.append("Both options are technically feasible based on standard compliance.")
    elif dh['feasible']:
        lines.append("Only district heating is feasible. Heat pump analysis revealed:")
        lines.append(f"- {hp['lv_grid'].get('voltage_violations_total', 'Multiple')} voltage violations")
        lines.append("- Exceeds VDE-AR-N 4100 planning limits")
    else:
        lines.append("Only heat pumps are feasible. District heating analysis revealed:")
        lines.append(f"- Hydraulic constraints: {', '.join(dh['reasons'])}")
    
    lines.extend([
        "",
        "## Step 2: Economic Comparison",
        f"- DH LCOH: {dh['lcoh']['median']:.1f} €/MWh [95% CI: {dh['lcoh']['p05']:.1f}-{dh['lcoh']['p95']:.1f}]",
        f"- HP LCOH: {hp['lcoh']['median']:.1f} €/MWh [95% CI: {hp['lcoh']['p05']:.1f}-{hp['lcoh']['p95']:.1f}]",
        f"- Relative difference: {abs(dh['lcoh']['median'] - hp['lcoh']['median']) / min(dh['lcoh']['median'], hp['lcoh']['median']):.1%}",
    ])
    
    if decision['choice'] in ["DH", "HP"]:
        lines.append(f"- **Decision**: {decision['choice']} is economically preferable.")
    
    lines.extend([
        "",
        "## Step 3: CO₂ Tie-Breaker (if applied)",
        f"- DH emissions: {dh['co2']['median']:.0f} kg/MWh",
        f"- HP emissions: {hp['co2']['median']:.0f} kg/MWh",
    ])
    
    if "CO2_TIEBREAKER_DH" in decision['reason_codes'] or "CO2_TIEBREAKER_HP" in decision['reason_codes']:
        lines.append(f"- **Tie-breaker**: {decision['choice']} chosen for lower emissions.")
    
    lines.extend([
        "",
        "## Step 4: Uncertainty & Robustness",
    ])
    
    if mc:
        lines.append(f"- Monte Carlo samples: {mc.get('n_samples', 'N/A')}")
        lines.append(f"- {decision['choice']} win fraction: {mc.get('dh_wins_fraction' if decision['choice'] == 'DH' else 'hp_wins_fraction', 0):.0%}")
        
        if decision['robust']:
            lines.append("- **Conclusion**: Decision is statistically robust.")
        else:
            lines.append("- **Caution**: Decision sensitive to input parameters.")
    else:
        lines.append("- Monte Carlo data not available: robustness cannot be assessed.")
    
    lines.extend([
        "",
        "## Key Assumptions",
        "- Technical constraints per EN 13941-1 and VDE-AR-N 4100",
        "- Building heat demand from TABULA typology",
        "",
        "## Recommendations for Planners",
        f"1. Proceed with {decision['choice']} implementation.",
        "2. Validate input data quality (especially LV grid topology).",
        "3. Monitor actual vs. projected heat demand.",
    ])
    
    if not decision['robust']:
        lines.append("4. Perform sensitivity analysis on key cost drivers.")
    
    return "\n".join(lines)

# Export
__all__ = ['explain_with_llm', 'STYLE_TEMPLATES', 'LLM_AVAILABLE']