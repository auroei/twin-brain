"""
Consolidation pipeline for memex-core.
Implements nightly synthesis: aggregates recent threads by theme into DailyInsights.

This pipeline:
1. Queries all threads from the last N hours
2. Groups them by Theme/Product
3. Uses LLM to synthesize each group into a DailyInsight
4. Stores the insights back into the vector store
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from ..models import DailyInsight, LifecycleStatus
from ..storage.vector_store import ChromaVectorStore
from ..ai.client import GeminiClient
from ..prompts import render_prompt


class ConsolidationPipeline:
    """
    Pipeline for consolidating recent threads into daily insights.
    
    Runs as a scheduled job (e.g., nightly) to synthesize scattered
    conversations into coherent summaries organized by theme.
    """
    
    def __init__(
        self,
        vector_store: ChromaVectorStore,
        llm_client: GeminiClient,
        hours_lookback: int = 24
    ):
        """
        Initialize ConsolidationPipeline.
        
        Args:
            vector_store: ChromaVectorStore instance for querying and storing
            llm_client: GeminiClient instance for synthesis
            hours_lookback: Number of hours to look back for threads (default: 24)
        """
        self.vector_store = vector_store
        self.llm_client = llm_client
        self.hours_lookback = hours_lookback
    
    def _get_recent_threads(self) -> List[Dict[str, Any]]:
        """
        Get all threads from the last N hours.
        
        Returns:
            List of thread dicts with metadata and document
        """
        # Calculate time range
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=self.hours_lookback)
        
        # Convert to Unix timestamps
        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()
        
        # Query threads in time range (only Active threads)
        threads = self.vector_store.get_threads_by_timerange(
            start_ts=start_ts,
            end_ts=end_ts,
            lifecycle_status=LifecycleStatus.ACTIVE
        )
        
        return threads
    
    def _group_threads_by_theme(
        self,
        threads: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group threads by their theme classification.
        
        Args:
            threads: List of thread dicts
            
        Returns:
            Dict mapping theme -> list of threads
        """
        grouped = defaultdict(list)
        
        for thread in threads:
            meta = thread.get("metadata", {})
            theme = meta.get("theme", "Unclassified")
            
            # Skip pending/unclassified threads
            if theme in ("Pending", "Unclassified", ""):
                continue
            
            grouped[theme].append(thread)
        
        return dict(grouped)
    
    def _synthesize_theme_insight(
        self,
        theme: str,
        threads: List[Dict[str, Any]],
        date: str
    ) -> Optional[DailyInsight]:
        """
        Use LLM to synthesize threads into a daily insight.
        
        Args:
            theme: Theme name
            threads: List of threads for this theme
            date: Date string (ISO format)
            
        Returns:
            DailyInsight or None if synthesis fails
        """
        if not threads:
            return None
        
        # Prepare thread data for the prompt
        thread_data = []
        source_thread_ids = []
        
        # Determine most common product in this theme group
        product_counts = defaultdict(int)
        
        for thread in threads:
            meta = thread.get("metadata", {})
            thread_ts = meta.get("thread_ts", "")
            source_thread_ids.append(thread_ts)
            
            product = meta.get("product", "")
            if product and product not in ("Pending", "Unclassified"):
                product_counts[product] += 1
            
            thread_data.append({
                "thread_name": meta.get("thread_name", "Untitled"),
                "summary": meta.get("summary", "No summary"),
                "project": meta.get("project", ""),
                "document": thread.get("document", "")[:500]  # Truncate for prompt
            })
        
        # Get most common product
        product = max(product_counts, key=product_counts.get) if product_counts else None
        
        # Build prompt using template
        prompt = render_prompt(
            "consolidate",
            date=date,
            theme=theme,
            product=product,
            thread_count=len(threads),
            hours=self.hours_lookback,
            threads=thread_data
        )
        
        try:
            response = self.llm_client.call_with_retry(prompt)
            
            # Extract JSON from response
            insight_match = re.search(
                r'<insight>\s*(\{.*?\})\s*</insight>',
                response,
                re.DOTALL
            )
            
            if insight_match:
                insight_json = json.loads(insight_match.group(1))
                
                return DailyInsight(
                    date=date,
                    theme=theme,
                    product=product,
                    title=insight_json.get("title", f"{theme} Daily Summary"),
                    summary=insight_json.get("summary", ""),
                    key_decisions=insight_json.get("key_decisions", []),
                    open_questions=insight_json.get("open_questions", []),
                    source_thread_ids=source_thread_ids
                )
            else:
                print(f"⚠️  Could not parse insight JSON for theme {theme}")
                return None
                
        except Exception as e:
            print(f"❌ Error synthesizing insight for {theme}: {e}")
            return None
    
    def run(self, min_threads_per_theme: int = 2) -> Dict[str, Any]:
        """
        Run the consolidation pipeline.
        
        Steps:
        1. Get all threads from the last N hours
        2. Group by theme
        3. Synthesize insights for themes with enough threads
        4. Store insights in vector store
        
        Args:
            min_threads_per_theme: Minimum threads required to create an insight
            
        Returns:
            Dict with run statistics
        """
        print(f"\n🔄 Running Consolidation Pipeline (last {self.hours_lookback} hours)")
        print("=" * 60)
        
        # Step 1: Get recent threads
        threads = self._get_recent_threads()
        print(f"📥 Found {len(threads)} threads in the last {self.hours_lookback} hours")
        
        if not threads:
            print("   No threads to consolidate")
            return {
                "threads_processed": 0,
                "themes_found": 0,
                "insights_created": 0
            }
        
        # Step 2: Group by theme
        grouped = self._group_threads_by_theme(threads)
        print(f"📂 Grouped into {len(grouped)} themes:")
        for theme, theme_threads in grouped.items():
            print(f"   - {theme}: {len(theme_threads)} threads")
        
        # Step 3: Synthesize insights
        date = datetime.now().strftime("%Y-%m-%d")
        insights_created = 0
        
        for theme, theme_threads in grouped.items():
            if len(theme_threads) < min_threads_per_theme:
                print(f"⏭️  Skipping {theme} ({len(theme_threads)} threads < {min_threads_per_theme} minimum)")
                continue
            
            print(f"\n📊 Synthesizing insight for {theme}...")
            insight = self._synthesize_theme_insight(theme, theme_threads, date)
            
            if insight:
                # Step 4: Store insight
                self.vector_store.upsert_daily_insight(insight)
                insights_created += 1
                print(f"   ✅ Created: {insight.title}")
                print(f"      Key decisions: {len(insight.key_decisions)}")
                print(f"      Open questions: {len(insight.open_questions)}")
        
        print("\n" + "=" * 60)
        print(f"✅ Consolidation complete: {insights_created} insights created")
        
        return {
            "threads_processed": len(threads),
            "themes_found": len(grouped),
            "insights_created": insights_created
        }
    
    def run_for_theme(self, theme: str) -> Optional[DailyInsight]:
        """
        Run consolidation for a specific theme only.
        
        Args:
            theme: Theme to consolidate
            
        Returns:
            DailyInsight if created, None otherwise
        """
        threads = self._get_recent_threads()
        grouped = self._group_threads_by_theme(threads)
        
        if theme not in grouped:
            print(f"⚠️  No recent threads found for theme: {theme}")
            return None
        
        date = datetime.now().strftime("%Y-%m-%d")
        insight = self._synthesize_theme_insight(theme, grouped[theme], date)
        
        if insight:
            self.vector_store.upsert_daily_insight(insight)
        
        return insight

