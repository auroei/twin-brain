"""
Catch Up script: Refreshes bot memory on startup by re-processing all watched threads.
Fetches latest thread history from Slack, re-classifies with current role.yaml,
and upserts updated classification and text to ChromaDB.

Uses the centralized services initialization for consistency with main.py.
"""

import os
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Import from cards_memex package
from cards_memex.paths import (
    ENV_FILE, CONFIG_DIR, DATA_DIR, KNOWLEDGE_BASE_DIR,
    ROLE_FILE, WATCHED_THREADS_FILE, ensure_data_dir,
)
from cards_memex.config_loader import load_all_configs
from cards_memex.services import initialize_services
from cards_memex.slack_utils import fetch_thread

# Import memex-core classes
from memex_core import load_role_definition

# --- Configuration ---
ensure_data_dir()

load_dotenv(dotenv_path=ENV_FILE)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN not found in .env file")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

# --- Load Configuration ---
configs = load_all_configs(CONFIG_DIR)
role_definition = load_role_definition(role_file=str(ROLE_FILE))
print(f"✅ Loaded role definition: {role_definition.role}")

# --- Initialize Pipeline Components via Services ---
# Only need ingestion pipeline for catchup (include_retrieval=False)
context = initialize_services(
    configs=configs,
    role_definition=role_definition,
    gemini_api_key=GEMINI_API_KEY,
    knowledge_base_dir=str(KNOWLEDGE_BASE_DIR),
    data_dir=str(DATA_DIR),
    include_retrieval=False,
)

print("✅ Initialized IngestionPipeline for catchup")

# --- Initialize Slack WebClient ---
slack_client = WebClient(token=SLACK_BOT_TOKEN)


# --- Helper Functions ---
def load_watched_threads() -> dict:
    """
    Load watched threads from watched_threads.json.
    Returns dict: {thread_ts: channel_id}
    """
    if not WATCHED_THREADS_FILE.exists():
        print(f"⚠️  {WATCHED_THREADS_FILE} not found, no threads to catch up")
        return {}
    
    try:
        with open(WATCHED_THREADS_FILE, 'r') as f:
            data = json.load(f)
            
            if "watched_threads" in data:
                watched_dict = data["watched_threads"]
                if isinstance(watched_dict, dict):
                    return watched_dict
            return {}
    except Exception as e:
        print(f"❌ Error loading watched threads: {e}")
        return {}


def save_watched_threads(watched_threads: dict) -> None:
    """Save watched threads dict to file."""
    try:
        with open(WATCHED_THREADS_FILE, 'w') as f:
            json.dump({"watched_threads": watched_threads}, f)
        print(f"✅ Saved watched threads ({len(watched_threads)} entries)")
    except Exception as e:
        print(f"❌ Error saving watched threads: {e}")


def try_resolve_channel_id(thread_ts: str) -> Optional[str]:
    """
    Attempt to resolve channel_id by searching for the thread in ChromaDB metadata.
    
    Args:
        thread_ts: Thread timestamp to look up
        
    Returns:
        channel_id if found, None otherwise
    """
    try:
        thread_id = f"thread_{thread_ts}"
        results = context.store.collection.get(ids=[thread_id], include=["metadatas"])
        
        if results["ids"] and results["metadatas"]:
            channel_id = results["metadatas"][0].get("channel")
            if channel_id:
                print(f"   ✅ Resolved channel_id from ChromaDB: {channel_id}")
                return channel_id
    except Exception as e:
        print(f"   ⚠️  Could not resolve channel_id from ChromaDB: {e}")
    
    return None


def refresh_thread(thread_ts: str, channel_id: str) -> bool:
    """
    Refresh a single thread using the IngestionPipeline.
    
    Args:
        thread_ts: Thread timestamp identifier
        channel_id: Channel ID where thread exists
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Fetch thread from Slack
        thread = fetch_thread(slack_client, channel_id, thread_ts)
        
        # Use pipeline for full ingestion (curate → store → classify)
        success = context.ingest_pipe.process_thread(thread, role_definition)
        
        if success:
            print(f"🔄 Refreshed thread {thread_ts}")
        
        return success
        
    except SlackApiError as e:
        print(f"❌ Slack API error refreshing thread {thread_ts}: {e.response.get('error', 'Unknown error')}")
        return False
    except ValueError as e:
        print(f"⚠️  {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error refreshing thread {thread_ts}: {e}")
        return False


# --- Main Logic ---
def catch_up():
    """Refresh memory by re-processing all watched threads using IngestionPipeline."""
    print("🔄 Starting Catch Up (refreshing memory)...")
    print()
    
    watched_threads = load_watched_threads()
    if not watched_threads:
        print("✅ No watched threads to catch up")
        return
    
    print(f"📊 Found {len(watched_threads)} watched threads")
    print()
    
    threads_processed = 0
    threads_failed = 0
    threads_skipped = 0
    threads_resolved = 0
    updated_watched = dict(watched_threads)  # Copy for potential updates
    
    for idx, (thread_ts, channel_id) in enumerate(watched_threads.items(), 1):
        print(f"[{idx}/{len(watched_threads)}] Processing thread {thread_ts}...")
        
        if channel_id is None:
            # Attempt to resolve channel_id from ChromaDB metadata
            print(f"   ℹ️  Attempting to resolve channel_id from ChromaDB...")
            resolved_channel = try_resolve_channel_id(thread_ts)
            
            if resolved_channel:
                channel_id = resolved_channel
                updated_watched[thread_ts] = channel_id
                threads_resolved += 1
            else:
                print(f"   ⚠️  Skipping thread {thread_ts}: channel_id is None and could not be resolved")
                print("   Please re-tag this thread to restore channel_id")
                threads_skipped += 1
                continue
        
        success = refresh_thread(thread_ts, channel_id)
        
        if success:
            threads_processed += 1
        else:
            threads_failed += 1
        
        # Rate limiting: small sleep between API calls
        if idx < len(watched_threads):
            time.sleep(0.5)
    
    # Save updated watched_threads if any channel_ids were resolved
    if threads_resolved > 0:
        print(f"\n📝 Saving {threads_resolved} resolved channel_id(s)...")
        save_watched_threads(updated_watched)
    
    print()
    print("✅ Catch Up complete!")
    print("📊 Statistics:")
    print(f"   - Threads refreshed: {threads_processed}")
    print(f"   - Channel IDs resolved: {threads_resolved}")
    print(f"   - Threads skipped: {threads_skipped}")
    print(f"   - Threads failed: {threads_failed}")
    print(f"   - Total threads: {len(watched_threads)}")


if __name__ == "__main__":
    catch_up()
