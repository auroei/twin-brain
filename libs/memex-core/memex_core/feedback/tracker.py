"""
Feedback tracker for memex-core.
Collects reactions, implicit signals, and expert reviews.
"""

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

# Cache bounds to prevent memory leaks
MAX_ANSWER_CACHE_SIZE = 1000
MAX_RECENT_ANSWERS_PER_USER = 50


class FeedbackType(str, Enum):
    """Types of feedback signals."""
    REACTION_POSITIVE = "reaction_positive"
    REACTION_NEGATIVE = "reaction_negative"
    FOLLOWUP_QUESTION = "followup_question"
    REPHRASE = "rephrase"
    REPEATED_QUESTION = "repeated_question"
    EXPERT_REVIEW = "expert_review"


@dataclass
class FeedbackEntry:
    """A single feedback entry."""
    id: str
    timestamp: str
    feedback_type: str
    user_id: str
    question: str
    answer: str
    answer_message_ts: str
    channel_id: str
    confidence_score: float = 0.0
    source_thread_count: int = 0
    reaction: Optional[str] = None
    expert_review: Optional[Dict[str, str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0  # Feedback weight (curators: 3.0, users: 1.0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeedbackEntry":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ReviewItem:
    """An item pending expert review."""
    id: str
    created_at: str
    question: str
    answer: str
    answer_message_ts: str
    channel_id: str
    user_id: str
    confidence_score: float
    source_thread_count: int
    trigger_reason: str  # "negative_reaction", "low_confidence", "random_sample"
    reactions: List[str] = field(default_factory=list)
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_result: Optional[Dict[str, str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewItem":
        """Create from dictionary."""
        return cls(**data)


class FeedbackTracker:
    """
    Tracks user feedback on bot answers.
    
    Collects:
    - Explicit reactions (👍/👎)
    - Implicit signals (followups, rephrases)
    - Expert reviews
    
    Stores:
    - Append-only log (feedback_log.jsonl)
    - Review queue (review_queue.json)
    """
    
    def __init__(
        self,
        feedback_config: Dict[str, Any],
        storage_dir: str,
        curator_ids: Optional[Set[str]] = None,
        teacher_ids: Optional[Set[str]] = None
    ):
        """
        Initialize FeedbackTracker.
        
        Args:
            feedback_config: Feedback configuration dict from feedback.yaml
            storage_dir: Directory for storing feedback files
            curator_ids: Set of curator user IDs (5x weighted feedback + L2)
            teacher_ids: Set of teacher user IDs (5x weighted feedback + L2)
        """
        self.config = feedback_config
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Store role IDs for weighted feedback
        self.curator_ids = curator_ids or set()
        self.teacher_ids = teacher_ids or set()
        
        # Determine reviewers (curators are the expert reviewers)
        reviewers_config = feedback_config.get("curated_review", {}).get("reviewers", "curators")
        if reviewers_config in ("allowed_users", "curators"):
            self.reviewers = self.curator_ids
        elif isinstance(reviewers_config, list):
            self.reviewers = set(reviewers_config)
        else:
            self.reviewers = self.curator_ids
        
        # File paths
        storage_config = feedback_config.get("storage", {})
        self.log_file = self.storage_dir / storage_config.get("file", "feedback_log.jsonl")
        self.queue_file = self.storage_dir / storage_config.get("review_queue", "review_queue.json")
        
        # Reaction mappings
        reactions_config = feedback_config.get("reactions", {})
        self.positive_reactions = set(reactions_config.get("positive", ["thumbsup", "+1"]))
        self.negative_reactions = set(reactions_config.get("negative", ["thumbsdown", "-1"]))
        
        # Feedback weight config (three-role system)
        weights_config = feedback_config.get("weights", {})
        self.curator_weight = weights_config.get("curator", 5.0)
        self.teacher_weight = weights_config.get("teacher", 5.0)
        self.user_weight = weights_config.get("user", 1.0)
        
        # Reinforcement config
        reinforcement_config = feedback_config.get("reinforcement", {})
        self.positive_delta = reinforcement_config.get("positive_delta", 0.1)
        self.negative_delta = reinforcement_config.get("negative_delta", -0.05)
        self.score_min = reinforcement_config.get("score_min", -1.0)
        self.score_max = reinforcement_config.get("score_max", 2.0)
        
        # Recent answers cache for implicit signal tracking
        # Maps user_id -> list of (timestamp, question, answer_ts)
        self._recent_answers: Dict[str, List[tuple]] = {}
        self._answer_cache: Dict[str, Dict[str, Any]] = {}  # answer_ts -> answer data
        
        # Log rotation config (10MB default, keep 5 old files)
        storage_config = feedback_config.get("storage", {})
        self._max_log_size_bytes = storage_config.get("max_log_size_mb", 10) * 1024 * 1024
        self._max_log_backups = storage_config.get("max_log_backups", 5)
        
        # Load existing review queue
        self._review_queue = self._load_review_queue()
    
    def _get_feedback_weight(self, user_id: str) -> float:
        """
        Get the feedback weight for a user based on their role.
        
        Three-role system:
        - Curators: 5x weight + L2 reinforcement
        - Teachers: 5x weight + L2 reinforcement
        - Users: 1x weight (logged only, no L2 reinforcement)
        
        Args:
            user_id: The user's ID
            
        Returns:
            Feedback weight multiplier
        """
        if user_id in self.curator_ids:
            return self.curator_weight
        if user_id in self.teacher_ids:
            return self.teacher_weight
        return self.user_weight
    
    def _load_review_queue(self) -> List[ReviewItem]:
        """Load the review queue from file."""
        if self.queue_file.exists():
            try:
                with open(self.queue_file, 'r') as f:
                    data = json.load(f)
                    return [ReviewItem.from_dict(item) for item in data.get("items", [])]
            except Exception as e:
                print(f"⚠️ Error loading review queue: {e}")
                return []
        return []
    
    def _save_review_queue(self) -> None:
        """Save the review queue to file."""
        try:
            with open(self.queue_file, 'w') as f:
                json.dump({
                    "items": [item.to_dict() for item in self._review_queue],
                    "last_updated": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving review queue: {e}")
    
    def _rotate_log_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if not self.log_file.exists():
            return
        
        try:
            if self.log_file.stat().st_size < self._max_log_size_bytes:
                return
            
            # Rotate existing backups
            for i in range(self._max_log_backups - 1, 0, -1):
                old_backup = self.log_file.with_suffix(f".{i}.jsonl")
                new_backup = self.log_file.with_suffix(f".{i + 1}.jsonl")
                if old_backup.exists():
                    if i + 1 >= self._max_log_backups:
                        old_backup.unlink()  # Delete oldest
                    else:
                        shutil.move(str(old_backup), str(new_backup))
            
            # Move current log to .1.jsonl
            backup_path = self.log_file.with_suffix(".1.jsonl")
            shutil.move(str(self.log_file), str(backup_path))
            print(f"📂 Rotated feedback log (exceeded {self._max_log_size_bytes // (1024*1024)}MB)")
            
        except Exception as e:
            print(f"⚠️ Error rotating log file: {e}")
    
    def _append_to_log(self, entry: FeedbackEntry) -> None:
        """Append a feedback entry to the log file."""
        try:
            self._rotate_log_if_needed()
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            print(f"❌ Error appending to feedback log: {e}")
    
    def _should_add_to_review_queue(
        self,
        trigger_reason: str,
        confidence_score: float
    ) -> bool:
        """Determine if an answer should be added to review queue."""
        sampling_config = self.config.get("curated_review", {}).get("sampling", {})
        
        if trigger_reason == "negative_reaction":
            return sampling_config.get("review_negative_reactions", True)
        
        if trigger_reason == "low_confidence":
            threshold = sampling_config.get("confidence_threshold", 0.5)
            return sampling_config.get("review_low_confidence", True) and confidence_score < threshold
        
        if trigger_reason == "random_sample":
            import random
            rate = sampling_config.get("random_sample_rate", 0.1)
            return random.random() < rate
        
        return False
    
    def track_answer(
        self,
        user_id: str,
        question: str,
        answer: str,
        answer_message_ts: str,
        channel_id: str,
        confidence_score: float = 0.0,
        source_thread_count: int = 0,
        source_thread_ids: Optional[List[str]] = None
    ) -> None:
        """
        Track a bot answer for potential feedback collection.
        
        Call this immediately after sending an answer to a user.
        
        Args:
            user_id: User who asked the question
            question: The question asked
            answer: The bot's answer
            answer_message_ts: Slack message timestamp of the answer
            channel_id: Channel where answer was sent
            confidence_score: Confidence in the answer (0-1)
            source_thread_count: Number of threads used as sources
            source_thread_ids: List of thread timestamps used as sources (for L2 reinforcement)
        """
        now = datetime.now()
        
        # Cache the answer for implicit signal tracking and L2 reinforcement
        self._answer_cache[answer_message_ts] = {
            "user_id": user_id,
            "question": question,
            "answer": answer,
            "channel_id": channel_id,
            "confidence_score": confidence_score,
            "source_thread_count": source_thread_count,
            "source_thread_ids": source_thread_ids or [],
            "timestamp": now.isoformat()
        }
        
        # Evict oldest entries if cache exceeds max size
        if len(self._answer_cache) > MAX_ANSWER_CACHE_SIZE:
            # Sort by timestamp and remove oldest 10%
            sorted_items = sorted(
                self._answer_cache.items(),
                key=lambda x: x[1].get("timestamp", "")
            )
            num_to_remove = max(1, len(sorted_items) // 10)
            for key, _ in sorted_items[:num_to_remove]:
                del self._answer_cache[key]
            print(f"🧹 Evicted {num_to_remove} old entries from answer cache")
        
        # Track for followup detection
        if user_id not in self._recent_answers:
            self._recent_answers[user_id] = []
        self._recent_answers[user_id].append((now, question, answer_message_ts))
        
        # Clean up old entries (keep last hour) and enforce per-user limit
        cutoff = now - timedelta(hours=1)
        self._recent_answers[user_id] = [
            (ts, q, ats) for ts, q, ats in self._recent_answers[user_id]
            if ts > cutoff
        ][-MAX_RECENT_ANSWERS_PER_USER:]
        
        # Check if should add to review queue (random sample or low confidence)
        if self._should_add_to_review_queue("low_confidence", confidence_score):
            self._add_to_review_queue(
                question=question,
                answer=answer,
                answer_message_ts=answer_message_ts,
                channel_id=channel_id,
                user_id=user_id,
                confidence_score=confidence_score,
                source_thread_count=source_thread_count,
                trigger_reason="low_confidence"
            )
        elif self._should_add_to_review_queue("random_sample", confidence_score):
            self._add_to_review_queue(
                question=question,
                answer=answer,
                answer_message_ts=answer_message_ts,
                channel_id=channel_id,
                user_id=user_id,
                confidence_score=confidence_score,
                source_thread_count=source_thread_count,
                trigger_reason="random_sample"
            )
    
    def _add_to_review_queue(
        self,
        question: str,
        answer: str,
        answer_message_ts: str,
        channel_id: str,
        user_id: str,
        confidence_score: float,
        source_thread_count: int,
        trigger_reason: str,
        reactions: Optional[List[str]] = None
    ) -> None:
        """Add an item to the review queue."""
        # Check if already in queue
        for item in self._review_queue:
            if item.answer_message_ts == answer_message_ts:
                # Update existing item
                if reactions:
                    item.reactions.extend(reactions)
                return
        
        # Add new item
        review_item = ReviewItem(
            id=str(uuid.uuid4()),
            created_at=datetime.now().isoformat(),
            question=question,
            answer=answer,
            answer_message_ts=answer_message_ts,
            channel_id=channel_id,
            user_id=user_id,
            confidence_score=confidence_score,
            source_thread_count=source_thread_count,
            trigger_reason=trigger_reason,
            reactions=reactions or []
        )
        
        self._review_queue.append(review_item)
        self._save_review_queue()
        print(f"📋 Added to review queue: {trigger_reason}")
    
    def record_reaction(
        self,
        reaction: str,
        user_id: str,
        message_ts: str,
        channel_id: str
    ) -> Optional[FeedbackEntry]:
        """
        Record a reaction on a bot answer.
        
        Args:
            reaction: The reaction emoji name
            user_id: User who reacted
            message_ts: Message timestamp that was reacted to
            channel_id: Channel where reaction occurred
            
        Returns:
            FeedbackEntry if this was a tracked answer, None otherwise
        """
        # Check if this is a tracked answer
        if message_ts not in self._answer_cache:
            return None
        
        answer_data = self._answer_cache[message_ts]
        
        # Determine reaction type
        is_positive = reaction in self.positive_reactions
        is_negative = reaction in self.negative_reactions
        
        if not is_positive and not is_negative:
            return None  # Not a feedback reaction
        
        feedback_type = FeedbackType.REACTION_POSITIVE if is_positive else FeedbackType.REACTION_NEGATIVE
        
        # Get feedback weight based on user role
        weight = self._get_feedback_weight(user_id)
        
        # Create feedback entry with weight
        entry = FeedbackEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            feedback_type=feedback_type.value,
            user_id=user_id,
            question=answer_data["question"],
            answer=answer_data["answer"],
            answer_message_ts=message_ts,
            channel_id=channel_id,
            confidence_score=answer_data.get("confidence_score", 0.0),
            source_thread_count=answer_data.get("source_thread_count", 0),
            reaction=reaction,
            weight=weight
        )
        
        # Log the feedback
        self._append_to_log(entry)
        
        # Add to review queue if negative
        if is_negative and self._should_add_to_review_queue("negative_reaction", 0):
            self._add_to_review_queue(
                question=answer_data["question"],
                answer=answer_data["answer"],
                answer_message_ts=message_ts,
                channel_id=channel_id,
                user_id=answer_data["user_id"],
                confidence_score=answer_data.get("confidence_score", 0.0),
                source_thread_count=answer_data.get("source_thread_count", 0),
                trigger_reason="negative_reaction",
                reactions=[reaction]
            )
        
        weight_label = "curator" if user_id in self.curator_ids else "user"
        print(f"{'👍' if is_positive else '👎'} Recorded {feedback_type.value} from {user_id} (weight: {weight}x {weight_label})")
        return entry
    
    def apply_reinforcement(
        self,
        vector_store,
        message_ts: str,
        is_positive: bool,
        weight: float
    ) -> bool:
        """
        Apply L2 reinforcement: boost or penalize source threads based on feedback.
        
        This updates the feedback_score in thread metadata, which affects
        future retrieval ranking.
        
        Args:
            vector_store: ChromaVectorStore instance for updating thread metadata
            message_ts: Message timestamp of the answer that received feedback
            is_positive: Whether the feedback was positive
            weight: Feedback weight (curator: 3.0, user: 1.0)
            
        Returns:
            True if reinforcement was applied, False otherwise
        """
        if message_ts not in self._answer_cache:
            return False
        
        answer_data = self._answer_cache[message_ts]
        source_threads = answer_data.get("source_thread_ids", [])
        
        if not source_threads:
            print(f"⚠️ No source threads to reinforce for message {message_ts}")
            return False
        
        # Calculate delta based on feedback type and weight
        if is_positive:
            delta = self.positive_delta * weight
        else:
            delta = self.negative_delta * weight
        
        # Apply reinforcement to each source thread
        updated_count = 0
        for thread_ts in source_threads:
            if thread_ts:  # Skip None/empty values
                if vector_store.update_feedback_score(thread_ts, delta):
                    updated_count += 1
        
        if updated_count > 0:
            sign = "+" if delta > 0 else ""
            print(f"🔄 L2 reinforcement: {sign}{delta:.3f} applied to {updated_count}/{len(source_threads)} threads")
        
        return updated_count > 0
    
    def check_for_followup(
        self,
        user_id: str,
        new_question: str,
        timestamp: datetime
    ) -> Optional[FeedbackEntry]:
        """
        Check if a new question is a followup to a recent answer.
        
        Args:
            user_id: User asking the question
            new_question: The new question
            timestamp: When the question was asked
            
        Returns:
            FeedbackEntry if this is a followup, None otherwise
        """
        if not self.config.get("implicit_signals", {}).get("track_followup_questions", True):
            return None
        
        if user_id not in self._recent_answers:
            return None
        
        window_seconds = self.config.get("implicit_signals", {}).get("followup_window_seconds", 120)
        cutoff = timestamp - timedelta(seconds=window_seconds)
        
        # Find recent answers within window
        for answer_ts, prev_question, answer_message_ts in reversed(self._recent_answers[user_id]):
            if answer_ts < cutoff:
                continue
            
            # Check if it's a followup (different question within window)
            if self._is_similar(prev_question, new_question):
                # This is a rephrase, not a followup
                continue
            
            # This is a followup - previous answer may have been incomplete
            if answer_message_ts in self._answer_cache:
                answer_data = self._answer_cache[answer_message_ts]
                
                entry = FeedbackEntry(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now().isoformat(),
                    feedback_type=FeedbackType.FOLLOWUP_QUESTION.value,
                    user_id=user_id,
                    question=answer_data["question"],
                    answer=answer_data["answer"],
                    answer_message_ts=answer_message_ts,
                    channel_id=answer_data["channel_id"],
                    confidence_score=answer_data.get("confidence_score", 0.0),
                    source_thread_count=answer_data.get("source_thread_count", 0),
                    metadata={"followup_question": new_question}
                )
                
                self._append_to_log(entry)
                print(f"📝 Detected followup question from {user_id}")
                return entry
        
        return None
    
    def check_for_rephrase(
        self,
        user_id: str,
        new_question: str,
        timestamp: datetime
    ) -> Optional[FeedbackEntry]:
        """
        Check if a new question is a rephrase of a recent question.
        
        Args:
            user_id: User asking the question
            new_question: The new question
            timestamp: When the question was asked
            
        Returns:
            FeedbackEntry if this is a rephrase, None otherwise
        """
        if not self.config.get("implicit_signals", {}).get("track_rephrases", True):
            return None
        
        if user_id not in self._recent_answers:
            return None
        
        window_seconds = self.config.get("implicit_signals", {}).get("followup_window_seconds", 120)
        cutoff = timestamp - timedelta(seconds=window_seconds)
        
        for answer_ts, prev_question, answer_message_ts in reversed(self._recent_answers[user_id]):
            if answer_ts < cutoff:
                continue
            
            # Check similarity
            if self._is_similar(prev_question, new_question):
                if answer_message_ts in self._answer_cache:
                    answer_data = self._answer_cache[answer_message_ts]
                    
                    entry = FeedbackEntry(
                        id=str(uuid.uuid4()),
                        timestamp=datetime.now().isoformat(),
                        feedback_type=FeedbackType.REPHRASE.value,
                        user_id=user_id,
                        question=answer_data["question"],
                        answer=answer_data["answer"],
                        answer_message_ts=answer_message_ts,
                        channel_id=answer_data["channel_id"],
                        confidence_score=answer_data.get("confidence_score", 0.0),
                        source_thread_count=answer_data.get("source_thread_count", 0),
                        metadata={"rephrased_question": new_question}
                    )
                    
                    self._append_to_log(entry)
                    print(f"🔄 Detected rephrase from {user_id}")
                    return entry
        
        return None
    
    def _is_similar(self, text1: str, text2: str) -> bool:
        """
        Check if two texts are similar (simple word overlap).
        
        For production, consider using embeddings.
        """
        threshold = self.config.get("implicit_signals", {}).get("rephrase_similarity_threshold", 0.7)
        
        # Simple word overlap
        words1 = set(re.findall(r'\w+', text1.lower()))
        words2 = set(re.findall(r'\w+', text2.lower()))
        
        if not words1 or not words2:
            return False
        
        intersection = words1 & words2
        union = words1 | words2
        
        jaccard = len(intersection) / len(union)
        return jaccard >= threshold
    
    def record_expert_review(
        self,
        review_item_id: str,
        reviewer_id: str,
        review_result: Dict[str, str]
    ) -> Optional[FeedbackEntry]:
        """
        Record an expert review.
        
        Args:
            review_item_id: ID of the review item
            reviewer_id: User ID of the reviewer
            review_result: Dict mapping criteria IDs to selected options
            
        Returns:
            FeedbackEntry if successful, None otherwise
        """
        # Verify reviewer is authorized
        if reviewer_id not in self.reviewers:
            print(f"⚠️ Unauthorized review attempt by {reviewer_id}")
            return None
        
        # Find the review item
        for item in self._review_queue:
            if item.id == review_item_id:
                item.reviewed = True
                item.reviewed_by = reviewer_id
                item.reviewed_at = datetime.now().isoformat()
                item.review_result = review_result
                
                # Save updated queue
                self._save_review_queue()
                
                # Log the review
                entry = FeedbackEntry(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now().isoformat(),
                    feedback_type=FeedbackType.EXPERT_REVIEW.value,
                    user_id=item.user_id,
                    question=item.question,
                    answer=item.answer,
                    answer_message_ts=item.answer_message_ts,
                    channel_id=item.channel_id,
                    confidence_score=item.confidence_score,
                    source_thread_count=item.source_thread_count,
                    expert_review=review_result,
                    metadata={"reviewer_id": reviewer_id}
                )
                
                self._append_to_log(entry)
                print(f"✅ Expert review recorded by {reviewer_id}")
                return entry
        
        return None
    
    def get_pending_reviews(self, limit: int = 10) -> List[ReviewItem]:
        """Get pending items for review."""
        pending = [item for item in self._review_queue if not item.reviewed]
        return pending[:limit]
    
    def get_review_stats(self) -> Dict[str, Any]:
        """Get statistics about reviews."""
        total = len(self._review_queue)
        reviewed = sum(1 for item in self._review_queue if item.reviewed)
        pending = total - reviewed
        
        # Count by trigger reason
        by_reason = {}
        for item in self._review_queue:
            reason = item.trigger_reason
            by_reason[reason] = by_reason.get(reason, 0) + 1
        
        # Count review results
        review_results = {
            "correct": 0,
            "partially_correct": 0,
            "incorrect": 0
        }
        for item in self._review_queue:
            if item.review_result:
                correctness = item.review_result.get("correctness", "")
                if correctness in review_results:
                    review_results[correctness] += 1
        
        return {
            "total_items": total,
            "reviewed": reviewed,
            "pending": pending,
            "by_trigger_reason": by_reason,
            "review_results": review_results
        }
    
    def get_feedback_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Get a summary of feedback from the last N days.
        
        Args:
            days: Number of days to look back
            
        Returns:
            Summary dict with counts and rates
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        summary = {
            "period_days": days,
            "reaction_positive": 0,
            "reaction_negative": 0,
            "followups": 0,
            "rephrases": 0,
            "expert_reviews": 0,
            "total_answers_tracked": len(self._answer_cache)
        }
        
        # Read from log file
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            entry_time = datetime.fromisoformat(entry["timestamp"])
                            if entry_time < cutoff:
                                continue
                            
                            fb_type = entry.get("feedback_type", "")
                            if fb_type == FeedbackType.REACTION_POSITIVE.value:
                                summary["reaction_positive"] += 1
                            elif fb_type == FeedbackType.REACTION_NEGATIVE.value:
                                summary["reaction_negative"] += 1
                            elif fb_type == FeedbackType.FOLLOWUP_QUESTION.value:
                                summary["followups"] += 1
                            elif fb_type == FeedbackType.REPHRASE.value:
                                summary["rephrases"] += 1
                            elif fb_type == FeedbackType.EXPERT_REVIEW.value:
                                summary["expert_reviews"] += 1
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ Error reading feedback log: {e}")
        
        # Calculate rates
        total_reactions = summary["reaction_positive"] + summary["reaction_negative"]
        if total_reactions > 0:
            summary["positive_rate"] = summary["reaction_positive"] / total_reactions
            summary["negative_rate"] = summary["reaction_negative"] / total_reactions
        
        return summary

