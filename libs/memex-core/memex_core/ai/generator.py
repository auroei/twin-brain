"""
Answer generation module for memex-core.
Contains logic for generating answers to user questions using RAG.
Uses externalized Jinja2 templates for prompt management.
Enhanced with output configuration support for response formatting.
"""

from typing import Optional, Dict, Any

import yaml

from ..models import RoleDefinition
from ..prompts import render_prompt
from .client import GeminiClient, rate_limit_gemini_qa


def _format_role_definition_for_llm(role_def: RoleDefinition) -> str:
    """
    Format a RoleDefinition Pydantic object into a string for LLM prompts.
    
    Args:
        role_def: RoleDefinition model instance
        
    Returns:
        Formatted string representation
    """
    role_dict = {
        "role": role_def.role,
        "products": role_def.products,
        "themes": [{"name": t.name, "description": t.description} for t in role_def.themes],
        "topics": role_def.topics
    }
    return yaml.dump(role_dict, default_flow_style=False, sort_keys=False)


class AnswerGenerator:
    """
    Generator for creating answers to user questions using retrieved context.
    Takes a GeminiClient as a dependency for LLM calls.
    
    Enhanced with output configuration support:
    - Response length control (concise/detailed)
    - Structure control (bullets/prose)
    - Citation formatting
    - Confidence-based qualifiers
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize AnswerGenerator.
        
        Args:
            client: GeminiClient instance for making LLM calls
        """
        self.client = client
    
    def _build_output_instructions(self, output_config: Optional[Dict[str, Any]]) -> str:
        """
        Build output instructions string from output config.
        
        Args:
            output_config: Output configuration dict
            
        Returns:
            Formatted instruction string for the prompt
        """
        if not output_config:
            return ""
        
        instructions = []
        
        # Length instructions
        length_cfg = output_config.get("length", {})
        length_mode = length_cfg.get("default", "concise")
        if length_mode == "concise":
            target = length_cfg.get("concise_target", 200)
            instructions.append(f"Keep your response concise (around {target} characters)")
        elif length_mode == "detailed":
            target = length_cfg.get("detailed_target", 600)
            instructions.append(f"Provide a detailed response (around {target} characters)")
        
        # Structure instructions
        structure_cfg = output_config.get("structure", {})
        structure_mode = structure_cfg.get("default", "auto")
        if structure_mode == "bullets":
            instructions.append("Use bullet points for the main content")
        elif structure_mode == "prose":
            instructions.append("Write in flowing prose paragraphs")
        
        # Citation instructions
        citation_cfg = output_config.get("citations", {})
        if citation_cfg.get("enabled", True):
            fmt = citation_cfg.get("format", "inline")
            max_cites = citation_cfg.get("max_citations", 3)
            if fmt == "inline":
                instructions.append(f"Reference sources naturally in your response (max {max_cites})")
            elif fmt == "footer":
                instructions.append(f"Add a 'Sources:' section at the end (max {max_cites})")
        
        # Formatting
        fmt_cfg = output_config.get("formatting", {})
        if fmt_cfg.get("use_markdown", True):
            instructions.append("Use **bold** for key terms")
        
        return "\n".join(f"- {inst}" for inst in instructions) if instructions else ""
    
    def _apply_confidence_handling(
        self,
        answer: str,
        confidence_score: float,
        output_config: Optional[Dict[str, Any]]
    ) -> str:
        """
        Apply confidence-based modifications to the answer.
        
        Args:
            answer: Generated answer
            confidence_score: Confidence score (0-1)
            output_config: Output configuration dict
            
        Returns:
            Modified answer with confidence handling applied
        """
        if not output_config:
            return answer
        
        confidence_cfg = output_config.get("confidence", {})
        threshold = confidence_cfg.get("threshold", 0.5)
        behavior = confidence_cfg.get("low_confidence_behavior", "qualify")
        
        if confidence_score >= threshold:
            return answer
        
        if behavior == "qualify":
            prefix = "I'm not entirely certain, but based on what I found: "
            return prefix + answer
        elif behavior == "refuse":
            return "I don't have enough information to confidently answer this question. Could you rephrase it or provide more context?"
        else:  # "proceed"
            return answer
    
    @rate_limit_gemini_qa(calls_per_minute=12)
    def generate_answer(
        self,
        context: str,
        question: str,
        role_def: RoleDefinition,
        behavior_config: Optional[Dict[str, Any]] = None,
        output_config: Optional[Dict[str, Any]] = None,
        confidence_score: float = 1.0
    ) -> str:
        """
        Generate an answer to a question using context and role definition.
        Rate limited to 12 calls per minute (Q&A).
        Uses externalized Jinja2 template for prompt management.
        
        Args:
            context: Retrieved context from vector database
            question: User's question
            role_def: RoleDefinition model instance for context understanding
            behavior_config: Optional dict with behavior configuration (personality, rate_limits)
            output_config: Optional dict with output configuration (length, structure, citations)
            confidence_score: Confidence in the retrieved context (0-1)
            
        Returns:
            Generated answer string
        """
        # Format role definition for LLM
        role_def_str = _format_role_definition_for_llm(role_def)
        
        # Extract personality tone if provided
        personality_instruction = ""
        if behavior_config and "personality" in behavior_config:
            tone = behavior_config["personality"].get("tone", "")
            if tone:
                personality_instruction = tone
        
        # Determine low confidence flag
        low_confidence = False
        if output_config:
            threshold = output_config.get("confidence", {}).get("threshold", 0.5)
            low_confidence = confidence_score < threshold
        
        # Build prompt using externalized template
        prompt = render_prompt(
            "answer",
            context=context,
            role_context=role_def_str,
            personality_instruction=personality_instruction,
            question=question,
            output_config=output_config,
            low_confidence=low_confidence
        )
        
        answer = self.client.call_with_retry(prompt)
        
        # Apply confidence handling
        answer = self._apply_confidence_handling(answer, confidence_score, output_config)
        
        # Apply length limit if specified
        if output_config:
            max_chars = output_config.get("length", {}).get("max_chars", 800)
            if len(answer) > max_chars:
                # Truncate intelligently at sentence boundary
                truncated = answer[:max_chars]
                last_period = truncated.rfind('.')
                if last_period > max_chars * 0.7:
                    answer = truncated[:last_period + 1]
                else:
                    answer = truncated.rstrip() + "..."
        
        return answer
