"""
Retrieval metrics for evaluating RAG systems.
Provides Precision, Recall, MRR, and F1 calculations.
"""

from typing import List, Dict, Any, Set


def calculate_mrr(retrieved_ids: List[str], correct_ids: Set[str]) -> float:
    """
    Calculate Mean Reciprocal Rank.
    
    MRR measures how well the system ranks relevant documents.
    Returns 1/rank of the first relevant document found.
    
    Args:
        retrieved_ids: Ordered list of retrieved document IDs
        correct_ids: Set of correct/relevant document IDs
        
    Returns:
        Reciprocal rank (1/position) of first relevant doc, or 0 if none found
    """
    for i, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in correct_ids:
            return 1 / i
    return 0.0


def evaluate_retrieval(
    vector_store,
    eval_data: List[Dict[str, Any]],
    k: int = 10,
    id_field: str = "thread_ts",
    verbose: bool = True
) -> Dict[str, float]:
    """
    Evaluate retrieval performance using precision, recall, MRR, and F1.
    
    Args:
        vector_store: ChromaVectorStore instance (or any store with .collection.query())
        eval_data: List of evaluation items with:
            - question: The test question
            - correct_thread_ids: List of expected thread IDs
        k: Number of results to retrieve per query
        id_field: Metadata field containing the document ID (default: "thread_ts")
        verbose: Whether to print per-question results
        
    Returns:
        Dictionary containing:
        - precision: Proportion of retrieved threads that are relevant
        - recall: Proportion of relevant threads that were retrieved
        - mrr: Mean Reciprocal Rank
        - f1: Harmonic mean of precision and recall
        - total_evaluated: Number of questions evaluated
    """
    precisions = []
    recalls = []
    mrrs = []
    
    if verbose:
        print(f"\n📊 Evaluating Retrieval (k={k})...")
        print("-" * 60)
    
    for i, item in enumerate(eval_data, 1):
        question = item.get("question", "")
        correct_ids = set(item.get("correct_thread_ids", []))
        
        if not correct_ids:
            if verbose:
                print(f"  ⚠️  Skipping item {i}: No correct_thread_ids provided")
            continue
        
        # Query the vector store
        results = vector_store.collection.query(
            query_texts=[question],
            n_results=k
        )
        
        # Extract IDs from metadata
        retrieved_ids = []
        if results.get("metadatas") and results["metadatas"][0]:
            for meta in results["metadatas"][0]:
                doc_id = meta.get(id_field, "")
                if doc_id:
                    retrieved_ids.append(doc_id)
        
        # Calculate metrics
        true_positives = len(set(retrieved_ids) & correct_ids)
        
        precision = true_positives / len(retrieved_ids) if retrieved_ids else 0.0
        recall = true_positives / len(correct_ids) if correct_ids else 0.0
        mrr = calculate_mrr(retrieved_ids, correct_ids)
        
        precisions.append(precision)
        recalls.append(recall)
        mrrs.append(mrr)
        
        if verbose:
            print(f"  Q{i}: P={precision:.2f} R={recall:.2f} MRR={mrr:.2f} | {question[:50]}...")
    
    if not precisions:
        if verbose:
            print("  ❌ No valid evaluation items found")
        return {
            "precision": 0.0,
            "recall": 0.0,
            "mrr": 0.0,
            "f1": 0.0,
            "total_evaluated": 0
        }
    
    # Calculate averages
    avg_precision = sum(precisions) / len(precisions)
    avg_recall = sum(recalls) / len(recalls)
    avg_mrr = sum(mrrs) / len(mrrs)
    
    # Calculate F1 score
    if (avg_precision + avg_recall) > 0:
        f1 = 2 * (avg_precision * avg_recall) / (avg_precision + avg_recall)
    else:
        f1 = 0.0
    
    return {
        "precision": avg_precision,
        "recall": avg_recall,
        "mrr": avg_mrr,
        "f1": f1,
        "total_evaluated": len(precisions)
    }

