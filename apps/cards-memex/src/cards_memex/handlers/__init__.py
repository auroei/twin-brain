"""Slack event handlers.

This module provides factory functions that create event handlers
with the necessary dependencies injected.
"""
from .mentions import create_mention_handler
from .messages import create_message_handler
from .reactions import create_reaction_handler

__all__ = [
    "create_mention_handler",
    "create_message_handler", 
    "create_reaction_handler",
]
