"""
test_rag.py - Standalone test script for the OpenAI RAG classifier

Tests:
  1. Knowledge base loading and chunking
  2. Embedding computation
  3. Chunk retrieval for sample queries
  4. Full RAG classification with sample transcripts

Usage:
  export OPENAI_API_KEY="sk-..."
  python test_rag.py
"""

import sys
import json
from pathlib import Path

# Ensure the project directory is importable
sys.path.insert(0, str(Path(__file__).parent))

from config import DEBUG, OPENAI_API_KEY


def test_knowledge_base_loading():
    """Test 1: Load and chunk the knowledge base."""
    print("\n" + "=" * 60)
    print("TEST 1: Knowledge Base Loading & Chunking")
    print("=" * 60)

    from rag_classifier import load_knowledge_base, chunk_knowledge_base

    data = load_knowledge_base()
    print(f"  ✓ Loaded knowledge base with {len(data.get('tracks', []))} tracks")

    chunks = chunk_knowledge_base(data)
    print(f"  ✓ Created {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        text_preview = chunk["text"][:80].replace("\n", " ")
        print(f"    Chunk {i}: type={meta.get('type', '?')}, "
              f"track={meta.get('track_name', 'N/A')}, "
              f"preview=\"{text_preview}...\"")

    return chunks


def test_embedding(chunks):
    """Test 2: Compute embeddings."""
    print("\n" + "=" * 60)
    print("TEST 2: Embedding Computation")
    print("=" * 60)

    from rag_classifier import embed_texts

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)
    print(f"  ✓ Computed embeddings: shape={embeddings.shape}")
    print(f"    Embedding dimension: {embeddings.shape[1]}")
    print(f"    Sample norms: {[f'{float(e):.4f}' for e in (embeddings ** 2).sum(axis=1) ** 0.5]}")

    return embeddings


def test_retrieval():
    """Test 3: Retrieve relevant chunks for sample queries."""
    print("\n" + "=" * 60)
    print("TEST 3: Chunk Retrieval")
    print("=" * 60)

    from rag_classifier import initialize_knowledge_base, retrieve_relevant_chunks

    initialize_knowledge_base()

    test_queries = [
        "Super Pro to the staging lanes",
        "Top Fuel standby please",
        "Junior Dragster report to the grid",
        "Attention all Funny Car drivers meeting in five minutes",
        "Pro Stock Motorcycle be on deck",
        "Street Legal Friday night drags",
        "Nostalgia drag races hot rod class",
        "Gold Cup bracket racing super pro and pro",
    ]

    for query in test_queries:
        print(f"\n  Query: \"{query}\"")
        results = retrieve_relevant_chunks(query, top_k=2)
        for r in results:
            track = r["metadata"].get("track_name", r["metadata"].get("type", "?"))
            print(f"    → {track} (score={r['score']:.3f})")


def test_classification():
    """Test 4: Full RAG classification with sample transcripts."""
    print("\n" + "=" * 60)
    print("TEST 4: Full RAG Classification")
    print("=" * 60)

    from rag_classifier import initialize_knowledge_base, classify_with_rag
    import datetime

    initialize_knowledge_base()

    test_transcripts = [
        "Super Pro, please make your way down to the staging lanes. Super Pro to the lanes.",
        "Attention Top Fuel drivers, you are on standby. Top Fuel, be ready.",
        "Junior Dragster, time to line up. Junior Dragster to the grid.",
        "Can I have all Pro Stock and Funny Car drivers report to the staging area please.",
        "Street Legal, you're up next. Street Legal, head on down to the lanes.",
        "Attention all drivers, there will be a mandatory drivers meeting in the tower in ten minutes.",
    ]

    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    for transcript in test_transcripts:
        print(f"\n  Transcript: \"{transcript}\"")
        msgs = classify_with_rag(transcript, timestamp)

        if msgs:
            for m in msgs:
                print(f"    → class_id={m['class_id']}, "
                      f"class_name=\"{m['class_name']}\", "
                      f"intent={m['intent']}")
                print(f"      message: \"{m['message_text']}\"")
        else:
            print("    → (no messages generated)")


def main():
    print("=" * 60)
    print("  OpenAI RAG Classifier — Test Suite")
    print("=" * 60)

    if not OPENAI_API_KEY:
        print("\n  ✗ ERROR: OPENAI_API_KEY environment variable is not set.")
        print("  Run: export OPENAI_API_KEY=\"sk-...\"")
        sys.exit(1)

    print(f"  API Key: {OPENAI_API_KEY[:8]}...{OPENAI_API_KEY[-4:]}")

    # Test 1: Loading & Chunking (no API calls)
    chunks = test_knowledge_base_loading()

    # Test 2: Embedding (API call)
    try:
        test_embedding(chunks)
    except Exception as e:
        print(f"  ✗ Embedding failed: {e}")
        sys.exit(1)

    # Test 3: Retrieval (API call for query embedding)
    try:
        test_retrieval()
    except Exception as e:
        print(f"  ✗ Retrieval failed: {e}")
        sys.exit(1)

    # Test 4: Full Classification (API calls)
    try:
        test_classification()
    except Exception as e:
        print(f"  ✗ Classification failed: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  All tests completed successfully! ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
