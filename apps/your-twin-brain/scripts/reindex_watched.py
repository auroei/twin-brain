"""
Reindex Watched Threads: Re-populates watched_threads.json from ChromaDB.
Useful when watched_threads.json is lost or corrupted.
Scans ChromaDB for all stored threads and rebuilds the watch list.
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
print("🔄 Reindexing watched threads from ChromaDB...")
print(f"📂 Loading ChromaDB from: {KNOWLEDGE_BASE_DIR}")
print()

client = chromadb.PersistentClient(path=str(KNOWLEDGE_BASE_DIR))

embedding_function = GoogleGenerativeAiEmbeddingFunction(
    api_key=GEMINI_API_KEY,
    task_type="RETRIEVAL_DOCUMENT"
)

collection = client.get_or_create_collection(
    name="slack_knowledge",
    embedding_function=embedding_function
)

doc_count = collection.count()
print(f"✅ Collection has {doc_count} documents")
print()

# --- Get all documents from ChromaDB ---
if doc_count == 0:
    print("⚠️  No documents in ChromaDB - nothing to reindex")
    exit(0)

# Get all documents (ChromaDB returns up to 10 by default, we need all)
results = collection.get(limit=doc_count)

# --- Build watched_threads dict ---
watched_threads = {}

for doc_id, metadata in zip(results["ids"], results["metadatas"]):
    # Extract thread_ts from document ID (format: "thread_1234567890.123456")
    if doc_id.startswith("thread_"):
        thread_ts = doc_id.replace("thread_", "")
        channel_id = metadata.get("channel")
        
        watched_threads[thread_ts] = channel_id
        
        # Print thread info
        thread_name = metadata.get("thread_name", "Untitled")
        theme = metadata.get("theme", "Unknown")
        status = "✅" if channel_id else "⚠️ "
        print(f"{status} {thread_ts}")
        print(f"   Channel: {channel_id or 'None'}")
        print(f"   Name: {thread_name}")
        print(f"   Theme: {theme}")
        print()

# --- Summary ---
null_count = sum(1 for v in watched_threads.values() if v is None)
print("📊 Summary:")
print(f"   - Total threads found: {len(watched_threads)}")
print(f"   - Threads with channel_id: {len(watched_threads) - null_count}")
print(f"   - Threads missing channel_id: {null_count}")
print()

# --- Save to watched_threads.json ---
# Backup existing file if it exists
if WATCHED_THREADS_FILE.exists():
    backup_file = WATCHED_THREADS_FILE.with_suffix(".json.backup")
    with open(WATCHED_THREADS_FILE, 'r') as f:
        original_data = json.load(f)
    with open(backup_file, 'w') as f:
        json.dump(original_data, f, indent=2)
    print(f"💾 Backed up existing watched_threads.json to: {backup_file}")

# Write new file
new_data = {"watched_threads": watched_threads}
with open(WATCHED_THREADS_FILE, 'w') as f:
    json.dump(new_data, f, indent=2)

print(f"✅ Wrote {len(watched_threads)} threads to {WATCHED_THREADS_FILE}")
print()
print("🔄 Reindex complete!")
