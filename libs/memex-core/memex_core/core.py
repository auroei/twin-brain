"""
Core factory functions for memex-core.
Provides a simplified entry point for creating standard system configurations.
"""

from typing import Dict, Any, Optional

from .ai import GeminiClient, ThreadClassifier, AnswerGenerator
from .storage import ChromaVectorStore
from .memory import MemoryCurator
from .pipelines import IngestionPipeline, RetrievalPipeline


def create_memex_system(
    api_key: str, 
    persist_dir: str, 
    collection_name: str = "slack_knowledge",
    memex_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Factory function to create a fully configured Memex system.
    
    Initializes:
    - Gemini Client
    - Vector Store (ChromaDB)
    - Classifier & Generator
    - Ingestion & Retrieval Pipelines
    
    Args:
        api_key: Google Gemini API key
        persist_dir: Directory to store the vector database
        collection_name: Name of the ChromaDB collection (default: "slack_knowledge")
        memex_config: Optional configuration dictionary containing 'retrieval', 'behavior', etc.
        
    Returns:
        Dictionary containing all initialized components:
        {
            "client": GeminiClient,
            "store": ChromaVectorStore,
            "curator": MemoryCurator,
            "classifier": ThreadClassifier,
            "generator": AnswerGenerator,
            "ingest_pipe": IngestionPipeline,
            "retrieval_pipe": RetrievalPipeline
        }
    """
    if memex_config is None:
        memex_config = {}

    # 1. Initialize AI Client
    client = GeminiClient(api_key=api_key)

    # 2. Initialize Storage (with Contextual Embeddings support)
    store = ChromaVectorStore(
        persist_directory=persist_dir,
        collection_name=collection_name,
        api_key=api_key,
        context_client=client
    )

    # 3. Initialize Helpers
    # Extract specific configs if they exist, otherwise defaults will be used
    retrieval_config = memex_config.get("retrieval", {})
    priority_config = memex_config.get("priority", {})
    
    curator = MemoryCurator(config_dict=retrieval_config)
    classifier = ThreadClassifier(client)
    generator = AnswerGenerator(client)

    # 4. Initialize Pipelines
    # Ingestion: Curate -> Store -> Classify
    ingest_pipe = IngestionPipeline(
        curator=curator, 
        classifier=classifier, 
        vector_store=store,
        supersession_client=client  # Enable detection of superseded threads
    )

    # Retrieval: Query -> Rerank -> Generate
    # We enable the reranker by default if the client is available
    retrieval_pipe = RetrievalPipeline(
        vector_store=store,
        generator=generator,
        reranker_client=client,
        priority_config=priority_config
    )

    return {
        "client": client,
        "store": store,
        "curator": curator,
        "classifier": classifier,
        "generator": generator,
        "ingest_pipe": ingest_pipe,
        "retrieval_pipe": retrieval_pipe
    }

