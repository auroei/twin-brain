#!/usr/bin/env python3
"""
Critical Flow Tests: The scenarios that MUST work.

These tests validate the most important behaviors:
1. New decision beats old decision (freshness)
2. Deprecated threads don't surface (supersession)
3. User feedback affects future ranking (L2 reinforcement)
4. Response format doesn't break Slack (output safety)

RUN BEFORE EVERY DEPLOY:
    python scripts/test_critical_flows.py

If any of these fail, DO NOT DEPLOY.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

# Setup paths
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(APP_DIR / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))


@dataclass
class CriticalFlowResult:
    name: str
    passed: bool
    message: str
    details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class CriticalFlowTests:
    """
    Tests for the most critical user-facing behaviors.
    
    If any of these fail, the bot will misbehave in obvious ways.
    """
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results: List[CriticalFlowResult] = []
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    # =========================================================================
    # CRITICAL FLOW 1: New Decision Beats Old Decision
    # =========================================================================
    
    def test_new_decision_beats_old(self) -> CriticalFlowResult:
        """
        SCENARIO: User asked "what's our strategy?"
        - Thread A (30 days old): "Our strategy is mobile-first"
        - Thread B (2 days old): "Our strategy is now desktop-first"
        
        EXPECTED: Thread B should rank significantly higher.
        
        This is THE MOST IMPORTANT test. If this fails, the bot will
        give outdated information which destroys user trust.
        """
        from memex_core import FreshnessRanker
        
        ranker = FreshnessRanker({
            "retrieval": {
                "recency": {"full_weight_days": 7, "half_life_days": 30},
                "weights": {"semantic": 0.6, "recency": 0.4}
            }
        })
        
        now = datetime.now()
        
        # Same semantic similarity (both match the query equally well)
        semantic_similarity = 0.85
        
        # Old thread: 30 days ago
        old_thread_ts = str((now - timedelta(days=30)).timestamp())
        old_result = ranker.compute_ranking_score(
            semantic_similarity=semantic_similarity,
            metadata={
                "thread_ts": old_thread_ts,
                "lifecycle_status": "Active",
                "thread_name": "Original Strategy Discussion"
            },
            now=now
        )
        
        # New thread: 2 days ago
        new_thread_ts = str((now - timedelta(days=2)).timestamp())
        new_result = ranker.compute_ranking_score(
            semantic_similarity=semantic_similarity,
            metadata={
                "thread_ts": new_thread_ts,
                "lifecycle_status": "Active",
                "thread_name": "Updated Strategy Decision"
            },
            now=now
        )
        
        # CRITICAL: New thread MUST score higher
        if new_result.final_score <= old_result.final_score:
            return CriticalFlowResult(
                name="New Decision Beats Old Decision",
                passed=False,
                message=f"NEW THREAD SHOULD WIN! New: {new_result.final_score:.4f}, Old: {old_result.final_score:.4f}",
                details={
                    "new_score": new_result.final_score,
                    "old_score": old_result.final_score,
                    "new_recency": new_result.recency_score,
                    "old_recency": old_result.recency_score,
                }
            )
        
        # The gap should be meaningful (at least 15%)
        gap = (new_result.final_score - old_result.final_score) / old_result.final_score
        if gap < 0.15:
            return CriticalFlowResult(
                name="New Decision Beats Old Decision",
                passed=False,
                message=f"Gap too small ({gap:.1%}). New decision may not reliably surface.",
                details={
                    "gap_percentage": gap,
                    "new_score": new_result.final_score,
                    "old_score": old_result.final_score,
                }
            )
        
        return CriticalFlowResult(
            name="New Decision Beats Old Decision",
            passed=True,
            message=f"New thread wins by {gap:.1%} (new: {new_result.final_score:.3f}, old: {old_result.final_score:.3f})",
            details={
                "gap_percentage": gap,
                "new_score": new_result.final_score,
                "old_score": old_result.final_score,
            }
        )
    
    # =========================================================================
    # CRITICAL FLOW 2: Deprecated Threads Are Suppressed
    # =========================================================================
    
    def test_deprecated_threads_suppressed(self) -> CriticalFlowResult:
        """
        SCENARIO: A thread was explicitly marked as deprecated.
        
        EXPECTED: It should score at least 80% lower than an active thread.
        
        If deprecated threads surface, users see contradictory information.
        """
        from memex_core import FreshnessRanker
        
        ranker = FreshnessRanker()
        now = datetime.now()
        thread_ts = str(now.timestamp())
        
        # Active thread
        active_result = ranker.compute_ranking_score(
            semantic_similarity=0.9,
            metadata={
                "thread_ts": thread_ts,
                "lifecycle_status": "Active",
            },
            now=now
        )
        
        # Deprecated thread (same age, same semantic similarity)
        deprecated_result = ranker.compute_ranking_score(
            semantic_similarity=0.9,
            metadata={
                "thread_ts": thread_ts,
                "lifecycle_status": "Deprecated",
            },
            now=now
        )
        
        # Calculate penalty
        if active_result.final_score == 0:
            return CriticalFlowResult(
                name="Deprecated Threads Suppressed",
                passed=False,
                message="Active thread has zero score - something is wrong",
            )
        
        penalty = 1 - (deprecated_result.final_score / active_result.final_score)
        
        if penalty < 0.80:
            return CriticalFlowResult(
                name="Deprecated Threads Suppressed",
                passed=False,
                message=f"Deprecated penalty only {penalty:.0%}, should be ≥80%",
                details={
                    "active_score": active_result.final_score,
                    "deprecated_score": deprecated_result.final_score,
                    "penalty": penalty,
                }
            )
        
        return CriticalFlowResult(
            name="Deprecated Threads Suppressed",
            passed=True,
            message=f"Deprecated threads penalized by {penalty:.0%}",
            details={
                "active_score": active_result.final_score,
                "deprecated_score": deprecated_result.final_score,
                "penalty": penalty,
            }
        )
    
    # =========================================================================
    # CRITICAL FLOW 3: Feedback Affects Ranking
    # =========================================================================
    
    def test_feedback_affects_ranking(self) -> CriticalFlowResult:
        """
        SCENARIO: Thread A got 👍 reactions, Thread B got 👎 reactions.
        
        EXPECTED: 
        - Positive feedback should boost ranking
        - Negative feedback should penalize ranking
        
        If feedback doesn't work, the system doesn't improve over time.
        """
        from memex_core import FreshnessRanker
        
        ranker = FreshnessRanker()
        now = datetime.now()
        thread_ts = str(now.timestamp())
        
        # Neutral thread (no feedback)
        neutral_result = ranker.compute_ranking_score(
            semantic_similarity=0.8,
            metadata={
                "thread_ts": thread_ts,
                "lifecycle_status": "Active",
                "feedback_score": 0.0,
            },
            now=now
        )
        
        # Positive feedback thread
        positive_result = ranker.compute_ranking_score(
            semantic_similarity=0.8,
            metadata={
                "thread_ts": thread_ts,
                "lifecycle_status": "Active",
                "feedback_score": 1.0,  # Maximum positive
            },
            now=now
        )
        
        # Negative feedback thread
        negative_result = ranker.compute_ranking_score(
            semantic_similarity=0.8,
            metadata={
                "thread_ts": thread_ts,
                "lifecycle_status": "Active",
                "feedback_score": -0.5,  # Moderate negative
            },
            now=now
        )
        
        # Positive should boost
        if positive_result.final_score <= neutral_result.final_score:
            return CriticalFlowResult(
                name="Feedback Affects Ranking",
                passed=False,
                message="Positive feedback should boost score",
                details={
                    "neutral": neutral_result.final_score,
                    "positive": positive_result.final_score,
                }
            )
        
        # Negative should penalize
        if negative_result.final_score >= neutral_result.final_score:
            return CriticalFlowResult(
                name="Feedback Affects Ranking",
                passed=False,
                message="Negative feedback should penalize score",
                details={
                    "neutral": neutral_result.final_score,
                    "negative": negative_result.final_score,
                }
            )
        
        boost_ratio = positive_result.final_score / neutral_result.final_score
        penalty_ratio = negative_result.final_score / neutral_result.final_score
        
        return CriticalFlowResult(
            name="Feedback Affects Ranking",
            passed=True,
            message=f"Positive: {boost_ratio:.2f}x boost, Negative: {penalty_ratio:.2f}x",
            details={
                "boost_ratio": boost_ratio,
                "penalty_ratio": penalty_ratio,
                "neutral_score": neutral_result.final_score,
            }
        )
    
    # =========================================================================
    # CRITICAL FLOW 4: Response Format Is Safe
    # =========================================================================
    
    def test_response_format_safe(self) -> CriticalFlowResult:
        """
        SCENARIO: Various edge cases in response formatting.
        
        EXPECTED:
        - Never return empty string
        - Never return None
        - Always return valid string for Slack
        
        If response format breaks, users see errors or empty responses.
        """
        from memex_core import ResponseFormatter
        
        formatter = ResponseFormatter()
        
        test_cases = [
            ("empty_answer", "", 0.9),
            ("whitespace_answer", "   \n\t  ", 0.9),
            ("normal_answer", "The answer is 42.", 0.9),
            ("low_confidence", "The answer is 42.", 0.2),
            ("very_long_answer", "x" * 5000, 0.9),
        ]
        
        failures = []
        
        for case_name, answer, confidence in test_cases:
            result = formatter.format_answer(answer, confidence=confidence)
            
            # Must return FormattedResponse
            if result is None:
                failures.append(f"{case_name}: returned None")
                continue
            
            # Must have .text attribute
            if not hasattr(result, 'text'):
                failures.append(f"{case_name}: missing .text attribute")
                continue
            
            # .text must be string
            if not isinstance(result.text, str):
                failures.append(f"{case_name}: .text is not string")
                continue
            
            # .text should not be empty for non-empty inputs (except whitespace)
            if answer.strip() and not result.text.strip():
                failures.append(f"{case_name}: non-empty input produced empty output")
                continue
        
        # Test thinking/error messages
        thinking = formatter.get_thinking_message()
        if not thinking or not isinstance(thinking, str):
            failures.append("get_thinking_message: invalid return")
        
        for error_type in ["generic", "rate_limited", "api_error"]:
            error = formatter.get_error_message(error_type)
            if not error or not isinstance(error, str):
                failures.append(f"get_error_message({error_type}): invalid return")
        
        if failures:
            return CriticalFlowResult(
                name="Response Format Is Safe",
                passed=False,
                message=f"{len(failures)} format safety issues",
                details={"failures": failures}
            )
        
        return CriticalFlowResult(
            name="Response Format Is Safe",
            passed=True,
            message="All edge cases handled safely",
        )
    
    # =========================================================================
    # CRITICAL FLOW 5: Config Changes Don't Crash
    # =========================================================================
    
    def test_config_changes_safe(self) -> CriticalFlowResult:
        """
        SCENARIO: Config files have missing/extra/wrong-type values.
        
        EXPECTED: System uses sensible defaults, never crashes.
        
        If config changes crash the bot, iteration becomes scary.
        """
        from memex_core import ResponseFormatter
        from memex_core.formatters.response_formatter import OutputConfig, UXConfig
        
        test_configs = [
            ({}, {}),  # Empty configs
            ({"length": {}}, {}),  # Partial config
            ({"length": {"max_chars": "not_a_number"}}, {}),  # Wrong type (should handle gracefully)
            ({"unknown_field": "ignored"}, {"unknown_field": "ignored"}),  # Extra fields
        ]
        
        failures = []
        
        for output_dict, ux_dict in test_configs:
            try:
                # These should not crash, even with bad input
                output_config = OutputConfig.from_dict(output_dict)
                ux_config = UXConfig.from_dict(ux_dict)
                
                formatter = ResponseFormatter(output_config, ux_config)
                
                # Should still work
                result = formatter.format_answer("test", confidence=0.8)
                if not result.text:
                    failures.append(f"Config {output_dict}: produced empty result")
                    
            except Exception as e:
                failures.append(f"Config {output_dict}: crashed with {e}")
        
        if failures:
            return CriticalFlowResult(
                name="Config Changes Don't Crash",
                passed=False,
                message=f"{len(failures)} config handling issues",
                details={"failures": failures}
            )
        
        return CriticalFlowResult(
            name="Config Changes Don't Crash",
            passed=True,
            message="All config edge cases handled gracefully",
        )
    
    # =========================================================================
    # Run All Critical Flow Tests
    # =========================================================================
    
    def run_all(self) -> bool:
        """Run all critical flow tests. Returns True if all pass."""
        tests = [
            self.test_new_decision_beats_old,
            self.test_deprecated_threads_suppressed,
            self.test_feedback_affects_ranking,
            self.test_response_format_safe,
            self.test_config_changes_safe,
        ]
        
        print("=" * 70)
        print("CRITICAL FLOW TESTS")
        print("=" * 70)
        print()
        print("These tests validate the most important user-facing behaviors.")
        print("If ANY fail, DO NOT DEPLOY.")
        print()
        print("-" * 70)
        
        all_passed = True
        
        for test_fn in tests:
            result = test_fn()
            self.results.append(result)
            
            if result.passed:
                print(f"✅ {result.name}")
                print(f"   {result.message}")
            else:
                print(f"❌ {result.name}")
                print(f"   {result.message}")
                if result.details:
                    for key, value in result.details.items():
                        print(f"   {key}: {value}")
                all_passed = False
            
            print()
        
        print("=" * 70)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"Results: {passed}/{total} critical flows passed")
        print("=" * 70)
        
        if all_passed:
            print()
            print("✅ ALL CRITICAL FLOWS PASS - Safe to deploy")
        else:
            print()
            print("❌ CRITICAL FAILURES - DO NOT DEPLOY")
            print()
            print("Fix the failures above before proceeding.")
            print("These represent user-visible bugs.")
        
        print("=" * 70)
        
        return all_passed


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Critical flow tests")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    args = parser.parse_args()
    
    suite = CriticalFlowTests(verbose=not args.quiet)
    success = suite.run_all()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

