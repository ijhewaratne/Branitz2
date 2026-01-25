"""
Unit tests for TNLI Logic Auditor validation system.

Run with: pytest tests/test_validation.py
"""

import pytest
from unittest.mock import Mock, patch
from branitz_heat_decision.validation import (
    LogicAuditor,
    ValidationConfig,
    TNLIModel,
    EntailmentResult,
    EntailmentLabel
)


class TestValidationConfig:
    """Test validation configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = ValidationConfig()
        assert config.model_name == "microsoft/tapas-large-finetuned-tabfact"
        assert config.min_confidence == 0.7
        assert config.max_iterations == 3
        assert config.enable_feedback is True
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = ValidationConfig(
            min_confidence=0.8,
            max_iterations=5,
            enable_feedback=False
        )
        assert config.min_confidence == 0.8
        assert config.max_iterations == 5
        assert config.enable_feedback is False


class TestLogicAuditor:
    """Test LogicAuditor class."""
    
    @pytest.fixture
    def mock_model(self):
        """Mock TNLI model to avoid loading actual model."""
        with patch('branitz_heat_decision.validation.logic_auditor.TNLIModel') as mock:
            yield mock
    
    @pytest.fixture
    def auditor(self, mock_model):
        """Create LogicAuditor with mocked model."""
        return LogicAuditor()
    
    def test_parse_statements(self, auditor):
        """Test statement parsing."""
        rationale = "District heating is cheaper. Heat pumps cost more. The difference is 10 EUR/MWh."
        statements = auditor._parse_statements(rationale)
        
        assert len(statements) == 3
        assert "District heating is cheaper" in statements[0]
        assert "Heat pumps cost more" in statements[1]
    
    def test_validate_rationale_pass(self, auditor, mock_model):
        """Test validation that passes."""
        # Mock successful validation
        mock_result = Mock(spec=EntailmentResult)
        mock_result.label = EntailmentLabel.ENTAILMENT
        mock_result.confidence = 0.95
        mock_result.is_valid = True
        mock_result.is_contradiction = False
        mock_result.statement = "District heating is cheaper"
        
        auditor.model.batch_validate = Mock(return_value=[mock_result])
        
        report = auditor.validate_rationale(
            kpis={"lcoh_dh": 75.0, "lcoh_hp": 82.0},
            rationale="District heating is cheaper.",
            cluster_id="test"
        )
        
        assert report.validation_status == "pass"
        assert not report.has_contradictions
        assert report.statements_validated == 1
    
    def test_validate_rationale_contradiction(self, auditor, mock_model):
        """Test validation with contradiction."""
        # Mock contradiction
        mock_result = Mock(spec=EntailmentResult)
        mock_result.label = EntailmentLabel.CONTRADICTION
        mock_result.confidence = 0.85
        mock_result.is_valid = False
        mock_result.is_contradiction = True
        mock_result.statement = "Heat pumps are cheaper"
        
        auditor.model.batch_validate = Mock(return_value=[mock_result])
        
        report = auditor.validate_rationale(
            kpis={"lcoh_dh": 75.0, "lcoh_hp": 82.0},
            rationale="Heat pumps are cheaper.",
            cluster_id="test"
        )
        
        assert report.validation_status == "fail"
        assert report.has_contradictions
        assert len(report.contradictions) == 1
    
    def test_identify_contradiction_context(self, auditor):
        """Test KPI context identification."""
        kpis = {"lcoh_dh": 75.0, "lcoh_hp": 82.0, "co2_dh": 250.0}
        
        # Statement mentioning lcoh_hp
        context = auditor._identify_contradiction_context(
            "Heat pump LCOH is 82 EUR/MWh",
            kpis
        )
        assert "lcoh_hp" in context
    
    def test_validation_report_to_dict(self, auditor, mock_model):
        """Test report serialization."""
        mock_result = Mock(spec=EntailmentResult)
        mock_result.label = EntailmentLabel.ENTAILMENT
        mock_result.confidence = 0.9
        mock_result.is_valid = True
        mock_result.is_contradiction = False
        mock_result.statement = "Test statement"
        
        auditor.model.batch_validate = Mock(return_value=[mock_result])
        
        report = auditor.validate_rationale(
            kpis={"test": 1},
            rationale="Test statement.",
            cluster_id="test"
        )
        
        report_dict = report.to_dict()
        
        assert "cluster_id" in report_dict
        assert "validation_status" in report_dict
        assert "overall_confidence" in report_dict
        assert "contradictions" in report_dict
        assert report_dict["cluster_id"] == "test"


class TestFeedbackLoop:
    """Test feedback loop functionality."""
    
    @pytest.fixture
    def mock_auditor(self):
        """Mock auditor."""
        with patch('branitz_heat_decision.validation.feedback_loop.LogicAuditor') as mock:
            yield mock
    
    def test_feedback_disabled(self, mock_auditor):
        """Test feedback loop when disabled."""
        from branitz_heat_decision.validation.feedback_loop import FeedbackLoop
        
        config = ValidationConfig(enable_feedback=False)
        loop = FeedbackLoop(mock_auditor, config)
        
        # Mock validation report (pass)
        mock_report = Mock()
        mock_report.has_contradictions = False
        mock_auditor.validate_rationale = Mock(return_value=mock_report)
        
        regenerate_fn = Mock()
        
        final, report = loop.validate_with_feedback(
            kpis={},
            initial_rationale="Test",
            regenerate_fn=regenerate_fn,
            cluster_id="test"
        )
        
        # Should not call regenerate if feedback disabled
        regenerate_fn.assert_not_called()
    
    def test_feedback_with_refinement(self, mock_auditor):
        """Test feedback loop with automatic refinement."""
        from branitz_heat_decision.validation.feedback_loop import FeedbackLoop
        
        config = ValidationConfig(enable_feedback=True, max_iterations=2)
        loop = FeedbackLoop(mock_auditor, config)
        
        # First validation fails, second passes
        fail_report = Mock()
        fail_report.has_contradictions = True
        fail_report.contradictions = [Mock()]
        
        pass_report = Mock()
        pass_report.has_contradictions = False
        pass_report.feedback_iterations = 0
        
        mock_auditor.validate_rationale = Mock(side_effect=[fail_report, pass_report])
        
        regenerate_fn = Mock(return_value="Refined rationale")
        
        final, report = loop.validate_with_feedback(
            kpis={"test": 1},
            initial_rationale="Initial",
            regenerate_fn=regenerate_fn,
            cluster_id="test"
        )
        
        # Should call regenerate once
        regenerate_fn.assert_called_once()
        assert final == "Refined rationale"


class TestIntegration:
    """Integration tests for complete workflow."""
    
    @pytest.mark.integration
    def test_end_to_end_validation_workflow(self):
        """Test complete validation workflow (requires model)."""
        # This test requires actual TAPAS model - mark as integration test
        pytest.skip("Requires TAPAS model download - run separately")
        
        from branitz_heat_decision.validation import LogicAuditor
        
        auditor = LogicAuditor()
        
        # Test with realistic KPIs
        kpis = {
            "lcoh_dh": 75.2,
            "lcoh_hp": 82.5,
            "co2_dh": 250.3,
            "co2_hp": 180.1
        }
        
        # Valid rationale
        rationale = "District heating has lower costs at 75.2 EUR/MWh compared to heat pumps at 82.5 EUR/MWh."
        
        report = auditor.validate_rationale(kpis, rationale, "test")
        
        assert report.validation_status in ["pass", "warning"]
        assert not report.has_contradictions


# Benchmark tests
class TestPerformance:
    """Performance benchmarking tests."""
    
    @pytest.mark.benchmark
    def test_validation_performance(self, benchmark):
        """Benchmark validation performance."""
        pytest.skip("Benchmark test - run separately")
        
        from branitz_heat_decision.validation import LogicAuditor
        
        auditor = LogicAuditor()
        kpis = {"lcoh_dh": 75.0, "lcoh_hp": 82.0}
        rationale = "District heating is cheaper with lower operating costs."
        
        # Benchmark should complete in < 5 seconds
        result = benchmark(auditor.validate_rationale, kpis, rationale, "bench")
        assert result.validation_status in ["pass", "warning", "fail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
