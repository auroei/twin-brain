"""Response Formatter: Single owner of how answers look.

ITERATION GUIDE:
- To change answer length: modify `_truncate_answer()` 
- To change confidence messaging: modify `_apply_confidence_prefix()`
- To change truncation behavior: modify `_truncate_answer()`
- To change structure (bullets vs prose): modify `_apply_structure()`
- To change staleness warnings: modify `_apply_staleness_warning()`
- To change thinking messages: modify `get_thinking_message()`
- To change error messages: modify `get_error_message()`

All response format changes should happen HERE, not in:
- generator.py (that's for LLM calls)
- retrieval.py (that's for retrieval logic)
- prompts/ (that's for prompt engineering)
"""

import random
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class FormattedResponse:
    """Formatted response with metadata for debugging."""
    text: str
    was_truncated: bool = False
    confidence_applied: bool = False
    staleness_warning_applied: bool = False
    original_length: int = 0


@dataclass
class OutputConfig:
    """
    Output configuration for response formatting.
    
    Can be initialized from a dict (for compatibility) or with typed fields.
    """
    # Length settings
    max_chars: int = 800
    length_mode: str = "concise"  # "concise", "detailed", "auto"
    concise_target: int = 200
    detailed_target: int = 600
    
    # Structure settings
    structure_mode: str = "auto"  # "bullets", "prose", "auto"
    bullet_threshold: int = 3
    
    # Citation settings
    citations_enabled: bool = True
    citations_format: str = "inline"  # "inline", "footer", "none"
    max_citations: int = 3
    
    # Confidence settings
    confidence_threshold: float = 0.5
    low_confidence_behavior: str = "qualify"  # "qualify", "refuse", "proceed"
    
    # Formatting settings
    use_markdown: bool = True
    use_emoji: bool = False
    
    # Staleness settings
    staleness_warn_after_days: int = 30
    staleness_warning_template: str = "⚠️ Note: The most relevant information I found is from {age} ago."
    
    @classmethod
    def from_dict(cls, config_dict: Optional[Dict[str, Any]] = None) -> "OutputConfig":
        """
        Create OutputConfig from a dictionary (e.g., from YAML config).
        
        Args:
            config_dict: Dictionary with output configuration
            
        Returns:
            OutputConfig instance with values from dict or defaults
        """
        if not config_dict:
            return cls()
        
        length_cfg = config_dict.get("length", {})
        structure_cfg = config_dict.get("structure", {})
        citations_cfg = config_dict.get("citations", {})
        confidence_cfg = config_dict.get("confidence", {})
        formatting_cfg = config_dict.get("formatting", {})
        staleness_cfg = config_dict.get("staleness", {})
        
        return cls(
            max_chars=length_cfg.get("max_chars", 800),
            length_mode=length_cfg.get("default", "concise"),
            concise_target=length_cfg.get("concise_target", 200),
            detailed_target=length_cfg.get("detailed_target", 600),
            structure_mode=structure_cfg.get("default", "auto"),
            bullet_threshold=structure_cfg.get("bullet_threshold", 3),
            citations_enabled=citations_cfg.get("enabled", True),
            citations_format=citations_cfg.get("format", "inline"),
            max_citations=citations_cfg.get("max_citations", 3),
            confidence_threshold=confidence_cfg.get("threshold", 0.5),
            low_confidence_behavior=confidence_cfg.get("low_confidence_behavior", "qualify"),
            use_markdown=formatting_cfg.get("use_markdown", True),
            use_emoji=formatting_cfg.get("use_emoji", False),
            staleness_warn_after_days=staleness_cfg.get("warn_after_days", 30),
            staleness_warning_template=staleness_cfg.get(
                "warning_template",
                "⚠️ Note: The most relevant information I found is from {age} ago."
            ),
        )


