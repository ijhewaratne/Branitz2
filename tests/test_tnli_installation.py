#!/usr/bin/env python3
"""
Simple test script to verify TNLI Logic Auditor installation and basic functionality.

Run this to check if validation system is properly set up.
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_imports():
    """Test if all validation modules can be imported."""
    logger.info("Testing imports...")
    try:
        from branitz_heat_decision.validation import (
            LogicAuditor,
            ValidationConfig,
            TNLIModel,
            EntailmentResult,
            FeedbackLoop
        )
        logger.info("✅ All imports successful")
        return True
    except ImportError as e:
        logger.error(f"❌ Import failed: {e}")
        return False


def test_config():
    """Test configuration creation."""
    logger.info("Testing configuration...")
    try:
        from branitz_heat_decision.validation import ValidationConfig
        
        config = ValidationConfig(
            min_confidence=0.8,
            max_iterations=2,
            enable_feedback=True
        )
        
        assert config.min_confidence == 0.8
        assert config.max_iterations == 2
        
        logger.info("✅ Configuration works")
        return True
    except Exception as e:
        logger.error(f"❌ Configuration failed: {e}")
        return False


def test_model_loading():
    """Test TNLI model loading (downloads model if needed)."""
    logger.info("Testing TNLI model loading...")
    logger.warning("⏳ This may take a few minutes on first run (downloading ~1.2GB model)...")
    
    try:
        from branitz_heat_decision.validation import TNLIModel, ValidationConfig
        
        config = ValidationConfig(use_cpu=True)  # Force CPU for testing
        model = TNLIModel(config)
        
        logger.info("✅ TNLI model loaded successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Model loading failed: {e}")
        logger.info("💡 Tip: Install transformers with: pip install transformers torch")
        return False


def test_simple_validation():
    """Test simple validation without actual model."""
    logger.info("Testing basic validation logic...")
    try:
        from branitz_heat_decision.validation import LogicAuditor
        from unittest.mock import Mock, patch
        
        # Mock the model to avoid loading
        with patch('branitz_heat_decision.validation.logic_auditor.TNLIModel'):
            auditor = LogicAuditor()
            
            # Test statement parsing
            statements = auditor._parse_statements(
                "District heating is cheaper. Heat pumps cost more."
            )
            
            assert len(statements) == 2
            logger.info(f"✅ Parsed {len(statements)} statements correctly")
            return True
    except Exception as e:
        logger.error(f"❌ Basic validation failed: {e}")
        return False


def test_integration_example():
    """Test integration example can be imported."""
    logger.info("Testing integration example...")
    try:
        sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
        from branitz_heat_decision.validation.integration_example import (
            validate_decision_explanation,
            make_decision_with_validation
        )
        logger.info("✅ Integration example imports successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Integration example failed: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TNLI Logic Auditor - Installation Test")
    print("="*60 + "\n")
    
    tests = [
        ("Module Imports", test_imports),
        ("Configuration", test_config),
        ("Basic Validation Logic", test_simple_validation),
        ("Integration Example", test_integration_example),
    ]
    
    results = []
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}")
            results.append((name, False))
    
    # Optional: Test model loading (takes time)
    print("\n" + "="*60)
    user_input = input("\n⚠️  Test TNLI model loading? (downloads ~1.2GB, y/n): ")
    if user_input.lower() == 'y':
        print(f"\n--- TNLI Model Loading ---")
        result = test_model_loading()
        results.append(("Model Loading", result))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! TNLI Logic Auditor is ready to use.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check logs above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
