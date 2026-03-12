"""UX helper functions for Cards Memex.

Provides user-facing messages based on UX configuration.
"""
import random
from typing import Set

from .config_models import UXConfig


# Module-level state for tracking greeted users (resets on restart)
_greeted_users: Set[str] = set()


def get_thinking_message(ux_config: UXConfig) -> str:
    """
    Get a random thinking message from UX config.
    
    Args:
        ux_config: UX configuration
        
    Returns:
        Thinking message string
    """
    variants = ux_config.thinking.variants
    if variants:
        return random.choice(variants)
    return ux_config.thinking.default


def get_error_message(ux_config: UXConfig, error_type: str = "generic") -> str:
    """
    Get error message from UX config.
    
    Args:
        ux_config: UX configuration
        error_type: Type of error (e.g., 'generic')
        
    Returns:
        Error message string
    """
    return getattr(ux_config.error_states, error_type, "Something went wrong.")


def get_empty_state_message(ux_config: UXConfig, state_type: str = "no_results") -> str:
    """
    Get empty state message from UX config.
    
    Args:
        ux_config: UX configuration
        state_type: Type of empty state (e.g., 'no_results')
        
    Returns:
        Empty state message string
    """
    return getattr(ux_config.empty_states, state_type, "I couldn't find anything relevant.")


def get_unauthorized_message(ux_config: UXConfig) -> str:
    """
    Get unauthorized message from UX config.
    
    Args:
        ux_config: UX configuration
        
    Returns:
        Unauthorized message string
    """
    return ux_config.admin.unauthorized


def get_curator_only_message(ux_config: UXConfig) -> str:
    """
    Get curator-only message from UX config.
    
    Args:
        ux_config: UX configuration
        
    Returns:
        Curator-only message string
    """
    return ux_config.admin.curator_only


def should_send_greeting(ux_config: UXConfig, user_id: str) -> bool:
    """
    Check if we should send a greeting to this user.
    
    Args:
        ux_config: UX configuration
        user_id: Slack user ID
        
    Returns:
        True if greeting should be sent
    """
    if not ux_config.greeting.enabled:
        return False
    
    if user_id in _greeted_users:
        return False
    _greeted_users.add(user_id)
    return True


def get_greeting_message(ux_config: UXConfig) -> str:
    """
    Get the greeting message for first-time DM users.
    
    Args:
        ux_config: UX configuration
        
    Returns:
        Greeting message string (empty string if not configured)
    """
    return ux_config.greeting.first_dm


def reset_greeted_users():
    """Reset the set of greeted users. Useful for testing."""
    global _greeted_users
    _greeted_users = set()
