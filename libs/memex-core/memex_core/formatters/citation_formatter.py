"""Citation Formatter: Single owner of how citations look.

ITERATION GUIDE:
- To change inline citation format: modify `_format_inline()`
- To change footer citation format: modify `_format_footer()`
- To change max citations: pass max_citations to constructor
"""

from typing import List, Dict, Any, Optional


class CitationFormatter:
    """
    Formats citations for inclusion in responses.
    
    This class is the SINGLE OWNER of citation format decisions:
    - Inline vs footer format
    - Max number of citations
    - Citation text formatting
    
    Usage:
        formatter = CitationFormatter(format_type="inline", max_citations=3)
        citation_text = formatter.format_citations(citations)
    """
    
    def __init__(
        self,
        format_type: str = "inline",
        max_citations: int = 3,
    ):
        """
        Initialize citation formatter.
        
        Args:
            format_type: "inline", "footer", or "none"
            max_citations: Maximum number of citations to include
        """
        self.format_type = format_type
        self.max_citations = max_citations
    
    def format_citations(
        self,
        citations: List[Dict[str, Any]],
    ) -> str:
        """
        Format citations into a string.
        
        Args:
            citations: List of citation dicts. Each should have:
                - thread_name: Name/title of the thread
                - thread_ts: Timestamp of the thread (optional)
                - channel_id: Channel ID (optional, for links)
                - summary: Brief summary (optional)
                
        Returns:
            Formatted citation string, or empty string if none
        """
        if not citations or self.format_type == "none":
            return ""
        
        # Limit to max citations
        citations = citations[:self.max_citations]
        
        if self.format_type == "inline":
            return self._format_inline(citations)
        elif self.format_type == "footer":
            return self._format_footer(citations)
        else:
            return ""
    
    def _format_inline(self, citations: List[Dict[str, Any]]) -> str:
        """
        Format citations inline (mentioned naturally in text).
        
        EDIT HERE to change inline citation format.
        
        For inline, we don't append anything - the LLM should have
        incorporated source references naturally. This is a no-op.
        """
        # Inline citations should be part of the answer itself,
        # handled by the prompt. We don't append anything.
        return ""
    
    def _format_footer(self, citations: List[Dict[str, Any]]) -> str:
        """
        Format citations as a footer section.
        
        EDIT HERE to change footer citation format.
        """
        if not citations:
            return ""
        
        lines = ["📚 **Sources:**"]
        
        for i, cite in enumerate(citations, 1):
            thread_name = cite.get("thread_name", "Unknown thread")
            summary = cite.get("summary", "")
            
            # Build citation line
            if summary:
                lines.append(f"  {i}. _{thread_name}_ — {summary}")
            else:
                lines.append(f"  {i}. _{thread_name}_")
        
        return "\n".join(lines)
    
    def format_single_citation(self, citation: Dict[str, Any]) -> str:
        """
        Format a single citation for reference.
        
        Args:
            citation: Citation dict with thread_name, etc.
            
        Returns:
            Formatted single citation string
        """
        thread_name = citation.get("thread_name", "Unknown thread")
        return f"_{thread_name}_"

