"""
Thread classification module for memex-core.
Contains logic for classifying Slack threads into dimensions.
Enhanced with RAG (similar examples) and Chain-of-Thought reasoning.
Uses externalized Jinja2 templates for prompt management.
"""

import json
import re
from typing import Optional, Tuple

import yaml

from ..models import RoleDefinition, ThreadClassification, LifecycleStatus
from ..utils import truncate_thread_for_classification
from ..prompts import render_prompt, load_prompt
from .client import GeminiClient, rate_limit_gemini_classify


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


def _validate_classification(json_output: dict, role_def: RoleDefinition) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Validate that classification output matches expected themes/products from role definition.
    
    Args:
        json_output: Classification dictionary from LLM
        role_def: RoleDefinition model instance
        
    Returns:
        Tuple of (is_valid, error_message, validated_classification)
    """
    try:
        valid_themes = [t.name for t in role_def.themes]
        valid_products = role_def.products
        
        # Check required fields exist
        required_fields = ["theme", "product", "project", "topic", "thread_name", "summary"]
        for field in required_fields:
            if field not in json_output:
                return False, f"Missing required field: {field}", None
        
        # Validate theme (should match one of the themes or be "Unclassified")
        theme = json_output.get("theme", "Unclassified")
        if theme != "Unclassified" and theme not in valid_themes:
            print(f"⚠️  Warning: Theme '{theme}' not in valid themes list, using 'Unclassified'")
            json_output["theme"] = "Unclassified"
        
        # Validate product (should match one of the products or be "Unclassified")
        product = json_output.get("product", "Unclassified")
        if product != "Unclassified" and product not in valid_products:
            print(f"⚠️  Warning: Product '{product}' not in valid products list, using 'Unclassified'")
            json_output["product"] = "Unclassified"
        
        return True, None, json_output
    except Exception as e:
        return False, f"Validation error: {e}", None


def _extract_classification_json(response_text: str) -> Optional[dict]:
    """
    Extract classification JSON from LLM response, handling both tagged and raw formats.
    
    Args:
        response_text: Raw response from LLM
        
    Returns:
        Parsed JSON dict or None if extraction fails
    """
    # First, try to extract from <classification> tags
    classification_match = re.search(
        r'<classification>\s*(\{.*?\})\s*</classification>',
        response_text,
        re.DOTALL
    )
    if classification_match:
        try:
            return json.loads(classification_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Fall back to finding JSON anywhere in response
    json_start = response_text.find('{')
    json_end = response_text.rfind('}') + 1
    
    if json_start >= 0 and json_end > json_start:
        try:
            return json.loads(response_text[json_start:json_end])
        except json.JSONDecodeError:
            pass
    
    return None


class ThreadClassifier:
    """
    Classifier for categorizing Slack threads into dimensions.
    Takes a GeminiClient as a dependency for LLM calls.
    
    Enhanced with:
    - RAG: Retrieves similar classified threads as few-shot examples
    - Chain-of-Thought: Uses scratchpad for step-by-step reasoning
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize ThreadClassifier.
        
        Args:
            client: GeminiClient instance for making LLM calls
        """
        self.client = client
    
    def _get_similar_examples(self, thread_text: str, vector_store, n_examples: int = 5) -> str:
        """
        Retrieve similar already-classified threads as few-shot examples.
        
        Args:
            thread_text: The thread text to find similar examples for
            vector_store: ChromaVectorStore instance to query
            n_examples: Number of similar examples to retrieve
            
        Returns:
            Formatted string of similar examples, or empty string if none found
        """
        if not vector_store:
            return ""
        
        try:
            # Query for similar threads that have been classified (not "Pending")
            similar = vector_store.collection.query(
                query_texts=[thread_text[:500]],  # Use start of thread for query
                n_results=n_examples * 2,  # Get more to filter out Pending
                where={"theme": {"$ne": "Pending"}}  # Only classified threads
            )
            
            if not similar.get("documents") or not similar["documents"][0]:
                return ""
            
            examples = []
            for doc, meta in zip(similar["documents"][0], similar["metadatas"][0]):
                # Skip if missing classification metadata
                theme = meta.get("theme", "")
                if not theme or theme == "Pending" or theme == "Unclassified":
                    continue
                
                # Format as example block
                example = f"""<example>
  <thread>{doc[:300]}...</thread>
  <classification>
    theme: {meta.get('theme', 'Unknown')}
    product: {meta.get('product', 'Unknown')}
    project: {meta.get('project', 'Unknown')}
    topic: {meta.get('topic', 'Unknown')}
    thread_name: {meta.get('thread_name', 'Unknown')}
  </classification>
