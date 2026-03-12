#!/usr/bin/env python3
"""
Contract Tests: Validate interfaces between modules.

These tests ensure that when you change one module, you don't silently
break another module that depends on it.

RUN BEFORE DEPLOYING ANY CHANGES:
    python scripts/test_contracts.py

These tests are FAST (no API calls) and catch interface breakage.
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Callable, Any
from datetime import datetime

# Setup paths
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(APP_DIR / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))


@dataclass
class ContractTest:
    name: str
    test_fn: Callable[[], bool]
    description: str


class ContractTestSuite:
    """Tests that module interfaces haven't changed unexpectedly."""
    
    def __init__(self):
        self.tests: List[ContractTest] = []
        self.register_all_tests()
    
    def register_all_tests(self):
        """Register all contract tests."""
        # ResponseFormatter contracts
        self.tests.append(ContractTest(
            "ResponseFormatter.format_answer returns FormattedResponse",
            self.test_response_formatter_returns_formatted_response,
            "Handlers expect FormattedResponse with .text, .was_truncated, etc."
        ))
        
        self.tests.append(ContractTest(
            "FormattedResponse has required fields",
            self.test_formatted_response_has_required_fields,
            "Handlers access .text, .was_truncated, .confidence_applied"
        ))
        
        self.tests.append(ContractTest(
            "ResponseFormatter.get_thinking_message returns string",
            self.test_thinking_message_returns_string,
            "message.py expects string for Slack API"
        ))
        
        self.tests.append(ContractTest(
            "ResponseFormatter.get_error_message returns string",
            self.test_error_message_returns_string,
            "message.py expects string for Slack API"
        ))
        
        self.tests.append(ContractTest(
            "ResponseFormatter.get_empty_message returns string",
            self.test_empty_message_returns_string,
            "message.py expects string for Slack API"
        ))
        
        # FreshnessRanker contracts
        self.tests.append(ContractTest(
            "FreshnessRanker.compute_ranking_score returns RankingResult",
            self.test_ranker_returns_ranking_result,
            "retrieval.py expects RankingResult with .final_score"
        ))
        
        self.tests.append(ContractTest(
            "RankingResult has required fields",
            self.test_ranking_result_has_required_fields,
            "retrieval.py accesses .final_score, .recency_score, etc."
        ))
        
        # Config loading contracts
        self.tests.append(ContractTest(
            "OutputConfig.from_dict accepts empty dict",
            self.test_output_config_accepts_empty_dict,
            "Services must work even with missing config"
        ))
        
        self.tests.append(ContractTest(
            "UXConfig.from_dict accepts empty dict",
            self.test_ux_config_accepts_empty_dict,
            "Services must work even with missing config"
        ))
        
        # BotContext contracts
        self.tests.append(ContractTest(
            "BotContext can be instantiated with minimal args",
            self.test_bot_context_minimal_instantiation,
            "handlers.py creates BotContext"
        ))
        
        # Pydantic model contracts
        self.tests.append(ContractTest(
            "AppConfig models can be serialized to dict",
            self.test_app_config_model_dump,
            "Various places call .model_dump() for dict conversion"
        ))
    
    # =========================================================================
    # ResponseFormatter Contracts
    # =========================================================================
    
    def test_response_formatter_returns_formatted_response(self) -> bool:
        """ResponseFormatter.format_answer must return FormattedResponse."""
        from memex_core import ResponseFormatter, FormattedResponse
        
        formatter = ResponseFormatter()
        result = formatter.format_answer("test answer", confidence=0.8)
        
        return isinstance(result, FormattedResponse)
    
    def test_formatted_response_has_required_fields(self) -> bool:
        """FormattedResponse must have fields handlers expect."""
        from memex_core import ResponseFormatter
        
        formatter = ResponseFormatter()
        result = formatter.format_answer("test answer", confidence=0.8)
        
        required_fields = ['text', 'was_truncated', 'confidence_applied', 
                          'staleness_warning_applied', 'original_length']
        
        for field in required_fields:
            if not hasattr(result, field):
                print(f"  Missing field: {field}")
                return False
        
        # Type checks
        if not isinstance(result.text, str):
            print(f"  .text should be str, got {type(result.text)}")
            return False
        if not isinstance(result.was_truncated, bool):
            print(f"  .was_truncated should be bool, got {type(result.was_truncated)}")
            return False
        
        return True
    
    def test_thinking_message_returns_string(self) -> bool:
        """get_thinking_message must return string for Slack API."""
        from memex_core import ResponseFormatter
        
        formatter = ResponseFormatter()
        result = formatter.get_thinking_message()
        
        if not isinstance(result, str):
            print(f"  Expected str, got {type(result)}")
            return False
        if len(result) < 1:
            print(f"  Empty string returned")
            return False
        
        return True
    
    def test_error_message_returns_string(self) -> bool:
        """get_error_message must return string for Slack API."""
        from memex_core import ResponseFormatter
        
        formatter = ResponseFormatter()
        
        for error_type in ["generic", "rate_limited", "api_error"]:
            result = formatter.get_error_message(error_type)
            if not isinstance(result, str):
                print(f"  {error_type}: Expected str, got {type(result)}")
                return False
            if len(result) < 1:
                print(f"  {error_type}: Empty string returned")
                return False
        
        return True
    
    def test_empty_message_returns_string(self) -> bool:
        """get_empty_message must return string for Slack API."""
        from memex_core import ResponseFormatter
        
        formatter = ResponseFormatter()
        
        for state_type in ["no_results", "no_context"]:
            result = formatter.get_empty_message(state_type)
            if not isinstance(result, str):
                print(f"  {state_type}: Expected str, got {type(result)}")
                return False
        
        return True
    
    # =========================================================================
    # FreshnessRanker Contracts
    # =========================================================================
    
    def test_ranker_returns_ranking_result(self) -> bool:
        """compute_ranking_score must return RankingResult."""
        from memex_core import FreshnessRanker, RankingResult
        
        ranker = FreshnessRanker()
        result = ranker.compute_ranking_score(
            semantic_similarity=0.8,
            metadata={"thread_ts": str(datetime.now().timestamp())}
        )
        
        return isinstance(result, RankingResult)
    
    def test_ranking_result_has_required_fields(self) -> bool:
        """RankingResult must have fields retrieval.py expects."""
        from memex_core import FreshnessRanker
        
        ranker = FreshnessRanker()
        result = ranker.compute_ranking_score(
            semantic_similarity=0.8,
            metadata={"thread_ts": str(datetime.now().timestamp())}
        )
        
        required_fields = ['final_score', 'semantic_score', 'recency_score',
                          'priority_score', 'feedback_score', 'supersession_penalty']
        
        for field in required_fields:
            if not hasattr(result, field):
                print(f"  Missing field: {field}")
                return False
        
        # Type checks
        if not isinstance(result.final_score, (int, float)):
            print(f"  .final_score should be numeric, got {type(result.final_score)}")
            return False
        
        return True
    
    # =========================================================================
    # Config Contracts
    # =========================================================================
    
    def test_output_config_accepts_empty_dict(self) -> bool:
        """OutputConfig must work with empty dict (default values)."""
        from memex_core.formatters.response_formatter import OutputConfig
        
        try:
            config = OutputConfig.from_dict({})
            # Must have sensible defaults
            if config.max_chars <= 0:
                print(f"  max_chars should be positive, got {config.max_chars}")
                return False
            return True
        except Exception as e:
            print(f"  Exception: {e}")
            return False
    
    def test_ux_config_accepts_empty_dict(self) -> bool:
        """UXConfig must work with empty dict (default values)."""
        from memex_core.formatters.response_formatter import UXConfig
        
        try:
            config = UXConfig.from_dict({})
            # Must have sensible defaults
            if not config.thinking_default:
                print(f"  thinking_default should not be empty")
                return False
            return True
        except Exception as e:
            print(f"  Exception: {e}")
            return False
    
    # =========================================================================
    # BotContext Contracts
    # =========================================================================
    
    def test_bot_context_minimal_instantiation(self) -> bool:
        """BotContext must work with minimal required args."""
        from twin_brain.context import BotContext
        from memex_core import RoleDefinition, Theme
        
        # Create minimal mock objects
        mock_role_def = RoleDefinition(
            role="Test",
            products=["Test Product"],
            themes=[Theme(name="Test Theme", description="Test")],
            topics=["Test Topic"]
        )
        
        # Create mock ingestion pipeline (minimal)
        class MockIngestPipe:
            pass
        
        try:
            context = BotContext(
                role_definition=mock_role_def,
                ingest_pipe=MockIngestPipe()
            )
            return context is not None
        except Exception as e:
            print(f"  Exception: {e}")
            return False
    
    # =========================================================================
    # Pydantic Model Contracts
    # =========================================================================
    
    def test_app_config_model_dump(self) -> bool:
        """Config models must support .model_dump() for dict conversion."""
        from twin_brain.config_models import (
            BehaviorConfig, OutputConfig, UXConfig, RetrievalConfig
        )
        
        configs = [
            BehaviorConfig(),
            OutputConfig(),
            UXConfig(),
            RetrievalConfig(),
        ]
        
        for config in configs:
            try:
                result = config.model_dump()
                if not isinstance(result, dict):
                    print(f"  {type(config).__name__}.model_dump() should return dict")
                    return False
            except Exception as e:
                print(f"  {type(config).__name__}.model_dump() failed: {e}")
                return False
        
        return True
    
    # =========================================================================
    # Run All Tests
    # =========================================================================
    
    def run_all(self) -> bool:
        """Run all contract tests. Returns True if all pass."""
        print("=" * 60)
        print("CONTRACT TEST SUITE")
        print("=" * 60)
        print()
        print("These tests validate interfaces between modules.")
        print("If any fail, you may have broken a dependent module.")
        print()
        
        passed = 0
        failed = 0
        
        for test in self.tests:
            try:
                result = test.test_fn()
                if result:
                    print(f"✅ {test.name}")
                    passed += 1
                else:
                    print(f"❌ {test.name}")
                    print(f"   → {test.description}")
                    failed += 1
            except Exception as e:
                print(f"❌ {test.name}")
                print(f"   → Exception: {e}")
                failed += 1
        
        print()
        print("=" * 60)
        print(f"Results: {passed}/{passed + failed} contracts passed")
        
        if failed > 0:
            print()
            print("⚠️  CONTRACT VIOLATIONS DETECTED")
            print("   You may have broken interfaces other modules depend on.")
            print("   Check the failures above and fix before deploying.")
        else:
            print()
            print("✅ All contracts satisfied. Safe to proceed.")
        
        print("=" * 60)
        
        return failed == 0


def main():
    suite = ContractTestSuite()
    success = suite.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

