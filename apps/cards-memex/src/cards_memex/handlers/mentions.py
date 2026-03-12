"""Handler for @mention events in Slack.

Silent Admin Mode: Only curators can tag threads for watching.
"""
from typing import Union
from slack_sdk.errors import SlackApiError

from cards_memex.rbac import get_user_role
from cards_memex.ux import get_curator_only_message
from cards_memex.config_models import UXConfig


def create_mention_handler(
    app,
    ux_config: Union[UXConfig, dict],
    curator_ids: set,
    teacher_ids: set,
    upsert_thread_fn,
    add_to_watched_threads_fn,
):
    """
    Create a handler for app_mention events.
    
    Args:
        app: Slack Bolt app instance
        ux_config: UX configuration dictionary
        curator_ids: Set of curator user IDs
        teacher_ids: Set of teacher user IDs
        upsert_thread_fn: Function to upsert a thread to the knowledge base
        add_to_watched_threads_fn: Function to add a thread to the watch list
        
    Returns:
        Handler function for app_mention events
    """
    
    def handle_mention(body, say, logger):
        """Silent Admin Mode: Only curators can tag threads for watching."""
        event = body["event"]
        user_id = event.get("user")
        channel_id = event["channel"]
        
        # Get user role for RBAC - only curators can tag
        role = get_user_role(user_id, curator_ids, teacher_ids)
        
        if role != "curator":
            # Teachers and users cannot tag threads
            print(f"📚 Non-curator {user_id} attempted to tag thread (role: {role})")
            try:
                app.client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=get_curator_only_message(ux_config)
                )
            except Exception as e:
                print(f"⚠️  Could not send ephemeral message: {e}")
            return
        
        thread_ts = event.get("thread_ts", event.get("ts"))
        message_ts = event.get("ts")
        print(f"👀 Mentioned by admin {user_id} in channel {channel_id}, thread {thread_ts}")
        
        try:
            # Ingest the thread using pipeline
            if not upsert_thread_fn(channel_id, thread_ts):
                print(f"⚠️  Failed to upsert thread {thread_ts}")
                return
            
            print(f"✅ Stored thread {thread_ts} in ChromaDB")
            add_to_watched_threads_fn(thread_ts, channel_id)
            
            # React with configured emoji (NO TEXT REPLY)
            if isinstance(ux_config, UXConfig):
                reaction_emoji = ux_config.reactions.watching
            else:
                reaction_emoji = ux_config.get("reactions", {}).get("watching", "eyes")
            try:
                app.client.reactions_add(channel=channel_id, timestamp=message_ts, name=reaction_emoji)
            except SlackApiError as e:
                if e.response.get("error") == "missing_scope":
                    print("⚠️  MISSING SCOPE ERROR: reactions:write scope is not enabled")
                else:
                    print(f"⚠️  Could not add reaction: {e}")
        except Exception as e:
            print(f"❌ Error handling mention: {e}")
    
    return handle_mention