@dataclass
class UXConfig:
    """
    UX configuration for thinking messages, errors, and empty states.
    
    Can be initialized from a dict (for compatibility) or with typed fields.
    """
    # Thinking/loading messages
    thinking_default: str = "🔍 Searching my memory..."
    thinking_variants: List[str] = field(default_factory=lambda: [
        "🔍 Searching my memory...",
        "🧠 Let me think about that...",
        "📚 Checking my notes...",
        "💭 Processing your question...",
    ])
    
    # Empty state messages
    empty_no_results: str = "I couldn't find anything relevant in my memory."
    empty_no_context: str = "I don't have any context on this topic yet."
    
    # Error messages
    error_generic: str = "Something went wrong while processing your question."
    error_rate_limited: str = "I'm getting a lot of questions right now. Please wait a moment."
    error_api_error: str = "I'm having trouble connecting. Please try again shortly."
    
    # Success prefixes
    low_confidence_prefix: str = "I'm not entirely certain, but based on what I've seen: "
    partial_match_prefix: str = "I found some related information: "
    
    @classmethod
    def from_dict(cls, config_dict: Optional[Dict[str, Any]] = None) -> "UXConfig":
        """
        Create UXConfig from a dictionary (e.g., from YAML config).
        
        Args:
            config_dict: Dictionary with UX configuration
            
        Returns:
            UXConfig instance with values from dict or defaults
        """
        if not config_dict:
            return cls()
        
        thinking_cfg = config_dict.get("thinking", {})
        empty_cfg = config_dict.get("empty_states", {})
        error_cfg = config_dict.get("error_states", {})
        success_cfg = config_dict.get("success", {})
        
        return cls(
            thinking_default=thinking_cfg.get("default", "🔍 Searching my memory..."),
            thinking_variants=thinking_cfg.get("variants", [
                "🔍 Searching my memory...",
                "🧠 Let me think about that...",
                "📚 Checking my notes...",
                "💭 Processing your question...",
            ]),
            empty_no_results=empty_cfg.get("no_results", "I couldn't find anything relevant in my memory."),
            empty_no_context=empty_cfg.get("no_context", "I don't have any context on this topic yet."),
            error_generic=error_cfg.get("generic", "Something went wrong while processing your question."),
            error_rate_limited=error_cfg.get("rate_limited", "I'm getting a lot of questions right now. Please wait a moment."),
            error_api_error=error_cfg.get("api_error", "I'm having trouble connecting. Please try again shortly."),
            low_confidence_prefix=success_cfg.get("low_confidence_prefix", "I'm not entirely certain, but based on what I've seen: "),
            partial_match_prefix=success_cfg.get("partial_match_prefix", "I found some related information: "),
        )


