"""
Maintenance pipeline for memex-core.
Implements background tasks for keeping the knowledge base healthy.

This pipeline handles:
1. Re-classification: Re-run classifier on old threads when prompts improve
2. Schema migration: Add new fields to old threads when model evolves
3. Stale detection: Mark old threads for review
4. Batch lifecycle updates: Bulk update lifecycle statuses
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable

from ..models import RoleDefinition, ThreadClassification, SlackThread, SlackMessage, LifecycleStatus
from ..storage.vector_store import ChromaVectorStore
from ..ai.classifier import ThreadClassifier
from ..utils import format_thread


class MaintenancePipeline:
    """
    Pipeline for maintenance tasks on the knowledge base.
    
    Runs as a scheduled job or on-demand to keep data fresh and consistent.
    """
    
    def __init__(
        self,
        vector_store: ChromaVectorStore,
        classifier: Optional[ThreadClassifier] = None
    ):
        """
        Initialize MaintenancePipeline.
        
        Args:
            vector_store: ChromaVectorStore instance
            classifier: Optional ThreadClassifier for re-classification tasks
        """
        self.vector_store = vector_store
        self.classifier = classifier
    
    def reclassify_threads(
        self,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        filter_fn: Optional[Callable[[Dict], bool]] = None,
        batch_size: int = 10,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Re-classify threads that match a filter condition.
        
        Use cases:
        - Re-classify threads after improving the classification prompt
        - Re-classify threads with specific themes after adding new themes
        - Re-classify old "Unclassified" threads
        
        Args:
            role_def: RoleDefinition for classification
            behavior_config: Optional behavior configuration
            filter_fn: Optional function (metadata -> bool) to filter threads to process
            batch_size: Number of threads to process per batch
            dry_run: If True, don't actually update, just report what would change
            
        Returns:
            Dict with statistics about the reclassification run
        """
        if not self.classifier:
            raise ValueError("Classifier not provided - cannot reclassify")
        
        print(f"\n🔄 Running Reclassification Pipeline {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        
        # Get all threads
        all_results = self.vector_store.collection.get()
        
        if not all_results["ids"]:
            print("   No threads found")
            return {"total": 0, "processed": 0, "updated": 0, "errors": 0}
        
        total = len(all_results["ids"])
        processed = 0
        updated = 0
        errors = 0
        
        print(f"📥 Found {total} threads total")
        
        for i, (thread_id, doc, meta) in enumerate(zip(
            all_results["ids"],
            all_results["documents"],
            all_results["metadatas"]
        )):
            # Skip non-thread documents (e.g., daily insights)
            if not thread_id.startswith("thread_"):
                continue
            
            # Apply filter if provided
            if filter_fn and not filter_fn(meta):
                continue
            
            processed += 1
            thread_ts = meta.get("thread_ts", thread_id.replace("thread_", ""))
            
            try:
                # Extract original thread text (remove context prefix if present)
                original_doc = doc
                if "\n\n---\n\n" in doc:
                    original_doc = doc.split("\n\n---\n\n", 1)[1]
                
                # Classify the thread
                new_classification = self.classifier.classify_thread(
                    original_doc,
                    role_def,
                    behavior_config=behavior_config,
                    vector_store=self.vector_store
                )
                
                # Check if classification changed
                old_theme = meta.get("theme", "")
                old_product = meta.get("product", "")
                
                changed = (
                    new_classification.theme != old_theme or
                    new_classification.product != old_product
                )
                
                if changed:
                    print(f"   [{processed}] {thread_ts}: {old_theme}/{old_product} → {new_classification.theme}/{new_classification.product}")
                    
                    if not dry_run:
                        # Preserve lifecycle status from existing metadata
                        existing_status = meta.get("lifecycle_status", LifecycleStatus.ACTIVE.value)
                        try:
                            new_classification.lifecycle_status = LifecycleStatus(existing_status)
                        except ValueError:
                            new_classification.lifecycle_status = LifecycleStatus.ACTIVE
                        
                        self.vector_store.update_thread_classification(
                            thread_ts,
                            new_classification
                        )
                    
                    updated += 1
                else:
                    if processed % batch_size == 0:
                        print(f"   Processed {processed} threads...")
                        
            except Exception as e:
                print(f"   ❌ Error processing {thread_ts}: {e}")
                errors += 1
        
        print("\n" + "=" * 60)
        print(f"✅ Reclassification complete:")
        print(f"   Processed: {processed}")
        print(f"   Updated: {updated}")
        print(f"   Errors: {errors}")
        
        return {
            "total": total,
            "processed": processed,
            "updated": updated,
            "errors": errors
        }
    
    def reclassify_unclassified(
        self,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Convenience method to reclassify threads marked as "Unclassified" or "Pending".
        
        Args:
            role_def: RoleDefinition for classification
            behavior_config: Optional behavior configuration
            dry_run: If True, don't actually update
            
        Returns:
            Dict with statistics
        """
        def filter_unclassified(meta: Dict) -> bool:
            theme = meta.get("theme", "")
            return theme in ("Unclassified", "Pending", "")
        
        return self.reclassify_threads(
            role_def=role_def,
            behavior_config=behavior_config,
            filter_fn=filter_unclassified,
            dry_run=dry_run
        )
    
    def retry_pending_threads(
        self,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        max_age_hours: int = 24,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Retry classification for threads stuck in "Pending" status.
        
        This handles cases where classification failed silently during
        initial ingestion. Only retries threads older than a few minutes
        to avoid interfering with active classification.
        
        Args:
            role_def: RoleDefinition for classification
            behavior_config: Optional behavior configuration
            max_age_hours: Only retry threads up to this age (default 24h)
            dry_run: If True, don't actually update
            
        Returns:
            Dict with statistics
        """
        print(f"\n🔄 Retrying Pending Threads (up to {max_age_hours}h old) {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        
        from datetime import datetime
        
        now = datetime.now()
        min_age_minutes = 10  # Skip threads classified within last 10 min
        
        def filter_stuck_pending(meta: Dict) -> bool:
            # Must be Pending
            theme = meta.get("theme", "")
            if theme != "Pending":
                return False
            
            # Check thread age (from thread_ts)
            thread_ts = meta.get("thread_ts", "")
            if not thread_ts:
                return False
            
            try:
                ts_float = float(thread_ts)
                thread_age_hours = (now.timestamp() - ts_float) / 3600
                
                # Skip if too new (probably still being classified)
                if thread_age_hours < (min_age_minutes / 60):
                    return False
                
                # Skip if too old
                if thread_age_hours > max_age_hours:
                    return False
                
                return True
            except (ValueError, TypeError):
                return False
        
        return self.reclassify_threads(
            role_def=role_def,
            behavior_config=behavior_config,
            filter_fn=filter_stuck_pending,
            dry_run=dry_run
        )
    
    def mark_stale_threads(
        self,
        days_threshold: int = 180,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Mark threads older than threshold as needing review.
        
        Adds a 'needs_review' flag to metadata for threads that haven't
        been updated in a long time.
        
        Args:
            days_threshold: Age in days after which threads are considered stale
            dry_run: If True, don't actually update
            
        Returns:
            Dict with statistics
        """
        print(f"\n🕐 Marking Stale Threads (>{days_threshold} days old) {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        
        cutoff_date = datetime.now() - timedelta(days=days_threshold)
        cutoff_ts = cutoff_date.timestamp()
        
        # Get all threads
        all_results = self.vector_store.collection.get()
        
        marked = 0
        already_marked = 0
        
        for thread_id, doc, meta in zip(
            all_results.get("ids", []),
            all_results.get("documents", []),
            all_results.get("metadatas", [])
        ):
            if not thread_id.startswith("thread_"):
                continue
            
            thread_ts = meta.get("thread_ts", "")
            
            try:
                ts_float = float(thread_ts)
                
                if ts_float < cutoff_ts:
                    # Thread is old
                    if meta.get("needs_review"):
                        already_marked += 1
                        continue
                    
                    thread_name = meta.get("thread_name", "Unknown")
                    print(f"   📋 {thread_ts}: {thread_name}")
                    
                    if not dry_run:
                        meta["needs_review"] = True
                        meta["stale_marked_at"] = datetime.now().isoformat()
                        
                        self.vector_store.collection.upsert(
                            ids=[thread_id],
                            documents=[doc],
                            metadatas=[meta]
                        )
                    
                    marked += 1
                    
            except (ValueError, TypeError):
                continue
        
        print("\n" + "=" * 60)
        print(f"✅ Stale marking complete:")
        print(f"   Newly marked: {marked}")
        print(f"   Already marked: {already_marked}")
        
        return {
            "marked": marked,
            "already_marked": already_marked
        }
    
    def bulk_update_lifecycle(
        self,
        thread_ids: List[str],
        new_status: LifecycleStatus,
        superseded_by: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Bulk update lifecycle status for multiple threads.
        
        Args:
            thread_ids: List of thread timestamps to update
            new_status: New lifecycle status to set
            superseded_by: Optional thread ID that supersedes these
            dry_run: If True, don't actually update
            
        Returns:
            Dict with statistics
        """
        print(f"\n🔄 Bulk Lifecycle Update → {new_status.value} {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        
        updated = 0
        errors = 0
        
        for thread_ts in thread_ids:
            try:
                print(f"   {thread_ts} → {new_status.value}")
                
                if not dry_run:
                    success = self.vector_store.update_lifecycle_status(
                        thread_ts,
                        new_status,
                        superseded_by=superseded_by
                    )
                    if success:
                        updated += 1
                    else:
                        errors += 1
                else:
                    updated += 1
                    
            except Exception as e:
                print(f"   ❌ Error updating {thread_ts}: {e}")
                errors += 1
        
        print("\n" + "=" * 60)
        print(f"✅ Bulk update complete: {updated} updated, {errors} errors")
        
        return {
            "updated": updated,
            "errors": errors
        }
    
    def migrate_schema(
        self,
        field_defaults: Dict[str, Any],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Add new fields with default values to existing threads.
        
        Use when adding new fields to the schema (e.g., lifecycle_status)
        and need to backfill existing data.
        
        Args:
            field_defaults: Dict of field_name -> default_value
            dry_run: If True, don't actually update
            
        Returns:
            Dict with statistics
        """
        print(f"\n📦 Schema Migration {'(DRY RUN)' if dry_run else ''}")
        print(f"   Adding fields: {list(field_defaults.keys())}")
        print("=" * 60)
        
        all_results = self.vector_store.collection.get()
        
        migrated = 0
        skipped = 0
        
        for thread_id, doc, meta in zip(
            all_results.get("ids", []),
            all_results.get("documents", []),
            all_results.get("metadatas", [])
        ):
            needs_update = False
            
            for field, default in field_defaults.items():
                if field not in meta or meta[field] is None:
                    meta[field] = default
                    needs_update = True
            
            if needs_update:
                if not dry_run:
                    self.vector_store.collection.upsert(
                        ids=[thread_id],
                        documents=[doc],
                        metadatas=[meta]
                    )
                migrated += 1
            else:
                skipped += 1
        
        print(f"✅ Migration complete: {migrated} updated, {skipped} already had fields")
        
        return {
            "migrated": migrated,
            "skipped": skipped
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the knowledge base.
        
        Returns:
            Dict with various statistics
        """
        all_results = self.vector_store.collection.get()
        
        total = len(all_results.get("ids", []))
        threads = 0
        insights = 0
        
        themes = {}
        products = {}
        lifecycle_counts = {
            LifecycleStatus.ACTIVE.value: 0,
            LifecycleStatus.DEPRECATED.value: 0,
            LifecycleStatus.DRAFT.value: 0
        }
        unclassified = 0
        pending = 0
        needs_review = 0
        
        for thread_id, meta in zip(
            all_results.get("ids", []),
            all_results.get("metadatas", [])
        ):
            if thread_id.startswith("thread_"):
                threads += 1
            elif thread_id.startswith("insight_"):
                insights += 1
            
            theme = meta.get("theme", "Unknown")
            themes[theme] = themes.get(theme, 0) + 1
            
            product = meta.get("product", "Unknown")
            products[product] = products.get(product, 0) + 1
            
            status = meta.get("lifecycle_status", LifecycleStatus.ACTIVE.value)
            lifecycle_counts[status] = lifecycle_counts.get(status, 0) + 1
            
            if theme == "Unclassified":
                unclassified += 1
            elif theme == "Pending":
                pending += 1
            
            if meta.get("needs_review"):
                needs_review += 1
        
        return {
            "total_documents": total,
            "threads": threads,
            "daily_insights": insights,
            "themes": themes,
            "products": products,
            "lifecycle": lifecycle_counts,
            "unclassified": unclassified,
            "pending": pending,
            "needs_review": needs_review
        }

