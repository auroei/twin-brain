"""Formatters module for memex-core.

Single owners of response formatting logic:
- ResponseFormatter: How answers look (length, confidence, structure)
- CitationFormatter: How citations are formatted
"""

from .response_formatter import ResponseFormatter, FormattedResponse
from .citation_formatter import CitationFormatter

__all__ = [
    "ResponseFormatter",
    "FormattedResponse",
    "CitationFormatter",
]