class ResponseFormatter:
    """
    Formats raw LLM answers into user-facing responses.
    
    This class is the SINGLE OWNER of response format decisions:
    - Length limits and truncation
    - Confidence-based prefixes
    - Staleness warnings
    - Structure (bullets vs prose)
    - Markdown formatting
    - Thinking/loading messages
    - Error messages
    - Empty state messages
    
    Usage:
        formatter = ResponseFormatter(output_config, ux_config)
        result = formatter.format_answer(raw_answer, confidence=0.8)
        send_to_user(result.text)
    """
    
    def __init__(
        self,
        output_config: Optional[OutputConfig] = None,
        ux_config: Optional[UXConfig] = None,
    ):
        """
        Initialize formatter with configuration.
        
        Args:
            output_config: OutputConfig instance or None for defaults.
                          Can also pass a dict which will be converted.
            ux_config: UXConfig instance or None for defaults.
                      Can also pass a dict which will be converted.
        """
        # Handle dict inputs for compatibility
        if isinstance(output_config, dict):
            output_config = OutputConfig.from_dict(output_config)
        if isinstance(ux_config, dict):
            ux_config = UXConfig.from_dict(ux_config)
            
        self.output_config = output_config or OutputConfig()
        self.ux_config = ux_config or UXConfig()
    
    def format_answer(
        self,
        raw_answer: str,
        confidence: float = 1.0,
        source_count: int = 0,
        oldest_source_date: Optional[datetime] = None,
    ) -> FormattedResponse:
        """
        Format a raw LLM answer into a user-facing response.
        
        This is the main entry point. All formatting rules are applied here.
        
        Args:
            raw_answer: Raw text from the LLM
            confidence: Retrieval confidence score (0-1)
            source_count: Number of sources used
            oldest_source_date: Date of oldest source (for staleness warning)
            
        Returns:
            FormattedResponse with the formatted text and metadata
        """
        if not raw_answer or not raw_answer.strip():
            return FormattedResponse(
                text=self._get_empty_response(),
                original_length=0
            )
        
        original_length = len(raw_answer)
        text = raw_answer.strip()
        
        # Step 1: Apply staleness warning if needed
        text, staleness_applied = self._apply_staleness_warning(text, oldest_source_date)
        
        # Step 2: Apply confidence prefix if needed
        text, confidence_applied = self._apply_confidence_prefix(text, confidence)
        
        # Step 3: Truncate if needed
        text, was_truncated = self._truncate_answer(text)
        
        # Step 4: Clean up formatting
        text = self._clean_formatting(text)
        
        return FormattedResponse(
            text=text,
            was_truncated=was_truncated,
            confidence_applied=confidence_applied,
            staleness_warning_applied=staleness_applied,
            original_length=original_length
        )
    
    def _apply_staleness_warning(
        self,
        text: str,
        oldest_source_date: Optional[datetime]
    ) -> tuple[str, bool]:
        """
        Apply staleness warning if sources are old.
        
        EDIT HERE to change staleness warning behavior.
        
        Returns:
            Tuple of (modified_text, was_warning_applied)
        """
        if not oldest_source_date:
            return text, False
        
        days_old = (datetime.now() - oldest_source_date).days
        warn_after = self.output_config.staleness_warn_after_days
        
        if days_old < warn_after:
            return text, False
        
        # Format the age nicely
        if days_old < 30:
            age_str = f"{days_old} days"
        elif days_old < 60:
            age_str = "about a month"
        elif days_old < 365:
            months = days_old // 30
            age_str = f"about {months} months"
        else:
            years = days_old // 365
            age_str = f"over {years} year{'s' if years > 1 else ''}"
        
        warning = self.output_config.staleness_warning_template.format(age=age_str)
        
        # Append warning at the end
        return f"{text}\n\n{warning}", True
    
    def _apply_confidence_prefix(
        self,
        text: str,
        confidence: float
    ) -> tuple[str, bool]:
        """
        Apply confidence-based prefix if confidence is below threshold.
        
        EDIT HERE to change confidence messaging.
        
        Returns:
            Tuple of (modified_text, was_prefix_applied)
        """
        threshold = self.output_config.confidence_threshold
        behavior = self.output_config.low_confidence_behavior
        
        if confidence >= threshold:
            return text, False
        
        if behavior == "qualify":
            # Add uncertainty prefix
            prefix = self.ux_config.low_confidence_prefix
            return prefix + text, True
        
        elif behavior == "refuse":
            # Replace with refusal message
            return (
                "I don't have enough information to confidently answer this. "
                "Could you rephrase your question or provide more context?"
            ), True
        
        else:  # "proceed"
            return text, False
    
    def _truncate_answer(self, text: str) -> tuple[str, bool]:
        """
        Truncate answer to configured max length.
        
        EDIT HERE to change truncation behavior.
        
        Returns:
            Tuple of (truncated_text, was_truncated)
        """
        max_chars = self.output_config.max_chars
        
        if len(text) <= max_chars:
            return text, False
        
        # Try to truncate at sentence boundary
        truncated = text[:max_chars]
        
        # Find last sentence boundary
        last_period = truncated.rfind('.')
        last_question = truncated.rfind('?')
        last_exclaim = truncated.rfind('!')
        
        best_boundary = max(last_period, last_question, last_exclaim)
        
        # Only use boundary if it's reasonably far into the text
        if best_boundary > max_chars * 0.7:
            return truncated[:best_boundary + 1], True
        else:
            return truncated.rstrip() + "...", True
    
    def _clean_formatting(self, text: str) -> str:
        """
        Clean up formatting quirks and convert markdown to Slack format.
        
        EDIT HERE to add/remove formatting cleanup rules.
        """
        # Convert markdown bold (**text**) to Slack bold (*text*)
        # This handles both **text** and cases where there might be spaces
        text = re.sub(r'\*\*([^*]+?)\*\*', r'*\1*', text)
        
        # Remove square bracket citations [Citation Name] - keep just the text
        # This converts inline citations like [Credit Card PA Base Expansion] 
        # to just "Credit Card PA Base Expansion"
        text = re.sub(r'\[([^\]]+)\]', r'\1', text)
        
        # Remove excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        return text.strip()
    
    def _get_empty_response(self) -> str:
        """
        Get the response for empty/no-results case.
        
        EDIT HERE to change the empty state message.
        """
        return self.ux_config.empty_no_results
    
    # =========================================================================
    # Thinking/Loading Messages
    # =========================================================================
    
    def get_thinking_message(self, use_variant: bool = True) -> str:
        """
        Get a thinking/loading message.
        
        EDIT HERE to change thinking message behavior.
        
        Args:
            use_variant: If True, randomly pick from variants. If False, use default.
            
        Returns:
            Thinking message string
        """
        if use_variant and self.ux_config.thinking_variants:
            return random.choice(self.ux_config.thinking_variants)
        return self.ux_config.thinking_default
    
    # =========================================================================
    # Error Messages
    # =========================================================================
    
    def get_error_message(self, error_type: str = "generic") -> str:
        """
        Get an error message.
        
        EDIT HERE to change error messages.
        
        Args:
            error_type: One of "generic", "rate_limited", "api_error"
            
        Returns:
            Error message string
        """
        if error_type == "rate_limited":
            return self.ux_config.error_rate_limited
        elif error_type == "api_error":
            return self.ux_config.error_api_error
        else:
            return self.ux_config.error_generic
    
    # =========================================================================
    # Empty State Messages
    # =========================================================================
    
    def get_empty_message(self, state_type: str = "no_results") -> str:
        """
        Get an empty state message.
        
        EDIT HERE to change empty state messages.
        
        Args:
            state_type: One of "no_results", "no_context"
            
        Returns:
            Empty state message string
        """
        if state_type == "no_context":
            return self.ux_config.empty_no_context
        else:
            return self.ux_config.empty_no_results
    
    # =========================================================================
    # Convenience methods for common formatting needs
    # =========================================================================
    
    def format_with_citations(
        self,
        raw_answer: str,
        citations: List[Dict[str, Any]],
        confidence: float = 1.0,
        oldest_source_date: Optional[datetime] = None,
    ) -> FormattedResponse:
        """
        Format answer with citations appended.
        
        Args:
            raw_answer: Raw LLM answer
            citations: List of citation dicts with 'thread_name', 'thread_ts'
            confidence: Confidence score
            oldest_source_date: Date of oldest source for staleness warning
            
        Returns:
            FormattedResponse with citations included
        """
        from .citation_formatter import CitationFormatter
        
        # First format the base answer
        result = self.format_answer(
            raw_answer,
            confidence,
            source_count=len(citations),
            oldest_source_date=oldest_source_date
        )
        
        # Then append citations if enabled
        if self.output_config.citations_enabled and citations:
            citation_formatter = CitationFormatter(
                format_type=self.output_config.citations_format,
                max_citations=self.output_config.max_citations,
            )
            citation_text = citation_formatter.format_citations(citations)
            
            if citation_text:
                result.text = f"{result.text}\n\n{citation_text}"
        
        return result

