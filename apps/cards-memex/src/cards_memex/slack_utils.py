"""Slack API utilities for cards-memex.

Provides shared functions for interacting with the Slack API.
"""
from typing import Union

from slack_sdk import WebClient
from slack_bolt import App

from memex_core import validate_slack_response
from memex_core.models import SlackThread, SlackMessage


def fetch_thread(
    client: Union[WebClient, App],
    channel_id: str,
    thread_ts: str
) -> SlackThread:
    """
    Fetch thread from Slack API and convert to SlackThread model.
    
    Args:
        client: Slack WebClient or Bolt App instance
        channel_id: Channel ID where thread exists
        thread_ts: Thread timestamp identifier
        
    Returns:
        SlackThread model instance
        
    Raises:
        ValueError: If the Slack response is invalid or empty
    """
    # Handle both App and WebClient
    if hasattr(client, 'client'):
        # It's a Bolt App
        result = client.client.conversations_replies(channel=channel_id, ts=thread_ts)
    else:
        # It's a WebClient
        result = client.conversations_replies(channel=channel_id, ts=thread_ts)
    
    is_valid, error_msg = validate_slack_response(result, thread_ts)
    if not is_valid:
        raise ValueError(error_msg)
    
    slack_messages = [
        SlackMessage(
            user=msg.get("user", "Unknown"),
            text=msg.get("text", ""),
            ts=msg.get("ts", "")
        )
        for msg in result["messages"]
    ]
    
    return SlackThread(
        thread_ts=thread_ts,
        channel_id=channel_id,
        messages=slack_messages,
        classification=None
    )

