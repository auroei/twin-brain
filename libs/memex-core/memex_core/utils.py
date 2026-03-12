"""
Utility functions for memex-core.
Includes helper functions for formatting, validation, and role definition loading.
"""

import os
import re
import yaml
from datetime import datetime
from typing import List, Dict, Tuple, Optional

from .models import RoleDefinition, Theme


def parse_datetime_robust(date_str: str) -> Optional[datetime]:
    """
    Parse a datetime string robustly, handling multiple formats.
    
    Handles:
    - ISO format with timezone: "2024-01-15T10:30:00+00:00"
    - ISO format with Z: "2024-01-15T10:30:00Z"
    - ISO format without timezone: "2024-01-15T10:30:00"
    - Date only: "2024-01-15"
    
    Args:
        date_str: Date string to parse
        
    Returns:
        Parsed datetime object, or None if parsing fails
    """
    if not date_str or not isinstance(date_str, str):
        return None
    
    date_str = date_str.strip()
    if not date_str:
        return None
    
    # Try various formats
    formats_to_try = [
        # ISO format with various timezone representations
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
        # Standard ISO format
        lambda s: datetime.fromisoformat(s),
        # Date only format
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
        # Common datetime format
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
    ]
    
    for parse_func in formats_to_try:
        try:
            return parse_func(date_str)
        except (ValueError, TypeError):
            continue
    
    # All formats failed
    return None


def parse_datetime_list_robust(date_strings: str) -> List[datetime]:
    """
    Parse a comma-separated string of dates robustly.
    
    Args:
        date_strings: Comma-separated date strings (e.g., "2024-01-15,2024-02-20")
        
    Returns:
        List of successfully parsed datetime objects (skips failures)
    """
    if not date_strings or not isinstance(date_strings, str):
        return []
    
    result = []
    for date_str in date_strings.split(","):
        parsed = parse_datetime_robust(date_str.strip())
        if parsed:
            result.append(parsed)
    
    return result


def clean_query(text: str) -> str:
    """
    Remove URLs and special characters before querying ChromaDB.
    
    Args:
        text: Input text to clean
        
    Returns:
        Cleaned text string
    """
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    # Remove special Slack formatting characters but keep basic punctuation
    text = re.sub(r'<[^>]+>', '', text)  # Remove Slack mentions/links format <@U123|name>
    # Clean up extra whitespace
    text = ' '.join(text.split())
    return text.strip()


def format_thread(messages: List[Dict[str, str]]) -> str:
    """
    Format a list of Slack message objects into a single string.
    Format: [User ID]: Message text... \n [User ID]: Reply text...
    
    Args:
        messages: List of message dictionaries with 'user' and 'text' keys
        
    Returns:
        Formatted string representation of the thread
    """
    formatted_parts = []
    for msg in messages:
        user_id = msg.get("user", "Unknown")
        text = msg.get("text", "")
        if text:  # Only include non-empty messages
            formatted_parts.append(f"[{user_id}]: {text}")
    return "\n".join(formatted_parts)


def truncate_thread_for_classification(text: str) -> str:
    """
    Truncate thread text for classification to save tokens.
    Keeps first 1000 and last 1000 characters.
    
    Args:
        text: Full thread text to truncate
        
    Returns:
        Truncated text with middle section removed if over 2000 characters
    """
    if len(text) <= 2000:
        return text
    
    first_part = text[:1000]
    last_part = text[-1000:]
    return f"{first_part}\n\n[... truncated middle content ...]\n\n{last_part}"


def validate_slack_response(result: Dict, thread_ts: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Slack API response to prevent crashes.
    Checks if result and result["messages"] exist and are valid.
    
    Args:
        result: Slack API response dictionary
        thread_ts: Thread timestamp for error messages
        
    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not result:
        return False, f"Empty response for thread {thread_ts}"
    
    if "messages" not in result:
        return False, f"No 'messages' key in response for thread {thread_ts}"
    
    if not isinstance(result["messages"], list):
        return False, f"'messages' is not a list for thread {thread_ts}"
    
    if len(result["messages"]) == 0:
        return False, f"Empty messages list for thread {thread_ts}"
    
    return True, None


def _get_default_role_definition() -> RoleDefinition:
    """
    Get default RoleDefinition as fallback.
    
    Returns:
        Default RoleDefinition instance
    """
    return RoleDefinition(
        role="Cards Strategy Lead",
        products=["Credit Cards (CC)", "Debit Cards (DC)", "Cross-Portfolio (Both)"],
        themes=[
            Theme(name="P&L & Financials", description="Revenue, cost of funds, yield, margins, budget planning."),
            Theme(name="Portfolio Strategy", description="Segmentation, book growth, retention, spend stimulation."),
            Theme(name="CVP & Economics", description="New offers, LTV/CAC simulations, unit economics, testing."),
            Theme(name="Growth Execution", description="Program management, GTM, Xfn delivery, status tracking."),
            Theme(name="Network Partnerships", description="Deals and negotiations with Visa/Mastercard/RuPay."),
        ],
        topics=[
            "GTM Plan",
            "Funnel Analysis",
            "Risk Review",
            "Legal/Contract",
            "Pricing Simulation",
            "Marketing Copy",
            "Tech Feasibility",
            "Status Update"
        ]
    )


def load_role_definition(role_file: str = "role_definition.yaml") -> RoleDefinition:
    """
    Load role_definition.yaml and return it as a RoleDefinition Pydantic object.
    
    Args:
        role_file: Path to the role definition YAML file
        
    Returns:
        RoleDefinition Pydantic model instance
    """
    if not os.path.exists(role_file):
        print(f"⚠️  Warning: {role_file} not found. Using generic fallback.")
        return _get_default_role_definition()
    
    try:
        with open(role_file, 'r') as f:
            role_data = yaml.safe_load(f)
        
        if not role_data:
            # Return default if file is empty
            return _get_default_role_definition()
        
        # Parse themes into Theme objects
        themes = []
        for theme_dict in role_data.get("themes", []):
            themes.append(Theme(
                name=theme_dict.get("name", ""),
                description=theme_dict.get("description", "")
            ))
        
        # Create and return RoleDefinition
        return RoleDefinition(
            role=role_data.get("role", "Cards Strategy Lead"),
            products=role_data.get("products", []),
            themes=themes,
            topics=role_data.get("topics", [])
        )
    except Exception as e:
        print(f"⚠️  Error loading {role_file}: {e}")
        # Return fallback on error
        return _get_default_role_definition()

