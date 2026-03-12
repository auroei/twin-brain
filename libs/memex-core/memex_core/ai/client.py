"""
AI client module for memex-core.
Contains GeminiClient class setup and rate limiting decorators.
"""

import functools
import os
import threading
import time
from typing import Optional

import google.generativeai as genai


# --- Rate Limiting for Gemini API ---
# Separate rate limiters for Q&A and Classification
_gemini_qa_lock = threading.Lock()
_gemini_qa_call_times = []

_gemini_classify_lock = threading.Lock()
_gemini_classify_call_times = []


def _rate_limit_helper(call_times_list, lock, calls_per_minute, limiter_name):
    """Helper function for rate limiting logic."""
    with lock:
        current_time = time.time()
        # Remove calls older than 1 minute
        call_times_list[:] = [t for t in call_times_list if current_time - t < 60]
        
        # If we've hit the limit, wait until we can make another call
        if len(call_times_list) >= calls_per_minute:
            oldest_call = min(call_times_list)
            wait_time = 60 - (current_time - oldest_call) + 0.1  # Add small buffer
            if wait_time > 0:
                print(f"⏳ Rate limit ({limiter_name}): Waiting {wait_time:.1f}s before next Gemini call...")
                time.sleep(wait_time)
                # Update current_time after waiting
                current_time = time.time()
                # Clean up again after waiting
                call_times_list[:] = [t for t in call_times_list if current_time - t < 60]
        
        # Record this call
        call_times_list.append(time.time())


def rate_limit_gemini_qa(calls_per_minute=12):
    """
    Decorator to rate limit Gemini API calls for Q&A (user questions).
    Uses a sliding window approach with threading lock for thread safety.
    
    Args:
        calls_per_minute: Maximum number of Q&A calls allowed per minute
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _rate_limit_helper(_gemini_qa_call_times, _gemini_qa_lock, calls_per_minute, "Q&A")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def rate_limit_gemini_classify(calls_per_minute=8):
    """
    Decorator to rate limit Gemini API calls for classification (background tasks).
    Uses a sliding window approach with threading lock for thread safety.
    
    Args:
        calls_per_minute: Maximum number of classification calls allowed per minute
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _rate_limit_helper(_gemini_classify_call_times, _gemini_classify_lock, calls_per_minute, "Classification")
            return func(*args, **kwargs)
        return wrapper
    return decorator


class GeminiClient:
    """
    Client for interacting with Google's Gemini API.
    Handles initialization, retries, and provides the base model for classification and Q&A.
    """
    
    def __init__(self, api_key: str, model_name: Optional[str] = None):
        """
        Initialize Gemini client.
        
        Args:
            api_key: Google Gemini API key
            model_name: Optional name of the Gemini model to use.
                       If not provided, loads from GEMINI_MODEL_NAME env var.
                       Defaults to "gemini-2.0-flash" if env var is missing.
        """
        genai.configure(api_key=api_key)
        
        # Determine model name: use argument, then env var, then default
        if model_name is None:
            model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.0-flash")
        
        self.model_name = model_name
        
        # Try to initialize the model with error handling and fallback
        try:
            self.model = genai.GenerativeModel(model_name)
        except Exception as e:
            print(f"❌ Error initializing model '{model_name}': {e}")
            print(f"   Falling back to 'gemini-1.5-flash'")
            try:
                self.model_name = "gemini-1.5-flash"
                self.model = genai.GenerativeModel(self.model_name)
            except Exception as fallback_error:
                print(f"❌ Fallback model initialization also failed: {fallback_error}")
                raise
    
    def call_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        """
        Call Gemini API with exponential backoff retry logic.
        
        Args:
            prompt: Prompt text to send to Gemini
            max_retries: Maximum number of retry attempts
            
        Returns:
            Response text from Gemini
            
        Raises:
            Exception: If all retries fail
        """
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"⚠️  Gemini API error (attempt {attempt + 1}/{max_retries}): {e}")
                    print(f"   Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Gemini API failed after {max_retries} attempts: {e}")
                    raise

