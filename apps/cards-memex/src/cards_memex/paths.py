"""Centralized path definitions for cards-memex."""
from pathlib import Path

# App root directory (apps/cards-memex/)
APP_DIR = Path(__file__).parent.parent.parent

# Config directory
CONFIG_DIR = APP_DIR / "config"

# Data directory (runtime data, gitignored)
DATA_DIR = APP_DIR / "data"

# Specific paths
ROLE_FILE = CONFIG_DIR / "role.yaml"
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
WATCHED_THREADS_FILE = DATA_DIR / "watched_threads.json"
FEEDBACK_LOG_FILE = DATA_DIR / "feedback_log.jsonl"
REVIEW_QUEUE_FILE = DATA_DIR / "review_queue.json"
ENV_FILE = APP_DIR / ".env"
PROMPTS_DIR = CONFIG_DIR / "prompts"


def ensure_data_dir():
    """Ensure the data directory exists, creating it if necessary."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

