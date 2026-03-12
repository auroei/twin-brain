"""Handler for message events in Slack.

Handles three cases:
- Case A: DM (Q&A) - Use RetrievalPipeline with gap checking
- Case B: Channel (Monitoring) - Debounced upsert via IngestionPipeline  
- Case C: Message Edit (Stealth Tagging) - Detect @mention in edited message
"""
import threading
from datetime import datetime
from typing import Callable

from slack_sdk.errors import SlackApiError

from twin_brain.context import BotContext
from twin_brain.rbac import get_user_role
from twin_brain.ux import (
    get_curator_only_message,
    should_send_greeting,
    get_greeting_message,
)
from memex_core import ResponseFormatter
from memex_core.models import SlackThread, SlackMessage


# Debouncing state
_debounce_timers = {}
_debounce_lock = threading.Lock()
DEBOUNCE_DELAY = 120


def _convert_slack_messages_to_thread(messages: list, channel_id: str, thread_ts: str) -> SlackThread:
    """Convert Slack API messages to SlackThread model."""
    slack_messages = [
        SlackMessage(
            user=msg.get("user", "Unknown"),
            text=msg.get("text", ""),
            ts=msg.get("ts", "")
        )
        for msg in messages
    ]
    return SlackThread(
        thread_ts=thread_ts,
        channel_id=channel_id,
        messages=slack_messages,
        classification=None
    )


