"""
Lightweight validation using LLM API or rule-based approach.

Edit B: Enhanced rule support for real decision claims
Edit C: Fixed scoring semantics (verified/unverified/contradiction)

No large model download required - uses Gemini API from .env.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class EntailmentLabel(str, Enum):
    ENTAILMENT = "Entailment"
    NEUTRAL = "Neutral"
    CONTRADICTION = "Contradiction"


@dataclass
class LightweightResult:
    """Result from lightweight validation."""
    statement: str
    label: EntailmentLabel
    confidence: float
    reason: str = ""
    
    @property
    def is_valid(self) -> bool:
        return self.label == EntailmentLabel.ENTAILMENT
    
    @property
    def is_contradiction(self) -> bool:
        return self.label == EntailmentLabel.CONTRADICTION
    
    @property
    def is_neutral(self) -> bool:
        return self.label == EntailmentLabel.NEUTRAL


class LightweightValidator:
    """
    Lightweight validator that works without downloading large models.
    
    Options:
    1. Rule-based: Deterministic verification against KPIs
    2. LLM-based: Uses Gemini API for semantic validation
    """
    
    def __init__(self, use_llm: bool = True):
        """
        Initialize validator.
        
        Args:
            use_llm: If True, try to use Gemini API. If False or unavailable, use rules.
        """
        self.use_llm = use_llm
        self.llm_client = None
        
        if use_llm:
            self._init_llm()
    
    def _init_llm(self):
        """
        Try to initialize LLM client using API key from .env file.
        
        Issue B Fix: Model name configurable via GEMINI_MODEL env var.
        """
        try:
            import os
            
            # Load .env file using bootstrap utility
            try:
                from branitz_heat_decision.ui.env import bootstrap_env
                bootstrap_env()
            except ImportError:
                try:
                    from dotenv import load_dotenv
                    load_dotenv()
                except ImportError:
                    pass
            
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            
            # Issue B: Make model configurable
            model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
            
            if api_key:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self.llm_client = genai.GenerativeModel(model_name)
                logger.info(f"✅ LLM validation enabled (model: {model_name})")
            else:
                logger.warning("No GOOGLE_API_KEY found in .env, using rule-based validation only")
        except ImportError as e:
            logger.warning(f"Missing package: {e}, using rule-based validation")
        except Exception as e:
            logger.warning(f"Failed to init LLM: {e}, using rule-based validation")
    
    def validate_statement(
        self,
        kpis: Dict[str, Any],
        statement: str
    ) -> LightweightResult:
        """
        Validate a single statement against KPIs.
        
        First attempts rule-based validation.
        Falls back to LLM if rules don't apply.
        """
        # First try rule-based (deterministic)
        rule_result = self._validate_with_rules(kpis, statement)
        
        # If rules gave a definitive answer (not neutral), return it
        if rule_result.label != EntailmentLabel.NEUTRAL:
            return rule_result
        
        # If neutral and LLM available, try LLM
        if self.llm_client:
            return self._validate_with_llm(kpis, statement)
        
        return rule_result
    
    def _validate_with_llm(
        self,
        kpis: Dict[str, Any],
        statement: str
    ) -> LightweightResult:
        """
        Validate using LLM API.
        
        Issue B Fix: Disables client on exception to prevent repeated failures.
        """
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
            # Issue B Fix: Disable client on exception to prevent repeated failures
            logger.warning(f"LLM validation failed: {e}. Disabling LLM for remaining validations.")
            self.llm_client = None  # Fail closed - use rules for rest of run
            return LightweightResult(statement, EntailmentLabel.NEUTRAL, 0.5, 
                "LLM unavailable, falling back to rules")
    
    def _validate_with_rules(
        self,
        kpis: Dict[str, Any],
        statement: str
    ) -> LightweightResult:
        """
        Enhanced rule-based validation (Edit B).
        
        Covers:
        - LCOH comparisons (cheaper, lower cost)
        - CO2 comparisons (lower emissions)
        - Recommended choice validation
        - Feasibility claims (ONLY_DH_FEASIBLE, ONLY_HP_FEASIBLE)
        - Robustness claims (ROBUST_DECISION, win fraction)
        - Specific numerical values
        """
        statement_lower = statement.lower()
        
        # Get KPI values with fallbacks
        lcoh_dh = self._get_kpi(kpis, ["lcoh_dh_median", "lcoh_dh"])
        lcoh_hp = self._get_kpi(kpis, ["lcoh_hp_median", "lcoh_hp"])
        co2_dh = self._get_kpi(kpis, ["co2_dh_median", "co2_dh"])
        co2_hp = self._get_kpi(kpis, ["co2_hp_median", "co2_hp"])
        dh_wins = self._get_kpi(kpis, ["dh_wins_fraction", "dh_win_fraction"])
        hp_wins = self._get_kpi(kpis, ["hp_wins_fraction", "hp_win_fraction"])
        dh_feasible = self._get_kpi(kpis, ["dh_feasible", "cha_feasible"])
        hp_feasible = self._get_kpi(kpis, ["hp_feasible", "dha_feasible"])
        choice = str(kpis.get("choice", kpis.get("recommendation", ""))).upper()
        
        # --- EDIT B: Enhanced rule support ---
        
        # 1. RECOMMENDED CHOICE VALIDATION
        if "recommended" in statement_lower and "choice" in statement_lower:
            if "dh" in statement_lower or "district" in statement_lower:
                if choice == "DH":
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
                        f"Recommended choice is DH (verified)")
                elif choice:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
                        f"Recommended choice is {choice}, not DH")
            elif "hp" in statement_lower or "heat pump" in statement_lower:
                if choice == "HP":
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
                        f"Recommended choice is HP (verified)")
                elif choice:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
                        f"Recommended choice is {choice}, not HP")
        
        # 2. FEASIBILITY CLAIMS
        if "only_dh_feasible" in statement_lower or "only dh feasible" in statement_lower:
            if dh_feasible is True and hp_feasible is False:
                return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
                    "DH feasible=True, HP feasible=False")
            elif dh_feasible is not None and hp_feasible is not None:
                return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
                    f"DH feasible={dh_feasible}, HP feasible={hp_feasible}")
        
        if "only_hp_feasible" in statement_lower or "only hp feasible" in statement_lower:
            if hp_feasible is True and dh_feasible is False:
                return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.95,
                    "HP feasible=True, DH feasible=False")
            elif dh_feasible is not None and hp_feasible is not None:
                return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.95,
                    f"DH feasible={dh_feasible}, HP feasible={hp_feasible}")
        
        # 3. ROBUSTNESS CLAIMS
        if "robust" in statement_lower:
            if dh_wins is not None and dh_wins >= 0.7 and ("dh" in statement_lower or choice == "DH"):
                return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                    f"DH win fraction = {dh_wins:.1%} ≥ 70%")
            elif hp_wins is not None and hp_wins >= 0.7 and ("hp" in statement_lower or choice == "HP"):
                return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                    f"HP win fraction = {hp_wins:.1%} ≥ 70%")
            elif dh_wins is not None and hp_wins is not None:
                winner_fraction = dh_wins if choice == "DH" else hp_wins
                if winner_fraction < 0.7:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.85,
                        f"Win fraction = {winner_fraction:.1%} < 70% (not robust)")
        
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
            
            if is_hp_ref and lcoh_dh is not None and lcoh_hp is not None:
                if lcoh_hp < lcoh_dh:
                    diff = lcoh_dh - lcoh_hp
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                        f"HP LCOH ({lcoh_hp:.1f}) < DH LCOH ({lcoh_dh:.1f}), diff={diff:.1f}")
                else:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.9,
                        f"HP LCOH ({lcoh_hp:.1f}) ≥ DH LCOH ({lcoh_dh:.1f})")
        
        # 5. CO2 COMPARISONS
        if "lower co2" in statement_lower or "lower emission" in statement_lower or "co2 tiebreaker" in statement_lower:
            if is_dh_ref and co2_dh is not None and co2_hp is not None:
                if co2_dh < co2_hp:
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                        f"DH CO2 ({co2_dh:.1f}) < HP CO2 ({co2_hp:.1f})")
                else:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.9,
                        f"DH CO2 ({co2_dh:.1f}) ≥ HP CO2 ({co2_hp:.1f})")
            
            if is_hp_ref and co2_dh is not None and co2_hp is not None:
                if co2_hp < co2_dh:
                    return LightweightResult(statement, EntailmentLabel.ENTAILMENT, 0.9,
                        f"HP CO2 ({co2_hp:.1f}) < DH CO2 ({co2_dh:.1f})")
                else:
                    return LightweightResult(statement, EntailmentLabel.CONTRADICTION, 0.9,
                        f"HP CO2 ({co2_hp:.1f}) ≥ DH CO2 ({co2_dh:.1f})")
        
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
        
        # Default: neutral (not verifiable with rules)
        return LightweightResult(statement, EntailmentLabel.NEUTRAL, 0.5, 
            "Could not verify against KPIs with rules")
    
    def _get_kpi(self, kpis: Dict[str, Any], keys: List[str]) -> Any:
        """Get first available KPI value from list of possible keys."""
        for key in keys:
            if key in kpis and kpis[key] is not None:
                return kpis[key]
        return None
    
    def _format_kpis(self, kpis: Dict[str, Any]) -> str:
        """Format KPIs for LLM prompt."""
        lines = []
        for k, v in kpis.items():
            if v is not None:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)
    
    def batch_validate(
        self,
        kpis: Dict[str, Any],
        statements: List[str]
    ) -> List[LightweightResult]:
        """Validate multiple statements."""
        return [self.validate_statement(kpis, s) for s in statements]


# Make it compatible with TNLIModel interface
class TNLIModel:
    """
    Wrapper that uses lightweight validation (no model download).
    """
    
    def __init__(self, config=None):
        self.validator = LightweightValidator(use_llm=True)
        logger.info("Using lightweight TNLI (no model download required)")
    
    def validate_statement(self, table_data: Dict[str, Any], statement: str):
        return self.validator.validate_statement(table_data, statement)
    
    def batch_validate(self, table_data: Dict[str, Any], statements: List[str]):
        return self.validator.batch_validate(table_data, statements)
