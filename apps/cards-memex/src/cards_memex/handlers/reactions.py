"""Handler for reaction events in Slack.

Tracks reactions on bot messages for feedback and applies L2 reinforcement.
"""
from typing import Union

from cards_memex.rbac import get_user_role
from cards_memex.config_models import FeedbackConfig


def create_reaction_handler(
    feedback_config: Union[FeedbackConfig, dict],
    feedback_tracker,
    store,
    curator_ids: set,
    teacher_ids: set,
):
    """
    Create a handler for reaction_added events.
    
    Args:
        feedback_config: Feedback configuration dictionary
        feedback_tracker: FeedbackTracker instance
        store: ChromaVectorStore instance
        curator_ids: Set of curator user IDs
        teacher_ids: Set of teacher user IDs
        
    Returns:
        Handler function for reaction_added events
    """
    
    def handle_reaction_added(body, logger):
        """Track reactions on bot messages for feedback and apply L2 reinforcement."""
        event = body["event"]
        user_id = event.get("user")
        reaction = event.get("reaction")
        item = event.get("item", {})
        
        # Only track reactions on messages
        if item.get("type") != "message":
            return
        
        message_ts = item.get("ts")
        channel_id = item.get("channel")
        
        # Skip if feedback tracking is disabled
        if isinstance(feedback_config, FeedbackConfig):
            if not feedback_config.reactions.enabled:
                return
        else:
            if not feedback_config.get("reactions", {}).get("enabled", True):
                return
        
        # Record the reaction (with role-based weight)
        entry = feedback_tracker.record_reaction(
            reaction=reaction,
            user_id=user_id,
            message_ts=message_ts,
            channel_id=channel_id
        )
        
        if entry:
            print(f"📊 Feedback recorded: {reaction} on message {message_ts}")
            
            # Apply L2 reinforcement (only for curators and teachers)
            # This updates feedback_score in source thread metadata
            role = get_user_role(user_id, curator_ids, teacher_ids)
            
            if role in ("curator", "teacher"):
                # Curators and teachers get immediate L2 reinforcement
                is_positive = entry.feedback_type == "reaction_positive"
                feedback_tracker.apply_reinforcement(
                    vector_store=store,
                    message_ts=message_ts,
                    is_positive=is_positive,
                    weight=entry.weight
                )
                print(f"🎯 L2 reinforcement applied ({role}, weight: {entry.weight}x)")
            else:
                # User feedback: logged but no reinforcement
                print("📝 User feedback logged (no L2 reinforcement)")
    
    return handle_reaction_added

