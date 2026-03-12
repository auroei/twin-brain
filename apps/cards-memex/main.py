# SLACK CONFIG REMINDER: Enable required scopes in Slack App dashboard
# Go to: OAuth & Permissions -> Scopes -> Bot Token Scopes -> Add:
#   - "message.channels" (to read channel messages)
#   - "reactions:write" (to add 👀 emoji reactions)
#   - "reactions:read" (to receive reaction events for feedback)

"""Cards Memex Bot - Entry Point.

A Slack bot that indexes threads and answers questions via RAG.
"""
import os
import sys
import json
import threading
from pathlib import Path

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Import from cards_memex package
from cards_memex.paths import (
    ENV_FILE, CONFIG_DIR, DATA_DIR, KNOWLEDGE_BASE_DIR,
    PROMPTS_DIR, ROLE_FILE, WATCHED_THREADS_FILE,
    ensure_data_dir,
)
from cards_memex.rbac import load_rbac_config, get_user_role
from cards_memex.config_loader import load_all_configs
from cards_memex.services import initialize_services
from cards_memex.handlers import (
    create_mention_handler,
    create_message_handler,
    create_reaction_handler,
)
from cards_memex.slack_utils import fetch_thread

# Import memex-core
from memex_core import load_role_definition, set_app_prompts_dir

# --- 1. Ensure Data Directory Exists ---
ensure_data_dir()

# --- 2. Load Environment ---
load_dotenv(dotenv_path=ENV_FILE)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- 3. Load RBAC Configuration ---
CURATOR_IDS, TEACHER_IDS = load_rbac_config()

# --- 4. Initialize Slack App ---
app = App(token=SLACK_BOT_TOKEN)
BOT_USER_ID = None

def get_bot_user_id():
    """Get the bot's user ID."""
    return BOT_USER_ID

# --- 5. Load Configuration ---
configs = load_all_configs(CONFIG_DIR)

# Role definition
role_definition = load_role_definition(role_file=str(ROLE_FILE))
print(f"✅ Loaded role definition: {role_definition.role}")

# Set app-level prompts directory
if PROMPTS_DIR.exists():
    set_app_prompts_dir(str(PROMPTS_DIR))
else:
    print(f"⚠️  App prompts directory not found: {PROMPTS_DIR}")

# --- 6. Initialize Pipeline Components via Services ---
context = initialize_services(
    configs=configs,
    role_definition=role_definition,
    gemini_api_key=GEMINI_API_KEY,
    knowledge_base_dir=str(KNOWLEDGE_BASE_DIR),
    data_dir=str(DATA_DIR),
    curator_ids=CURATOR_IDS,
    teacher_ids=TEACHER_IDS,
    include_retrieval=True,
)

print("   • App-level prompts: Enabled")

# --- 7. Persistent Watch List ---
_file_lock = threading.Lock()
_watched_threads_lock = threading.Lock()
_classification_locks = {}  # Per-thread classification locks


def load_watched_threads():
    """Load watched threads from file. Returns dict: {thread_ts: channel_id}."""
    if WATCHED_THREADS_FILE.exists():
        try:
            with open(WATCHED_THREADS_FILE, 'r') as f:
                data = json.load(f)
                if "watched_threads" in data:
                    watched_dict = data["watched_threads"]
                    if isinstance(watched_dict, dict):
                        return watched_dict
                return {}
        except Exception as e:
            print(f"⚠️  Error loading watched threads: {e}")
            return {}
    return {}


def save_watched_threads():
    """Save watched threads dict to file with thread-safe locking."""
    with _file_lock:
        try:
            with open(WATCHED_THREADS_FILE, 'w') as f:
                json.dump({"watched_threads": watched_threads}, f)
        except Exception as e:
            print(f"❌ Error saving watched threads: {e}")


watched_threads = load_watched_threads()
print(f"✅ Loaded {len(watched_threads)} watched threads")


def add_to_watched_threads(thread_ts, channel_id):
    """Thread-safe helper to add a thread to the watch list."""
    with _watched_threads_lock:
        if thread_ts not in watched_threads:
            watched_threads[thread_ts] = channel_id
            save_watched_threads()
            print(f"✅ Added thread {thread_ts} to watch list")
        elif watched_threads[thread_ts] != channel_id:
            watched_threads[thread_ts] = channel_id
            save_watched_threads()
            print(f"✅ Updated channel_id for thread {thread_ts}")


# --- 8. Thread Helper Functions ---
def _get_classification_lock(thread_ts: str) -> threading.Lock:
    """Get or create a lock for a specific thread to prevent duplicate classification."""
    with _watched_threads_lock:  # Reuse existing lock for dict access
        if thread_ts not in _classification_locks:
            _classification_locks[thread_ts] = threading.Lock()
        return _classification_locks[thread_ts]


