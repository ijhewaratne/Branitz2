"""
Validation module for Branitz Heat Decision System.

Provides logic auditing using Tabular Natural Language Inference (TNLI)
to validate LLM-generated decision rationales against KPI data.
"""

from .logic_auditor import LogicAuditor, ValidationReport, Contradiction
from .tnli_model import TNLIModel, LightweightResult as EntailmentResult, EntailmentLabel
from .config import ValidationConfig
from .feedback_loop import FeedbackLoop
from .claims import (
    ClaimType, Claim, ClaimResult, ClaimValidator, 
    StructuredExplanation, Operator
)

__all__ = [
    "LogicAuditor",
    "ValidationReport",
    "Contradiction",
    "TNLIModel",
    "EntailmentResult",
    "EntailmentLabel",
    "ValidationConfig",
    "FeedbackLoop",
    "ClaimType",
    "Claim",
    "ClaimResult", 
    "ClaimValidator",
    "StructuredExplanation",
    "Operator",
]

