#!/usr/bin/env python3
"""
Integration Tests for Cards Memex

These tests verify CRITICAL FLOWS end-to-end:
1. New decision supersedes old decision
2. Latest information wins in retrieval  
3. Feedback affects ranking
4. Format changes don't break output

Run before deploying any changes:
    python scripts/test_integration.py

Run specific test:
    python scripts/test_integration.py --test freshness
    python scripts/test_integration.py --test format
    python scripts/test_integration.py --test feedback
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from dataclasses import dataclass

# Setup paths
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(APP_DIR / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration_ms: float = 0.0


class IntegrationTestSuite:
    """Integration tests for critical flows."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results: List[TestResult] = []
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    # =========================================================================
    # TEST 1: Freshness - New decision beats old decision
    # =========================================================================
    
    def test_freshness_ranking(self) -> TestResult:
        """
        Verify that newer information ranks higher than older.
        
        Scenario: Two threads about same topic, one 7 days old, one 60 days old.
        Expected: 7-day thread should rank significantly higher.
        """
        try:
            from memex_core.ranking import FreshnessRanker
            
            ranker = FreshnessRanker({
                "retrieval": {
                    "recency": {"full_weight_days": 30, "half_life_days": 60},
                    "weights": {"semantic": 0.7, "recency": 0.3}
                }
            })
            
            now = datetime.now()
            
            # Create two results with same semantic score but different ages
            new_thread_ts = str((now - timedelta(days=7)).timestamp())
            old_thread_ts = str((now - timedelta(days=60)).timestamp())
            
            new_result = ranker.compute_ranking_score(
                semantic_similarity=0.85,
                metadata={"thread_ts": new_thread_ts, "lifecycle_status": "Active"},
                now=now
            )
            
            old_result = ranker.compute_ranking_score(
                semantic_similarity=0.85,
                metadata={"thread_ts": old_thread_ts, "lifecycle_status": "Active"},
                now=now
            )
            
            # New should score higher
            if new_result.final_score <= old_result.final_score:
                return TestResult(
                    "freshness_ranking",
                    False,
                    f"New thread ({new_result.final_score:.3f}) should rank higher than old ({old_result.final_score:.3f})"
                )
            
            # Gap should be significant (at least 10%)
            gap = (new_result.final_score - old_result.final_score) / old_result.final_score
            if gap < 0.10:
                return TestResult(
                    "freshness_ranking",
                    False,
                    f"Recency gap too small: {gap:.1%}. Newer thread may not surface."
                )
            
            return TestResult(
                "freshness_ranking",
                True,
                f"New thread scores {gap:.1%} higher than 60-day-old thread ✓"
            )
            
        except Exception as e:
            return TestResult("freshness_ranking", False, f"Exception: {e}")
    
    # =========================================================================
    # TEST 2: Supersession - Deprecated threads heavily penalized
    # =========================================================================
    
    def test_supersession_penalty(self) -> TestResult:
        """
        Verify that deprecated threads are heavily penalized in ranking.
        
        Scenario: Active thread vs Deprecated thread with same semantic score.
        Expected: Deprecated should score ~90% lower.
        """
        try:
            from memex_core.ranking import FreshnessRanker
            
            ranker = FreshnessRanker()
            now = datetime.now()
            thread_ts = str(now.timestamp())
            
            active_result = ranker.compute_ranking_score(
                semantic_similarity=0.9,
                metadata={"thread_ts": thread_ts, "lifecycle_status": "Active"},
                now=now
            )
            
            deprecated_result = ranker.compute_ranking_score(
                semantic_similarity=0.9,
                metadata={"thread_ts": thread_ts, "lifecycle_status": "Deprecated"},
                now=now
            )
            
            # Deprecated should be heavily penalized
            penalty = 1 - (deprecated_result.final_score / active_result.final_score)
            
            if penalty < 0.80:
                return TestResult(
                    "supersession_penalty",
                    False,
                    f"Deprecated penalty only {penalty:.0%}, should be ~90%"
                )
            
            return TestResult(
                "supersession_penalty",
                True,
                f"Deprecated threads penalized by {penalty:.0%} ✓"
            )
            
        except Exception as e:
            return TestResult("supersession_penalty", False, f"Exception: {e}")
    
    # =========================================================================
    # TEST 3: Feedback - L2 reinforcement affects ranking
    # =========================================================================
    
    def test_feedback_boost(self) -> TestResult:
        """
        Verify that positive feedback boosts thread ranking.
        
        Scenario: Same thread with feedback_score=0 vs feedback_score=1.0
        Expected: Boosted thread should score ~2x higher.
        """
        try:
            from memex_core.ranking import FreshnessRanker
            
            ranker = FreshnessRanker()
            now = datetime.now()
            thread_ts = str(now.timestamp())
            
            neutral_result = ranker.compute_ranking_score(
                semantic_similarity=0.8,
                metadata={"thread_ts": thread_ts, "lifecycle_status": "Active", "feedback_score": 0.0},
                now=now
            )
            
            boosted_result = ranker.compute_ranking_score(
                semantic_similarity=0.8,
                metadata={"thread_ts": thread_ts, "lifecycle_status": "Active", "feedback_score": 1.0},
                now=now
            )
            
            # Boosted should be ~2x
            ratio = boosted_result.final_score / neutral_result.final_score
            
            if ratio < 1.8 or ratio > 2.2:
                return TestResult(
                    "feedback_boost",
                    False,
                    f"Feedback boost ratio is {ratio:.2f}x, expected ~2x"
                )
            
            return TestResult(
                "feedback_boost",
                True,
                f"Positive feedback provides {ratio:.2f}x boost ✓"
            )
            
        except Exception as e:
            return TestResult("feedback_boost", False, f"Exception: {e}")
    
    # =========================================================================
    # TEST 4: Response Format - Length limits work
    # =========================================================================
    
    def test_response_truncation(self) -> TestResult:
        """
        Verify that response formatter truncates long answers.
        
        Scenario: 2000 char answer with 800 char limit.
        Expected: Output should be ≤800 chars.
        """
        try:
            from memex_core import ResponseFormatter
            
            formatter = ResponseFormatter(
                output_config={"length": {"max_chars": 800}}
            )
            
            long_answer = "This is a test. " * 200  # ~3200 chars
            
            result = formatter.format_answer(long_answer, confidence=0.9)
            
            if len(result.text) > 800:
                return TestResult(
                    "response_truncation",
                    False,
                    f"Output length {len(result.text)} exceeds limit 800"
                )
            
            if not result.was_truncated:
                return TestResult(
                    "response_truncation",
                    False,
                    f"was_truncated should be True"
                )
            
            return TestResult(
                "response_truncation",
                True,
                f"Long answer truncated to {len(result.text)} chars ✓"
            )
            
        except Exception as e:
            return TestResult("response_truncation", False, f"Exception: {e}")
    
    # =========================================================================
    # TEST 5: Confidence Prefix - Low confidence gets qualified
    # =========================================================================
    
    def test_confidence_prefix(self) -> TestResult:
        """
        Verify that low confidence answers get qualified.
        
        Scenario: Answer with 0.3 confidence (threshold 0.5).
        Expected: Output should start with uncertainty prefix.
        """
        try:
            from memex_core import ResponseFormatter
            
            formatter = ResponseFormatter(
                output_config={"confidence": {"threshold": 0.5}},
                ux_config={"success": {"low_confidence_prefix": "I'm not sure, but: "}}
            )
            
            result = formatter.format_answer("The answer is 42.", confidence=0.3)
            
            if not result.confidence_applied:
                return TestResult(
                    "confidence_prefix",
                    False,
                    "confidence_applied should be True for low confidence"
                )
            
            if not result.text.startswith("I'm not sure"):
                return TestResult(
                    "confidence_prefix",
                    False,
                    f"Expected prefix not found. Got: {result.text[:50]}..."
                )
            
            return TestResult(
                "confidence_prefix",
                True,
                f"Low confidence answer properly qualified ✓"
            )
            
        except Exception as e:
            return TestResult("confidence_prefix", False, f"Exception: {e}")
    
    # =========================================================================
    # TEST 6: UX Messages - Thinking message works
    # =========================================================================
    
    def test_thinking_message(self) -> TestResult:
        """
        Verify that thinking messages are returned.
        """
        try:
            from memex_core import ResponseFormatter
            
            formatter = ResponseFormatter(
                ux_config={"thinking": {
                    "default": "🔍 Searching...",
                    "variants": ["🔍 Searching...", "🧠 Thinking..."]
                }}
            )
            
            msg = formatter.get_thinking_message()
            
            if not msg or len(msg) < 5:
                return TestResult(
                    "thinking_message",
                    False,
                    f"Thinking message empty or too short: '{msg}'"
                )
            
            return TestResult(
                "thinking_message",
                True,
                f"Thinking message returned: '{msg}' ✓"
            )
            
        except Exception as e:
            return TestResult("thinking_message", False, f"Exception: {e}")
    
    # =========================================================================
    # RUN ALL TESTS
    # =========================================================================
    
    def run_all(self) -> bool:
        """Run all integration tests. Returns True if all pass."""
        tests = [
            ("Freshness Ranking", self.test_freshness_ranking),
            ("Supersession Penalty", self.test_supersession_penalty),
            ("Feedback Boost", self.test_feedback_boost),
            ("Response Truncation", self.test_response_truncation),
            ("Confidence Prefix", self.test_confidence_prefix),
            ("Thinking Message", self.test_thinking_message),
        ]
        
        print("=" * 60)
        print("INTEGRATION TEST SUITE")
        print("=" * 60)
        print()
        
        all_passed = True
        
        for name, test_fn in tests:
            self.log(f"Running: {name}...")
            start = datetime.now()
            result = test_fn()
            result.duration_ms = (datetime.now() - start).total_seconds() * 1000
            self.results.append(result)
            
            status = "✅ PASS" if result.passed else "❌ FAIL"
            self.log(f"  {status}: {result.message}")
            
            if not result.passed:
                all_passed = False
        
        print()
        print("=" * 60)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"Results: {passed}/{total} tests passed")
        print("=" * 60)
        
        return all_passed
    
    def run_single(self, test_name: str) -> bool:
        """Run a single test by name."""
        test_map = {
            "freshness": self.test_freshness_ranking,
            "supersession": self.test_supersession_penalty,
            "feedback": self.test_feedback_boost,
            "format": self.test_response_truncation,
            "confidence": self.test_confidence_prefix,
            "thinking": self.test_thinking_message,
        }
        
        if test_name not in test_map:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(test_map.keys())}")
            return False
        
        result = test_map[test_name]()
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"{status}: {result.message}")
        
        return result.passed


def main():
    parser = argparse.ArgumentParser(description="Integration tests for Cards Memex")
    parser.add_argument("--test", type=str, help="Run a specific test")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    
    args = parser.parse_args()
    
    suite = IntegrationTestSuite(verbose=not args.quiet)
    
    if args.test:
        success = suite.run_single(args.test)
    else:
        success = suite.run_all()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

