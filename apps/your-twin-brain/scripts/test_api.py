#!/usr/bin/env python3
"""
Test script to verify API keys and functionality work correctly.
"""

import os
import sys
from pathlib import Path

# Script is in apps/your-twin-brain/scripts/, add src to path
APP_DIR = Path(__file__).parent.parent
PROJECT_ROOT = APP_DIR.parent.parent

sys.path.insert(0, str(APP_DIR / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "libs" / "memex-core"))

from dotenv import load_dotenv
import google.generativeai as genai
import chromadb
from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction

# Import paths from twin_brain package
from twin_brain.paths import ENV_FILE, KNOWLEDGE_BASE_DIR, ROLE_FILE, ensure_data_dir

# Load environment variables from app's .env
ensure_data_dir()
load_dotenv(dotenv_path=ENV_FILE)


def test_gemini_api_key():
    """Test if Gemini API key works for generative AI."""
    print("🔍 Testing Gemini API Key (Generative AI)...")
    try:
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY not found in .env file")
            return False
        
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content("Say 'Hello, API test successful!'")
        
        if response and response.text:
            print(f"✅ Gemini API Key works! Response: {response.text.strip()}")
            return True
        else:
            print("❌ Gemini API returned empty response")
            return False
    except Exception as e:
        print(f"❌ Gemini API Key test failed: {e}")
        return False


def test_embeddings():
    """Test if embeddings API works."""
    print("\n🔍 Testing Embeddings API...")
    try:
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY not found in .env file")
            return False
        
        embedding_function = GoogleGenerativeAiEmbeddingFunction(
            api_key=GEMINI_API_KEY,
            task_type="RETRIEVAL_DOCUMENT"
        )
        
        # Test embedding generation
        test_text = "This is a test message for embedding generation"
        embedding = embedding_function([test_text])
        
        if embedding and len(embedding) > 0 and len(embedding[0]) > 0:
            print(f"✅ Embeddings API works! Generated embedding with {len(embedding[0])} dimensions")
            return True
        else:
            print("❌ Embeddings API returned empty or invalid embedding")
            return False
    except Exception as e:
        print(f"❌ Embeddings API test failed: {e}")
        return False


def test_chromadb():
    """Test if ChromaDB connection works."""
    print("\n🔍 Testing ChromaDB connection...")
    try:
        chroma_client = chromadb.PersistentClient(path=str(KNOWLEDGE_BASE_DIR))
        collections = chroma_client.list_collections()
        print(f"✅ ChromaDB connection works! Found {len(collections)} collection(s)")
        for col in collections:
            count = col.count()
            print(f"   - Collection '{col.name}': {count} items")
        return True
    except Exception as e:
        print(f"❌ ChromaDB test failed: {e}")
        return False


def test_chromadb_with_embeddings():
    """Test ChromaDB with embedding function."""
    print("\n🔍 Testing ChromaDB with Embeddings...")
    try:
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY not found in .env file")
            return False
        
        chroma_client = chromadb.PersistentClient(path=str(KNOWLEDGE_BASE_DIR))
        embedding_function = GoogleGenerativeAiEmbeddingFunction(
            api_key=GEMINI_API_KEY,
            task_type="RETRIEVAL_DOCUMENT"
        )
        
        # Try to get or create the collection
        collection = chroma_client.get_or_create_collection(
            name="slack_knowledge",
            embedding_function=embedding_function
        )
        
        # Test adding a document
        test_id = "test_doc_123"
        test_text = "This is a test document for ChromaDB"
        
        collection.add(
            documents=[test_text],
            ids=[test_id]
        )
        
        # Test querying
        results = collection.query(
            query_texts=["test document"],
            n_results=1
        )
        
        if results and len(results['ids'][0]) > 0:
            print("✅ ChromaDB with embeddings works! Successfully stored and retrieved document")
            
            # Clean up test document
            collection.delete(ids=[test_id])
            print("   (Cleaned up test document)")
            return True
        else:
            print("❌ ChromaDB query returned no results")
            return False
    except Exception as e:
        print(f"❌ ChromaDB with embeddings test failed: {e}")
        return False


def test_classification():
    """Test thread classification function using memex-core pipeline architecture."""
    print("\n🔍 Testing Thread Classification...")
    try:
        from memex_core import GeminiClient, ThreadClassifier, load_role_definition
        
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            print("⚠️  GEMINI_API_KEY not found, skipping classification test")
            return None
        
        # Load role definition from the new path
        if ROLE_FILE.exists():
            role_definition = load_role_definition(role_file=str(ROLE_FILE))
        else:
            role_definition = load_role_definition()
        
        # Initialize Gemini client and ThreadClassifier
        gemini_client = GeminiClient(api_key=GEMINI_API_KEY)
        classifier = ThreadClassifier(gemini_client)
        
        # Test with a sample thread text
        test_thread_text = "[U123]: We need to discuss the new card feature implementation\n[U456]: This relates to our Q4 product roadmap"
        
        result = classifier.classify_thread(test_thread_text, role_definition)
        
        if result:
            print("✅ Classification works!")
            print(f"   Theme: {result.theme}")
            print(f"   Product: {result.product}")
            print(f"   Project: {result.project}")
            print(f"   Topic: {result.topic}")
            print(f"   Thread Name: {result.thread_name}")
            return True
        else:
            print("❌ Classification returned empty result")
            return False
    except Exception as e:
        print(f"❌ Classification test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("API & Functionality Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test 1: Gemini API Key
    results.append(("Gemini API Key", test_gemini_api_key()))
    
    # Test 2: Embeddings API
    results.append(("Embeddings API", test_embeddings()))
    
    # Test 3: ChromaDB Connection
    results.append(("ChromaDB Connection", test_chromadb()))
    
    # Test 4: ChromaDB with Embeddings
    results.append(("ChromaDB + Embeddings", test_chromadb_with_embeddings()))
    
    # Test 5: Classification (optional)
    classification_result = test_classification()
    if classification_result is not None:
        results.append(("Thread Classification", classification_result))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Your API key and setup are working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