def _classify_in_background(thread):
    """Background worker: Classify thread ONLY if significantly changed."""
    lock = _get_classification_lock(thread.thread_ts)
    
    # Non-blocking attempt to acquire lock - if another thread is classifying, skip
    if not lock.acquire(blocking=False):
        print(f"⏭️  Skipping classification for {thread.thread_ts}: Another classification in progress")
        return
    
    try:
        thread_id = f"thread_{thread.thread_ts}"
        
        # Check existing metadata to see if classification is worthwhile
        existing = context.store.collection.get(ids=[thread_id], include=["metadatas"])
        
        should_classify = True
        
        if existing["ids"]:
            meta = existing["metadatas"][0]
            
            # Gate 1: Check message count delta (need 5+ new messages)
            last_msg_count = meta.get("message_count", 0)
            current_msg_count = len(thread.messages)
            msg_delta = current_msg_count - last_msg_count
            
            if 0 < msg_delta < 5:
                print(f"⏭️  Skipping classification for {thread.thread_ts}: Only {msg_delta} new messages")
                should_classify = False
            
            # Gate 2: Check time since last classification (need 5+ min gap)
            last_classified = meta.get("last_classified_at")
            if last_classified and should_classify:
                from datetime import datetime
                try:
                    last_time = datetime.fromisoformat(last_classified)
                    seconds_since = (datetime.now() - last_time).total_seconds()
                    if seconds_since < 300:  # 5 minute cooldown
                        print(f"⏭️  Skipping classification for {thread.thread_ts}: Only {int(seconds_since)}s since last classification")
                        should_classify = False
                except (ValueError, TypeError):
                    pass  # Proceed if date parsing fails
        
        if not should_classify:
            return
        
        print(f"🔄 Background classification started for thread {thread.thread_ts}")
        context.ingest_pipe.classify_thread(
            thread, 
            role_definition, 
            behavior_config=configs.behavior.model_dump()
        )
        print(f"✅ Background classification completed for thread {thread.thread_ts}")
        
    except Exception as e:
        print(f"❌ Error in background classification for thread {thread.thread_ts}: {e}")
    finally:
        lock.release()


def upsert_thread(channel_id, thread_ts):
    """Async thread upsert: saves immediately, classifies in background."""
    try:
        thread = fetch_thread(app, channel_id, thread_ts)
        
        # Use pipeline for async ingestion (skip classification)
        success = context.ingest_pipe.process_thread_async(thread, role_definition, behavior_config=configs.behavior.model_dump())
        if not success:
            return False
        
        print(f"📝 Immediate upsert completed for thread {thread_ts}")
        
        # Spawn background thread for classification
        bg_thread = threading.Thread(target=_classify_in_background, args=(thread,), daemon=True)
        bg_thread.start()
        
        return True
    except Exception as e:
        print(f"❌ Error upserting thread {thread_ts}: {e}")
        return False


# --- 9. Register Event Handlers ---
handle_mention = create_mention_handler(
    app=app,
    ux_config=configs.ux,
    curator_ids=CURATOR_IDS,
    teacher_ids=TEACHER_IDS,
    upsert_thread_fn=upsert_thread,
    add_to_watched_threads_fn=add_to_watched_threads,
)

handle_message = create_message_handler(
    app=app,
    context=context,
    watched_threads=watched_threads,
    upsert_thread_fn=upsert_thread,
    add_to_watched_threads_fn=add_to_watched_threads,
    bot_user_id_getter=get_bot_user_id,
)

handle_reaction_added = create_reaction_handler(
    feedback_config=configs.feedback,
    feedback_tracker=context.feedback_tracker,
    store=context.store,
    curator_ids=CURATOR_IDS,
    teacher_ids=TEACHER_IDS,
)

app.event("app_mention")(handle_mention)
app.event("message")(handle_message)
app.event("reaction_added")(handle_reaction_added)


