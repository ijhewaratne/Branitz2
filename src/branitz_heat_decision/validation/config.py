"""
Configuration for validation module.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ValidationConfig:
    """Configuration for TNLI logic validation."""
    
    # Model settings
    model_name: str = "google/tapas-large-finetuned-tabfact"
    use_cpu: bool = False  # Set to True to force CPU usage
    model_cache_dir: Optional[Path] = None
    
    # Validation thresholds
    min_confidence: float = 0.7  # Minimum confidence for entailment
    contradiction_threshold: float = 0.5  # Above this = contradiction
    
    # Feedback loop settings
    max_iterations: int = 3  # Max re-generation attempts
    enable_feedback: bool = True  # Enable automatic re-generation
    
    # Monitoring and logging
    log_level: str = "INFO"
    save_reports: bool = True
    report_dir: Path = Path("results/validation")
    
    # Performance
    batch_size: int = 8  # For batch validation
    max_sequence_length: int = 512  # Token limit
    
    def __post_init__(self):
        """Ensure directories exist."""
        if self.save_reports:
            self.report_dir.mkdir(parents=True, exist_ok=True)
        
        if self.model_cache_dir:
            self.model_cache_dir.mkdir(parents=True, exist_ok=True)


def get_default_config() -> ValidationConfig:
    """Get default validation configuration."""
    return ValidationConfig()
