#!/usr/bin/env python3
"""
Rapid Iteration Test Harness

Use this to test individual components without running the full bot.
This enables quick iteration on specific dimensions.

Usage:
    # Test response formatting
    python scripts/test_harness.py format "Your raw answer here"
    
    # Test formatting with low confidence
    python scripts/test_harness.py format "Answer text" --confidence 0.3
    
    # Test classification on sample text
    python scripts/test_harness.py classify "Thread text here"
    
    # Test retrieval (returns raw results, no generation)
    python scripts/test_harness.py retrieve "Your question here"
    
    # Test full pipeline (retrieval + generation)
    python scripts/test_harness.py answer "Your question here"
    
    # Compare two prompt versions
    python scripts/test_harness.py compare-prompts answer
    
    # Test thinking messages
    python scripts/test_harness.py thinking
    
    # Test error messages
    python scripts/test_harness.py errors
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Setup paths
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(APP_DIR / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))

from dotenv import load_dotenv

# Load environment
load_dotenv(dotenv_path=APP_DIR / ".env")


def test_format(raw_answer: str, confidence: float = 0.8, days_old: int = 0):
    """Test response formatting in isolation."""
    from memex_core import ResponseFormatter
    from twin_brain.config_loader import load_all_configs
    from twin_brain.paths import CONFIG_DIR
    
    configs = load_all_configs(CONFIG_DIR)
    
    # Convert Pydantic models to dicts for ResponseFormatter
    output_dict = configs.output.model_dump()
    ux_dict = configs.ux.model_dump()
    
    formatter = ResponseFormatter(output_dict, ux_dict)
    
    # Calculate oldest source date if days_old specified
    oldest_date = None
    if days_old > 0:
        oldest_date = datetime.now() - timedelta(days=days_old)
    
    result = formatter.format_answer(
        raw_answer,
        confidence=confidence,
        oldest_source_date=oldest_date
    )
    
    print("=" * 60)
    print("RESPONSE FORMAT TEST")
    print("=" * 60)
    print(f"Input length: {result.original_length}")
    print(f"Output length: {len(result.text)}")
    print(f"Was truncated: {result.was_truncated}")
    print(f"Confidence applied: {result.confidence_applied}")
    print(f"Staleness warning: {result.staleness_warning_applied}")
    print(f"Confidence score: {confidence}")
    if days_old > 0:
        print(f"Source age: {days_old} days")
    print("-" * 60)
    print("OUTPUT:")
    print(result.text)
    print("=" * 60)


def test_thinking():
    """Test thinking/loading messages."""
    from memex_core import ResponseFormatter
    from twin_brain.config_loader import load_all_configs
    from twin_brain.paths import CONFIG_DIR
    
    configs = load_all_configs(CONFIG_DIR)
    ux_dict = configs.ux.model_dump()
    
    formatter = ResponseFormatter(ux_config=ux_dict)
    
    print("=" * 60)
    print("THINKING MESSAGES TEST")
    print("=" * 60)
    print("Generating 5 random thinking messages:\n")
    
    for i in range(5):
        msg = formatter.get_thinking_message(use_variant=True)
        print(f"  {i+1}. {msg}")
    
    print("\n" + "-" * 60)
    print("Default message:")
    print(f"  {formatter.get_thinking_message(use_variant=False)}")
    print("=" * 60)


def test_errors():
    """Test error messages."""
    from memex_core import ResponseFormatter
    from twin_brain.config_loader import load_all_configs
    from twin_brain.paths import CONFIG_DIR
    
    configs = load_all_configs(CONFIG_DIR)
    ux_dict = configs.ux.model_dump()
    
    formatter = ResponseFormatter(ux_config=ux_dict)
    
    print("=" * 60)
    print("ERROR MESSAGES TEST")
    print("=" * 60)
    
    error_types = ["generic", "rate_limited", "api_error"]
    for error_type in error_types:
        msg = formatter.get_error_message(error_type)
        print(f"\n{error_type}:")
        print(f"  {msg}")
    
    print("\n" + "-" * 60)
    print("EMPTY STATE MESSAGES:")
    
    empty_types = ["no_results", "no_context"]
    for empty_type in empty_types:
        msg = formatter.get_empty_message(empty_type)
        print(f"\n{empty_type}:")
        print(f"  {msg}")
    
    print("=" * 60)


def test_classify(thread_text: str):
    """Test classification in isolation."""
    from twin_brain.paths import CONFIG_DIR, ROLE_FILE
    from twin_brain.config_loader import load_all_configs
    from memex_core import GeminiClient, ThreadClassifier, load_role_definition
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set")
        return
    
    configs = load_all_configs(CONFIG_DIR)
    role_def = load_role_definition(role_file=str(ROLE_FILE))
    client = GeminiClient(api_key=api_key)
    classifier = ThreadClassifier(client)
    
    print("=" * 60)
    print("CLASSIFICATION TEST")
    print("=" * 60)
    print(f"Thread text ({len(thread_text)} chars):")
    print(thread_text[:200] + "..." if len(thread_text) > 200 else thread_text)
    print("-" * 60)
    
    behavior_dict = configs.behavior.model_dump()
    
    result = classifier.classify_thread(
        thread_text,
        role_def,
        behavior_config=behavior_dict
    )
    
    print("CLASSIFICATION RESULT:")
    print(f"  Theme: {result.theme}")
    print(f"  Product: {result.product}")
    print(f"  Project: {result.project}")
    print(f"  Topic: {result.topic}")
    print(f"  Thread Name: {result.thread_name}")
    print(f"  Summary: {result.summary}")
    print("=" * 60)


def test_retrieve(query: str, n_results: int = 5):
    """Test retrieval in isolation (no generation)."""
    from twin_brain.paths import CONFIG_DIR, KNOWLEDGE_BASE_DIR
    from twin_brain.config_loader import load_all_configs
    from memex_core import ChromaVectorStore, GeminiClient
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set")
        return
    
    configs = load_all_configs(CONFIG_DIR)
    client = GeminiClient(api_key=api_key)
    store = ChromaVectorStore(
        persist_directory=str(KNOWLEDGE_BASE_DIR),
        collection_name="slack_knowledge",
        api_key=api_key,
        context_client=client,
    )
    
    print("=" * 60)
    print("RETRIEVAL TEST")
    print("=" * 60)
    print(f"Query: {query}")
    print(f"Requesting: {n_results} results")
    print("-" * 60)
    
    results = store.collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    
    print(f"Found: {len(docs)} results")
    print("-" * 60)
    
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        similarity = max(0, 1 - dist / 2)
        print(f"\n[{i+1}] Similarity: {similarity:.2%}")
        print(f"    Thread: {meta.get('thread_name', 'Unknown')}")
        print(f"    Theme: {meta.get('theme', 'Unknown')}")
        print(f"    Preview: {doc[:150]}...")
    
    print("=" * 60)


def test_answer(query: str):
    """Test full answer pipeline."""
    from twin_brain.paths import CONFIG_DIR, KNOWLEDGE_BASE_DIR, ROLE_FILE
    from twin_brain.config_loader import load_all_configs
    from memex_core import (
        GeminiClient, ChromaVectorStore, AnswerGenerator,
        RetrievalPipeline, load_role_definition, ResponseFormatter
    )
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not set")
        return
    
    configs = load_all_configs(CONFIG_DIR)
    role_def = load_role_definition(role_file=str(ROLE_FILE))
    
    client = GeminiClient(api_key=api_key)
    store = ChromaVectorStore(
        persist_directory=str(KNOWLEDGE_BASE_DIR),
        collection_name="slack_knowledge",
        api_key=api_key,
        context_client=client,
    )
    generator = AnswerGenerator(client)
    
    priority_dict = configs.priority.model_dump()
    
    pipeline = RetrievalPipeline(
        store, generator,
        reranker_client=client,
        priority_config=priority_dict
    )
    
    print("=" * 60)
    print("FULL ANSWER TEST")
    print("=" * 60)
    print(f"Query: {query}")
    print("-" * 60)
    print("Generating answer...")
    
    behavior_dict = configs.behavior.model_dump()
    retrieval_dict = configs.retrieval.model_dump()
    output_dict = configs.output.model_dump()
    ux_dict = configs.ux.model_dump()
    
    result = pipeline.answer_question_with_sources(
        query=query,
        role_def=role_def,
        behavior_config=behavior_dict,
        retrieval_config=retrieval_dict,
        output_config=output_dict,
    )
    
    # Apply our formatter
    formatter = ResponseFormatter(output_dict, ux_dict)
    formatted = formatter.format_answer(result["answer"], confidence=result["confidence"])
    
    print("\nRAW ANSWER:")
    print(result["answer"][:500] + "..." if len(result["answer"]) > 500 else result["answer"])
    print("\n" + "-" * 60)
    print("FORMATTED ANSWER:")
    print(formatted.text)
    print("-" * 60)
    print(f"Confidence: {result['confidence']:.2%}")
    print(f"Sources used: {result['source_count']}")
    print(f"Memories used: {result.get('memories_used', 0)}")
    print(f"Was truncated: {formatted.was_truncated}")
    print(f"Confidence applied: {formatted.confidence_applied}")
    print("=" * 60)


def compare_prompts(prompt_name: str):
    """Compare library prompt vs app prompt."""
    from memex_core.prompts import get_prompt_source
    from twin_brain.paths import PROMPTS_DIR
    
    # Library prompts directory
    lib_prompts_dir = PROJECT_ROOT / "libs" / "memex-core" / "memex_core" / "prompts"
    
    print("=" * 60)
    print(f"PROMPT COMPARISON: {prompt_name}")
    print("=" * 60)
    
    source = get_prompt_source(prompt_name)
    print(f"Active source: {source}")
    
    lib_path = lib_prompts_dir / f"{prompt_name}.jinja2"
    app_path = PROMPTS_DIR / f"{prompt_name}.jinja2"
    
    print("-" * 60)
    
    if lib_path.exists():
        print("LIBRARY VERSION:")
        content = lib_path.read_text()
        print(content[:500] + "..." if len(content) > 500 else content)
    else:
        print("LIBRARY VERSION: Not found")
    
    print("-" * 60)
    
    if app_path.exists():
        print("APP VERSION:")
        content = app_path.read_text()
        print(content[:500] + "..." if len(content) > 500 else content)
    else:
        print("APP VERSION: Not found (using library)")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for rapid iteration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_harness.py format "Here is a long answer..."
  python test_harness.py format "Answer" --confidence 0.3
  python test_harness.py format "Answer" --days-old 45
  python test_harness.py classify "We decided to go with option A"
  python test_harness.py retrieve "What is the status of project X?"
  python test_harness.py answer "What did we decide about pricing?"
  python test_harness.py compare-prompts answer
  python test_harness.py thinking
  python test_harness.py errors
        """
    )
    
    parser.add_argument(
        "command",
        choices=["format", "classify", "retrieve", "answer", "compare-prompts", "thinking", "errors"],
        help="What to test"
    )
    
    parser.add_argument(
        "input",
        nargs="?",
        help="Input text or query"
    )
    
    parser.add_argument(
        "--confidence", "-c",
        type=float,
        default=0.8,
        help="Confidence score for format test (default: 0.8)"
    )
    
    parser.add_argument(
        "--days-old", "-d",
        type=int,
        default=0,
        help="Days old for staleness warning test (default: 0, no staleness)"
    )
    
    parser.add_argument(
        "--n-results", "-n",
        type=int,
        default=5,
        help="Number of results for retrieve test (default: 5)"
    )
    
    args = parser.parse_args()
    
    if args.command == "format":
        if not args.input:
            # Use sample input
            args.input = """Based on the discussions I found, the team decided to proceed with the mobile-first approach for Q3. Key points:

1. The mobile app will be prioritized over desktop
2. Budget allocation shifted to 60% mobile, 40% desktop  
3. Timeline remains unchanged - launch by end of Q3

John mentioned concerns about the desktop user base, but the data shows 70% of engagement is mobile. Sarah will lead the mobile workstream.

Let me know if you need more details on any of these points!"""
        test_format(args.input, args.confidence, args.days_old)
    
    elif args.command == "classify":
        if not args.input:
            args.input = "[U123]: We need to finalize the pricing for Visa Infinite\n[U456]: I think we should go with tier 2 pricing based on the analysis\n[U123]: Approved. Let's move forward with that."
        test_classify(args.input)
    
    elif args.command == "retrieve":
        if not args.input:
            args.input = "What is the status of the project?"
        test_retrieve(args.input, args.n_results)
    
    elif args.command == "answer":
        if not args.input:
            args.input = "What did we decide about pricing?"
        test_answer(args.input)
    
    elif args.command == "compare-prompts":
        if not args.input:
            args.input = "answer"
        compare_prompts(args.input)
    
    elif args.command == "thinking":
        test_thinking()
    
    elif args.command == "errors":
        test_errors()


if __name__ == "__main__":
    main()

