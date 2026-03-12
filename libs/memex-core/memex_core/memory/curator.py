"""
Memory curation module for filtering and validating threads before ingestion.
"""

import os
import re
from typing import Optional, Dict, Any, Tuple
import yaml

from ..models import SlackThread
from ..utils import format_thread


class MemoryCurator:
    """
    Curates threads before ingestion into memory.
    Filters out low-quality threads based on configurable criteria.
    """
    
    def __init__(self, config_path: Optional[str] = None, config_dict: Optional[Dict[str, Any]] = None):
        """
        Initialize MemoryCurator with configuration.
        
        Args:
            config_path: Path to retrieval.yaml config file
            config_dict: Optional dict with config values (overrides config_path)
        """
        if config_dict:
            self.config = config_dict
        elif config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}
        
        self.min_length = self.config.get("curation", {}).get("min_length", 20)
    
    def should_ingest(self, thread: SlackThread) -> Tuple[bool, Optional[str]]:
        """
        Determine if a thread should be ingested into memory.
        
        Args:
            thread: SlackThread instance to evaluate
            
        Returns:
            Tuple of (should_ingest: bool, reason: Optional[str])
            If should_ingest is False, reason contains the rejection reason.
        """
        # Check minimum message count (>1)
        if len(thread.messages) <= 1:
            return False, "Too few messages (need >1)"
        
        # Format thread to get full text
        messages_dict = [{"user": msg.user, "text": msg.text} for msg in thread.messages]
        thread_text = format_thread(messages_dict)
        
        # Check minimum text length
        text_length = len(thread_text.strip())
        if text_length < self.min_length:
            return False, f"Text too short ({text_length} chars, need {self.min_length})"
        
        # Check if thread is just emojis
        # Remove all emojis and check if there's any meaningful text left
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"  # enclosed characters
            "]+",
            flags=re.UNICODE
        )
        
        # Also remove common Slack emoji shortcodes like :thumbsup:
        slack_emoji_pattern = re.compile(r':[a-z0-9_+-]+:', re.IGNORECASE)
        
        # Remove emojis and Slack emoji shortcodes
        text_without_emojis = emoji_pattern.sub('', thread_text)
        text_without_emojis = slack_emoji_pattern.sub('', text_without_emojis)
        
        # Remove user IDs in brackets (from format_thread)
        text_without_emojis = re.sub(r'\[[^\]]+\]:\s*', '', text_without_emojis)
        
        # Remove whitespace and check if anything meaningful remains
        text_without_emojis = text_without_emojis.strip()
        
        if len(text_without_emojis) < self.min_length:
            return False, "Only emojis or insufficient text after removing emojis"
        
        # All checks passed
        return True, None