</example>"""
                examples.append(example)
                
                if len(examples) >= n_examples:
                    break
            
            if examples:
                return "\n".join(examples)
            
        except Exception as e:
            print(f"⚠️  Error retrieving similar examples: {e}")
        
        return ""
    
    @rate_limit_gemini_classify(calls_per_minute=8)
    def classify_thread(
        self,
        thread_text: str,
        role_def: RoleDefinition,
        behavior_config: Optional[dict] = None,
        vector_store=None
    ) -> ThreadClassification:
        """
        Classify a thread into 5 dimensions using Gemini (background task).
        Rate limited to 8 calls per minute (classification).
        
        Enhanced with RAG (similar examples) and Chain-of-Thought reasoning.
        
        Args:
            thread_text: Full text content of the thread
            role_def: RoleDefinition model instance
            behavior_config: Optional dict with behavior configuration (personality)
            vector_store: Optional ChromaVectorStore for RAG-based few-shot examples
            
        Returns:
            ThreadClassification model instance
        """
        # Truncate thread text to save tokens
        truncated_thread = truncate_thread_for_classification(thread_text)
        
        # Format role definition for LLM
        role_def_str = _format_role_definition_for_llm(role_def)
        
        # Inject personality tone if provided
        personality_instruction = ""
        if behavior_config and "personality" in behavior_config:
            tone = behavior_config["personality"].get("tone", "")
            if tone:
                personality_instruction = f"\n\nNote: {tone}\n"
        
        # Get similar classified examples for RAG
        similar_examples = self._get_similar_examples(truncated_thread, vector_store)
        
        # Build prompt using externalized template
        prompt = render_prompt(
            "classify",
            personality_instruction=personality_instruction.strip() if personality_instruction else "",
            role_definition=role_def_str,
            similar_examples=similar_examples,
            thread_text=truncated_thread
        )

        try:
            response_text = self.client.call_with_retry(prompt).strip()
            
            # Extract JSON from response (handles both tagged and raw formats)
            classification_dict = _extract_classification_json(response_text)
            
            if classification_dict:
                # Validate classification against role definition
                is_valid, error_msg, validated = _validate_classification(classification_dict, role_def)
                
                if is_valid and validated:
                    return ThreadClassification(**validated)
                else:
                    print(f"⚠️  Classification validation failed: {error_msg}")
                    return ThreadClassification(
                        theme="Unclassified",
                        product="Unclassified",
                        project="Ad-hoc",
                        topic="Unclassified",
                        thread_name="Unclassified Thread",
                        summary="Validation failed"
                    )
            else:
                print(f"⚠️  Could not parse classification JSON: {response_text[:200]}...")
                return ThreadClassification(
                    theme="Unclassified",
                    product="Unclassified",
                    project="Ad-hoc",
                    topic="Unclassified",
                    thread_name="Unclassified Thread",
                    summary="Classification parsing failed"
                )
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON decode error in classification: {e}")
            return ThreadClassification(
                theme="Unclassified",
                product="Unclassified",
                project="Ad-hoc",
                topic="Unclassified",
                thread_name="Unclassified Thread",
                summary="JSON decode error"
            )
        except Exception as e:
            print(f"⚠️  Error classifying thread: {e}")
            return ThreadClassification(
                theme="Unclassified",
                product="Unclassified",
                project="Ad-hoc",
                topic="Unclassified",
                thread_name="Unclassified Thread",
                summary=f"Classification error: {str(e)}"
            )
