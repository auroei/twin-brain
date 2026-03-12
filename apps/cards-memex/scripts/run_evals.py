#!/usr/bin/env python3
"""
Evaluation runner for cards-memex app.
Measures retrieval accuracy and end-to-end answer quality.

This script uses the generic evaluation functions from memex_core.eval
with app-specific configuration and test data.

IMPORTANT: The golden_dataset.jsonl contains placeholder thread IDs
(e.g., "1733500000.000000") that won't match real data. Before running
evaluations:

1. The correct_thread_ids field must contain actual thread timestamps
   from your knowledge base
2. Run `python scripts/reindex_watched.py` to see available thread IDs
3. Update the golden dataset with real thread IDs for accurate recall metrics

Without real thread IDs, retrieval evaluation will always return 0% recall.

Usage:
    python scripts/run_evals.py
    python scripts/run_evals.py --eval-file evals/golden_dataset.jsonl
    python scripts/run_evals.py --retrieval-only
    python scripts/run_evals.py --e2e-only
"""

import argparse
import json
import os
import sys
from pathlib import Path

# App directory is parent of scripts/
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent

# Add src to path for local imports
sys.path.insert(0, str(APP_DIR / "src"))
# Add the libs directory to the path for imports
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))

from dotenv import load_dotenv

# Import paths from cards_memex package
from cards_memex.paths import ENV_FILE, KNOWLEDGE_BASE_DIR, ROLE_FILE

from memex_core import (
    GeminiClient,
    ChromaVectorStore,
    AnswerGenerator,
    RetrievalPipeline,
    load_role_definition,
    # Evaluation functions from library
    evaluate_retrieval,
    evaluate_end_to_end,
)


def load_eval_data(eval_file: str) -> list:
    """
    Load evaluation data from a JSONL file.
    
    Args:
        eval_file: Path to the JSONL file containing evaluation data
        
    Returns:
        List of evaluation items
    """
    eval_data = []
    with open(eval_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:  # Skip empty lines
                try:
                    eval_data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"⚠️  Skipping invalid JSON on line {line_num}: {e}")
    return eval_data


def print_retrieval_results(results: dict) -> None:
    """Print formatted retrieval evaluation results."""
    print("\n" + "=" * 60)
    print("📈 RETRIEVAL EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Precision:  {results['precision']:.2%}")
    print(f"  Recall:     {results['recall']:.2%}")
    print(f"  MRR:        {results['mrr']:.2%}")
    print(f"  F1 Score:   {results['f1']:.2%}")
    print(f"  Evaluated:  {results['total_evaluated']} questions")
    print("=" * 60)


def print_e2e_results(results: dict) -> None:
    """Print formatted end-to-end evaluation results."""
    print("\n" + "=" * 60)
    print("📈 END-TO-END EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Accuracy:   {results['accuracy']:.1f}%")
    print(f"  Correct:    {results['correct_count']}/{results['total_count']}")
    print("=" * 60)


def main():
    """Main entry point for the evaluation script."""
    parser = argparse.ArgumentParser(
        description="Evaluate cards-memex RAG system performance"
    )
    parser.add_argument(
        "--eval-file",
        type=str,
        default="evals/golden_dataset.jsonl",
        help="Path to evaluation dataset relative to app dir (JSONL format)"
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Run only retrieval evaluation"
    )
    parser.add_argument(
        "--e2e-only",
        action="store_true",
        help="Run only end-to-end evaluation"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Number of results to retrieve (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Optional path to save results as JSON"
    )
    
    args = parser.parse_args()
    
    # Resolve eval file path (relative to app dir)
    eval_file = APP_DIR / args.eval_file
    
    print("⚡️ Cards-Memex Evaluation Runner")
    print("=" * 60)
    
    # Check if eval file exists
    if not eval_file.exists():
        print(f"❌ Evaluation file not found: {eval_file}")
        print("   Please create the file with test cases.")
        sys.exit(1)
    
    # Load environment variables from app's .env
    load_dotenv(dotenv_path=ENV_FILE)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not found in environment")
        sys.exit(1)
    
    # Load evaluation data
    print(f"📂 Loading evaluation data from: {eval_file}")
    eval_data = load_eval_data(str(eval_file))
    print(f"   Loaded {len(eval_data)} test cases")
    
    # Initialize components
    print("\n🔧 Initializing components...")
    
    client = GeminiClient(api_key=GEMINI_API_KEY)
    store = ChromaVectorStore(
        persist_directory=str(KNOWLEDGE_BASE_DIR),
        collection_name="slack_knowledge",
        api_key=GEMINI_API_KEY
    )
    
    doc_count = store.collection.count()
    print(f"   ChromaDB connected: {doc_count} documents")
    
    # Load role definition
    role_def = load_role_definition(role_file=str(ROLE_FILE))
    print(f"   Role definition loaded: {role_def.role}")
    
    # Store results
    all_results = {}
    
    # Run retrieval evaluation
    if not args.e2e_only:
        retrieval_results = evaluate_retrieval(
            vector_store=store,
            eval_data=eval_data,
            k=args.k,
            verbose=True
        )
        print_retrieval_results(retrieval_results)
        all_results["retrieval"] = retrieval_results
    
    # Run end-to-end evaluation
    if not args.retrieval_only:
        generator = AnswerGenerator(client)
        retrieval_pipe = RetrievalPipeline(store, generator)
        
        e2e_results = evaluate_end_to_end(
            retrieval_pipeline=retrieval_pipe,
            eval_data=eval_data,
            role_def=role_def,
            judge_client=client,
            verbose=True
        )
        print_e2e_results(e2e_results)
        all_results["end_to_end"] = {
            "accuracy": e2e_results["accuracy"],
            "correct_count": e2e_results["correct_count"],
            "total_count": e2e_results["total_count"]
        }
    
    # Save results if output path provided
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = APP_DIR / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"\n📁 Results saved to: {output_path}")
    
    print("\n✅ Evaluation complete!")


if __name__ == "__main__":
    main()