def create_message_handler(
    app,
    context: BotContext,
    watched_threads: dict,
    upsert_thread_fn: Callable[[str, str], bool],
    add_to_watched_threads_fn: Callable[[str, str], None],
    bot_user_id_getter: Callable[[], str],
):
    """
    Create a handler for message events.
    
    Args:
        app: Slack Bolt app instance
        context: BotContext containing all pipeline components and configs
        watched_threads: Dict of watched thread_ts -> channel_id
        upsert_thread_fn: Function to upsert a thread
        add_to_watched_threads_fn: Function to add thread to watch list
        bot_user_id_getter: Callable that returns the bot's user ID
        
    Returns:
        Handler function for message events
    """
    
    def _do_upsert_thread(channel_id: str, thread_ts: str) -> bool:
        """Internal function that performs the upsert via IngestionPipeline."""
        try:
            result = app.client.conversations_replies(channel=channel_id, ts=thread_ts)
            if not result.get("ok") or not result.get("messages"):
                return False
            
            thread = _convert_slack_messages_to_thread(result["messages"], channel_id, thread_ts)
            success = context.ingest_pipe.process_thread_async(
                thread, context.role_definition, behavior_config=context.behavior_config
            )
            
            if success:
                print(f"📝 Debounced upsert completed for thread {thread_ts}")
            
            return success
        except Exception as e:
            print(f"❌ Error in debounced upsert for thread {thread_ts}: {e}")
            return False
    
    def debounced_upsert_thread(channel_id: str, thread_ts: str):
        """Debounced thread upsert: waits DEBOUNCE_DELAY seconds before upserting."""
        with _debounce_lock:
            if thread_ts in _debounce_timers:
                _debounce_timers[thread_ts].cancel()
                print(f"⏱️  Cancelled previous debounce timer for thread {thread_ts}")
            
            def timer_callback():
                _do_upsert_thread(channel_id, thread_ts)
                with _debounce_lock:
                    if thread_ts in _debounce_timers:
                        del _debounce_timers[thread_ts]
            
            timer = threading.Timer(DEBOUNCE_DELAY, timer_callback)
            timer.start()
            _debounce_timers[thread_ts] = timer
            print(f"⏱️  Started debounce timer ({DEBOUNCE_DELAY}s) for thread {thread_ts}")
    
    def handle_message(body, logger):
        """
        Handle message events.
        
        Case A: DM (Q&A) - Use RetrievalPipeline with gap checking
        Case B: Channel (Monitoring) - Debounced upsert via IngestionPipeline
        Case C: Message Edit (Stealth Tagging) - Detect @mention in edited message
        """
        event = body["event"]
        bot_user_id = bot_user_id_getter()
        
        # --- Case C: Handle message edits for stealth tagging ---
        if event.get("subtype") == "message_changed":
            edited_message = event.get("message", {})
            edited_text = edited_message.get("text", "")
            edited_user_id = edited_message.get("user")
            channel_id = event.get("channel")
            message_ts = edited_message.get("ts")
            thread_ts = edited_message.get("thread_ts", message_ts)
            
            if bot_user_id and f"<@{bot_user_id}>" in edited_text:
                print(f"👀 Stealth tagging detected: User {edited_user_id} edited message to mention bot")
                
                # Get user role for RBAC - only curators can tag
                role = get_user_role(edited_user_id, context.curator_ids, context.teacher_ids)
                
                if role != "curator":
                    # Teachers and users cannot tag threads
                    print(f"📚 Non-curator {edited_user_id} attempted stealth tagging (role: {role})")
                    try:
                        app.client.chat_postEphemeral(
                            channel=channel_id,
                            user=edited_user_id,
                            text=get_curator_only_message(context.ux_config)
                        )
                    except Exception as e:
                        print(f"⚠️  Could not send ephemeral message: {e}")
                    return
                
                # Only curators reach here
                try:
                    if upsert_thread_fn(channel_id, thread_ts):
                        print(f"✅ Stealth tagging: Stored thread {thread_ts}")
                        add_to_watched_threads_fn(thread_ts, channel_id)
                        reaction_emoji = context.ux_config.reactions.watching
                        try:
                            app.client.reactions_add(channel=channel_id, timestamp=message_ts, name=reaction_emoji)
                        except SlackApiError as e:
                            print(f"⚠️  Could not add reaction: {e}")
                except Exception as e:
                    print(f"❌ Error handling stealth tagging: {e}")
            return
        
        # Ignore bot messages
        if event.get("subtype") == "bot_message" or event.get("bot_id"):
            return
        
        user_id = event.get("user")
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts")
        
        # Determine if DM
        is_dm = False
        try:
            channel_info = app.client.conversations_info(channel=channel_id)
            if channel_info.get("ok"):
                is_dm = channel_info.get("channel", {}).get("is_im", False)
        except Exception:
            is_dm = channel_id.startswith('D')
        
        # Case A: DM (Q&A) - Use RetrievalPipeline with gap checking
        if is_dm:
            print(f"💬 DM received from {user_id}")
            message_text = event.get("text", "")
            if not message_text:
                return
            
            # Check for implicit signals (followup/rephrase) BEFORE processing
            context.feedback_tracker.check_for_followup(user_id, message_text, datetime.now())
            context.feedback_tracker.check_for_rephrase(user_id, message_text, datetime.now())
            
            # Check for first-time greeting
            if should_send_greeting(context.ux_config, user_id):
                greeting = get_greeting_message(context.ux_config)
                if greeting:
                    try:
                        app.client.chat_postMessage(channel=channel_id, text=greeting)
                    except Exception as e:
                        print(f"⚠️  Could not send greeting: {e}")
            
            # Create ResponseFormatter for this request
            output_dict = context.output_config.model_dump()
            ux_dict = context.ux_config.model_dump()
            formatter = ResponseFormatter(output_dict, ux_dict)
            
            thinking_ts = None
            try:
                # Show thinking message (using ResponseFormatter)
                thinking_response = app.client.chat_postMessage(
                    channel=channel_id,
                    text=formatter.get_thinking_message()
                )
                thinking_ts = thinking_response["ts"]
                
                # Check for known gaps and out-of-scope queries FIRST
                should_proceed, gap_response, block_reason = context.gap_checker.check_query(message_text)
                
                if not should_proceed and gap_response:
                    print(f"🚫 Query blocked: {block_reason}")
                    app.client.chat_update(channel=channel_id, ts=thinking_ts, text=gap_response)
                    return
                
                # Use RetrievalPipeline to answer the question (single retrieval)
                behavior_dict = context.behavior_config.model_dump()
                retrieval_dict = context.retrieval_config.model_dump()
                
                result = context.retrieval_pipe.answer_question_with_sources(
                    query=message_text,
                    role_def=context.role_definition,
                    behavior_config=behavior_dict,
                    retrieval_config=retrieval_dict,
                    output_config=output_dict,
                    n_results=10
                )
                
                raw_answer = result["answer"]
                
                # Check if answer indicates no results
                if not raw_answer or raw_answer.strip() == "" or "No relevant context found" in raw_answer:
                    answer = formatter.get_empty_message("no_results")
                else:
                    # Format the answer using ResponseFormatter
                    formatted = formatter.format_answer(
                        raw_answer,
                        confidence=result["confidence"],
                        source_count=result["source_count"]
                    )
                    answer = formatted.text
                
                # Update the message with the answer
                app.client.chat_update(channel=channel_id, ts=thinking_ts, text=answer)
                
                # Track the answer for feedback collection and L2 reinforcement
                context.feedback_tracker.track_answer(
                    user_id=user_id,
                    question=message_text,
                    answer=answer,
                    answer_message_ts=thinking_ts,
                    channel_id=channel_id,
                    confidence_score=result["confidence"],
                    source_thread_count=result["source_count"],
                    source_thread_ids=result["source_thread_ids"]
                )
                
            except Exception as e:
                print(f"❌ Error processing DM question: {e}")
                if thinking_ts:
                    try:
                        app.client.chat_update(
                            channel=channel_id,
                            ts=thinking_ts,
                            text=formatter.get_error_message("generic")
                        )
                    except:
                        pass
            return
        
        # Case B: Channel (Monitoring) - Use debounced IngestionPipeline
        if thread_ts and thread_ts in watched_threads:
            debounced_upsert_thread(channel_id, thread_ts)
            print(f"📝 Monitoring message in watched thread {thread_ts}")
    
    return handle_message