# --- 10. Startup Validation ---
def validate_startup():
    """Validate environment variables, Slack auth, and ChromaDB connectivity."""
    print("\n🔍 Validating Bot Configuration...")
    errors = []
    
    if not SLACK_BOT_TOKEN:
        errors.append("SLACK_BOT_TOKEN not found in .env")
    if not SLACK_APP_TOKEN:
        errors.append("SLACK_APP_TOKEN not found in .env")
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY not found in .env")
    
    global BOT_USER_ID
    if SLACK_BOT_TOKEN:
        try:
            result = app.client.auth_test()
            if not result["ok"]:
                errors.append(f"Slack auth test failed: {result.get('error', 'Unknown error')}")
            else:
                BOT_USER_ID = result.get("user_id")
                print(f"✅ Slack Authentication Successful")
                print(f"   Bot Name: {result.get('user', 'Unknown')}")
                print(f"   Bot User ID: {BOT_USER_ID}")
                print(f"   Workspace: {result.get('team', 'Unknown')}")
                if not BOT_USER_ID:
                    errors.append("Could not retrieve bot user ID from auth_test")
        except Exception as e:
            errors.append(f"Slack auth test exception: {e}")
    
    try:
        doc_count = context.store.collection.count()
        print(f"✅ ChromaDB Connected")
        print(f"   Documents in memory: {doc_count}")
    except Exception as e:
        errors.append(f"ChromaDB connectivity issue: {e}")
    
    print(f"✅ Role-Based Access Control Configured")
    print(f"   Curators (tag + Q&A + 5x feedback + L2): {len(CURATOR_IDS)}")
    print(f"   Teachers (Q&A + 5x feedback + L2): {len(TEACHER_IDS)}")
    print(f"   Users (Q&A + logged feedback): Open access")
    
    # Print config summary
    print(f"✅ Configuration Loaded")
    print(f"   • Output length: {configs.output.length.default}")
    print(f"   • Citations: {configs.output.citations.format}")
    print(f"   • Known gaps: {len(configs.gaps.known_gaps)}")
    print(f"   • Out-of-scope topics: {len(configs.gaps.out_of_scope)}")
    print(f"   • Priority patterns: {len(configs.priority.content_patterns)}")
    print(f"   • Feedback tracking: {configs.feedback.reactions.enabled}")
    
    if errors:
        print("\n❌ Startup validation failed:")
        for error in errors:
            print(f"   - {error}")
        return False
    
    print("\n✅ All validations passed!")
    return True


# --- 11. Review Queue Commands ---
def send_review_request(user_id: str, channel_id: str):
    """Send pending review items to an expert reviewer."""
    pending = context.feedback_tracker.get_pending_reviews(limit=5)
    
    if not pending:
        app.client.chat_postMessage(
            channel=channel_id,
            text="✅ No pending reviews! All caught up."
        )
        return
    
    # Get review prompt template from feedback config (access raw dict for optional nested fields)
    feedback_dict = configs.feedback.model_dump()
    interface_config = feedback_dict.get("review_workflow", {}).get("interface", {})
    prompt_template = interface_config.get("prompt", "")
    
    for item in pending:
        if prompt_template:
            prompt = prompt_template.format(
                question=item.question,
                answer=item.answer[:500] + "..." if len(item.answer) > 500 else item.answer,
                source_count=item.source_thread_count,
                confidence=f"{item.confidence_score:.0%}"
            )
        else:
            prompt = f"""📋 *Review Request*

*Question:* {item.question}
*Answer:* {item.answer[:500]}{'...' if len(item.answer) > 500 else ''}
*Confidence:* {item.confidence_score:.0%}

Please react:
✅ = Correct & Complete
⚠️ = Partially correct/incomplete
❌ = Incorrect"""
        
        try:
            app.client.chat_postMessage(channel=channel_id, text=prompt)
        except Exception as e:
            print(f"⚠️  Error sending review request: {e}")


def send_feedback_summary(user_id: str, channel_id: str):
    """Send a feedback summary to the user."""
    summary = context.feedback_tracker.get_feedback_summary(days=7)
    review_stats = context.feedback_tracker.get_review_stats()
    
    message = f"""📊 *Feedback Summary (Last 7 Days)*

*Reactions:*
• 👍 Positive: {summary.get('reaction_positive', 0)}
• 👎 Negative: {summary.get('reaction_negative', 0)}

*Implicit Signals:*
• Follow-up questions: {summary.get('followups', 0)}
• Rephrased questions: {summary.get('rephrases', 0)}

*Expert Reviews:*
• Total in queue: {review_stats.get('total_items', 0)}
• Reviewed: {review_stats.get('reviewed', 0)}
• Pending: {review_stats.get('pending', 0)}

*Review Results:*
• Correct: {review_stats.get('review_results', {}).get('correct', 0)}
• Partially Correct: {review_stats.get('review_results', {}).get('partially_correct', 0)}
• Incorrect: {review_stats.get('review_results', {}).get('incorrect', 0)}
"""
    
    try:
        app.client.chat_postMessage(channel=channel_id, text=message)
    except Exception as e:
        print(f"⚠️  Error sending feedback summary: {e}")


# --- 12. Start the App ---
if __name__ == "__main__":
    print("⚡️ Cards-Strategy Bot - Startup Sequence")
    print("=" * 60)
    
    if not validate_startup():
        print("\n❌ STARTUP FAILED - Please fix the errors above and try again.")
        print("=" * 60)
        exit(1)
    
    print("\n🚀 Starting Slack Connection...")
    print("=" * 60)
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    
    print("\n" + "=" * 60)
    print("✅ BOT IS READY!")
    print("=" * 60)
    print(f"📋 Mode: Three-Role Access Control")
    print(f"   • Curators ({len(CURATOR_IDS)}): Tag + Q&A + 5x feedback + L2")
    print(f"   • Teachers ({len(TEACHER_IDS)}): Q&A + 5x feedback + L2")
    print(f"   • Users (open): Q&A + logged feedback")
    print("=" * 60)
    print("📝 Logs will be written to: bot.log")
    print("🔌 Bot is now listening for events...\n")
    
    handler.start()
