"""
Query ChromaDB to get channel_id for each watched thread.
Run this to populate channel IDs in watched_threads.json.
"""

import os
import json
import sys
from pathlib import Path

# Script is in apps/your-twin-brain/scripts/, add src to path
app_dir = Path(__file__).parent.parent
sys.path.insert(0, str(app_dir / "src"))

from dotenv import load_dotenv
import chromadb
from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction

# Import paths from twin_brain package
from twin_brain.paths import ENV_FILE, KNOWLEDGE_BASE_DIR, WATCHED_THREADS_FILE, ensure_data_dir

# --- Configuration ---
ensure_data_dir()
load_dotenv(dotenv_path=ENV_FILE)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

# --- Initialize ChromaDB ---
print(f"📂 Loading ChromaDB from: {KNOWLEDGE_BASE_DIR}")

client = chromadb.PersistentClient(path=str(KNOWLEDGE_BASE_DIR))

embedding_function = GoogleGenerativeAiEmbeddingFunction(
    api_key=GEMINI_API_KEY,
    task_type="RETRIEVAL_DOCUMENT"
)

collection = client.get_or_create_collection(
    name="slack_knowledge",
    embedding_function=embedding_function
)

print(f"✅ Collection has {collection.count()} documents")
print()

# --- Load watched threads ---
if not WATCHED_THREADS_FILE.exists():
    print(f"❌ {WATCHED_THREADS_FILE} not found")
    exit(1)

with open(WATCHED_THREADS_FILE, 'r') as f:
    data = json.load(f)
    watched_threads = data.get("watched_threads", {})

print(f"📋 Found {len(watched_threads)} watched threads to check")
print()

# --- Query each thread ---
updated_threads = {}
missing_threads = []

for thread_ts, current_channel_id in watched_threads.items():
    thread_id = f"thread_{thread_ts}"
    
    # Query ChromaDB for this thread
    results = collection.get(ids=[thread_id])
    
    if results["ids"]:
        metadata = results["metadatas"][0] if results["metadatas"] else {}
        channel_id = metadata.get("channel")
        
        if channel_id:
            updated_threads[thread_ts] = channel_id
            status = "✅" if current_channel_id is None else "🔄"
            print(f"{status} {thread_ts} -> {channel_id}")
        else:
            updated_threads[thread_ts] = current_channel_id
            print(f"⚠️  {thread_ts}: Found in DB but no channel_id in metadata")
            missing_threads.append(thread_ts)
    else:
        updated_threads[thread_ts] = current_channel_id
        print(f"❌ {thread_ts}: Not found in ChromaDB")
        missing_threads.append(thread_ts)

print()

# --- Summary ---
null_count = sum(1 for v in updated_threads.values() if v is None)
print("📊 Summary:")
print(f"   - Threads with channel_id: {len(updated_threads) - null_count}")
print(f"   - Threads still missing channel_id: {null_count}")
print()

# --- Save updated file ---
if null_count < len(watched_threads):
    new_data = {"watched_threads": updated_threads}
    
    # Backup original
    backup_file = WATCHED_THREADS_FILE.with_suffix(".json.backup")
    with open(backup_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"💾 Backed up original to: {backup_file}")
    
    # Write updated
    with open(WATCHED_THREADS_FILE, 'w') as f:
        json.dump(new_data, f, indent=2)
    print(f"✅ Updated {WATCHED_THREADS_FILE} with channel IDs")
else:
    print("⚠️  No channel IDs found - watched_threads.json not modified")
    print("   Threads may need to be re-tagged to get channel IDs")
