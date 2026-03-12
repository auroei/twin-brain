"""
Memory extractor: Decomposes threads into atomic, self-contained facts.

This addresses a core RAG failure: "chunks lack context when isolated from conversation."
Each extracted memory resolves ambiguous references (pronouns, "this", "that", etc.)
and includes temporal grounding.
"""

import json
import re
from datetime import datetime
from typing import List, Optional

from ..models import (
    AtomicMemory,
    MemoryRelation,
    TemporalMetadata,
    MemoryExtractionResult,
    RoleDefinition,
)
from ..prompts import render_prompt
from ..utils import parse_datetime_robust
from .client import GeminiClient


class MemoryExtractor:
    """
    Extracts atomic memories from thread text.
    
    Key capabilities:
    1. Decompose threads into single facts
    2. Resolve ambiguous references (pronouns → names)
    3. Extract temporal metadata (document date vs event date)
    4. Identify entities (people, projects, products)
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize MemoryExtractor.
        
        Args:
            client: GeminiClient for LLM calls
        """
        self.client = client
    
    def extract_memories(
        self,
        thread_text: str,
        thread_ts: str,
        channel_id: str,
        role_def: Optional[RoleDefinition] = None,
        existing_memories: Optional[List[AtomicMemory]] = None,
    ) -> MemoryExtractionResult:
        """
        Extract atomic memories from a thread.
        
        Args:
            thread_text: Formatted thread text
            thread_ts: Thread timestamp
            channel_id: Channel ID for context
            role_def: Optional RoleDefinition for domain context
            existing_memories: Optional list of existing memories for relationship detection
            
        Returns:
            MemoryExtractionResult with list of AtomicMemory objects
        """
        # Calculate document date from thread_ts
        try:
            doc_date = datetime.fromtimestamp(float(thread_ts))
        except (ValueError, TypeError):
            doc_date = datetime.now()
        
        # Build context for extraction
        domain_context = ""
        if role_def:
            domain_context = f"""
Domain: {role_def.role}
Products: {', '.join(role_def.products)}
Common Topics: {', '.join(role_def.topics)}
"""
        
        # Build prompt for memory extraction
        prompt = self._build_extraction_prompt(
            thread_text=thread_text,
            document_date=doc_date.isoformat(),
            domain_context=domain_context,
        )
        
        try:
            response = self.client.call_with_retry(prompt)
            memories = self._parse_extraction_response(
                response=response,
                thread_ts=thread_ts,
                document_date=doc_date,
            )
            
            # Detect relationships with existing memories if provided
            if existing_memories and memories:
                memories = self._detect_relationships(memories, existing_memories)
            
            return MemoryExtractionResult(
                thread_ts=thread_ts,
                memories=memories,
                extraction_metadata={
                    "document_date": doc_date.isoformat(),
                    "memory_count": len(memories),
                    "channel_id": channel_id,
                }
            )
            
        except Exception as e:
            print(f"⚠️ Memory extraction failed for {thread_ts}: {e}")
            return MemoryExtractionResult(
                thread_ts=thread_ts,
                memories=[],
                extraction_metadata={"error": str(e)}
            )
    
    def _build_extraction_prompt(
        self,
        thread_text: str,
        document_date: str,
        domain_context: str,
    ) -> str:
        """Build the prompt for memory extraction using Jinja2 template."""
        # Truncate thread text to prevent context overflow
        truncated_text = thread_text[:6000]
        
        return render_prompt(
            "extract_memories",
            thread_text=truncated_text,
            document_date=document_date,
            domain_context=domain_context,
        )
    
    def _parse_extraction_response(
        self,
        response: str,
        thread_ts: str,
        document_date: datetime,
    ) -> List[AtomicMemory]:
        """Parse the LLM response into AtomicMemory objects."""
        memories = []
        
        # Extract JSON from response - try tagged format first
        match = re.search(r'<memories>\s*(\[.*?\])\s*</memories>', response, re.DOTALL)
        if not match:
            # Try to find JSON array directly
            match = re.search(r'\[.*\]', response, re.DOTALL)
        
        if not match:
            print("⚠️ Could not parse memories from response")
            return memories
        
        try:
            json_str = match.group(1) if match.lastindex else match.group(0)
            raw_memories = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decode error: {e}")
            return memories
        
        for idx, raw in enumerate(raw_memories):
            if not isinstance(raw, dict) or "fact" not in raw:
                continue
            
            # Parse event dates using robust helper
            event_dates = []
            for date_str in raw.get("event_dates", []):
                parsed_date = parse_datetime_robust(date_str)
                if parsed_date:
                    event_dates.append(parsed_date)
            
            # Create temporal metadata
            temporal = TemporalMetadata(
                document_date=document_date,
                event_dates=event_dates,
                is_future_event=raw.get("is_future", False),
                temporal_references=raw.get("temporal_refs", []),
            )
            
            memory = AtomicMemory(
                id=f"mem_{thread_ts}_{idx}",
                fact=raw["fact"],
                source_thread_ts=thread_ts,
                source_chunk_content="",  # Will be populated during storage
                chunk_index=idx,
                entities=raw.get("entities", []),
                temporal=temporal,
                confidence=raw.get("confidence", 0.8),
            )
            memories.append(memory)
        
        return memories
    
    def _detect_relationships(
        self,
        new_memories: List[AtomicMemory],
        existing_memories: List[AtomicMemory],
    ) -> List[AtomicMemory]:
        """
        Detect relationships between new and existing memories.
        
        Uses a single batched LLM call for efficiency (instead of N calls for N memories).
        
        Relationship types:
        - UPDATES: New memory contradicts/replaces existing
        - EXTENDS: New memory adds detail to existing
        - DERIVES: New memory is inferred from multiple existing
        """
        if not existing_memories or not new_memories:
            return new_memories
        
        # Build context for relationship detection
        existing_facts = "\n".join([
            f"[{m.id}] {m.fact}" 
            for m in existing_memories[-50:]  # Limit to recent memories
        ])
        
        # Build list of new memories for batch processing
        new_facts = "\n".join([
            f"[{i}] {m.fact}"
            for i, m in enumerate(new_memories)
        ])
        
        # Single batched prompt for all new memories
        prompt = f"""Analyze relationships between these NEW memories and EXISTING memories.

## New Memories (to analyze):
{new_facts}

## Existing Memories (reference):
{existing_facts}

## Relationship Types:
- UPDATES: New memory contradicts or replaces an existing memory (e.g., "budget is now $75k" updates "budget is $50k")
- EXTENDS: New memory adds detail without contradiction (e.g., "timeline is Q2" extends "we're launching the product")
- DERIVES: New memory is a logical inference from combining existing memories
- NONE: No relationship with any existing memory

For EACH new memory, output a JSON object. Return all results inside <relations> tags as a JSON array:

<relations>
[
  {{"new_idx": 0, "type": "UPDATES", "related_ids": ["mem_xxx_0"], "reason": "contradicts previous budget"}},
  {{"new_idx": 1, "type": "NONE", "related_ids": [], "reason": "no relationship found"}},
  {{"new_idx": 2, "type": "EXTENDS", "related_ids": ["mem_yyy_1"], "reason": "adds timeline detail"}}
]
</relations>

Analyze all {len(new_memories)} new memories and return relationships for each:

<relations>
"""
        
        try:
            response = self.client.call_with_retry(prompt)
            
            # Parse the batched response
            match = re.search(r'<relations>\s*(\[.*?\])\s*</relations>', response, re.DOTALL)
            if not match:
                # Try to find JSON array directly
                match = re.search(r'\[.*\]', response, re.DOTALL)
            
            if match:
                json_str = match.group(1) if match.lastindex else match.group(0)
                relations_data = json.loads(json_str)
                
                # Apply relationships to memories
                for rel_data in relations_data:
                    if not isinstance(rel_data, dict):
                        continue
                    
                    new_idx = rel_data.get("new_idx")
                    if new_idx is None or not isinstance(new_idx, int) or new_idx >= len(new_memories):
                        continue
                    
                    rel_type = rel_data.get("type", "NONE").upper()
                    
                    if rel_type in ["UPDATES", "EXTENDS", "DERIVES"]:
                        memory = new_memories[new_idx]
                        memory.relation_type = MemoryRelation(rel_type.lower())
                        memory.related_memory_ids = rel_data.get("related_ids", [])
                        
                        # If this updates another memory, mark the old one as not latest
                        if rel_type == "UPDATES":
                            for existing in existing_memories:
                                if existing.id in memory.related_memory_ids:
                                    existing.is_latest = False
                                    
        except json.JSONDecodeError as e:
            print(f"⚠️ Relationship detection JSON parse failed: {e}")
        except Exception as e:
            print(f"⚠️ Relationship detection failed: {e}")
        
        return new_memories

