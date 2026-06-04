"""
rag_classifier.py - OpenAI RAG-based classifier for drag-strip announcements

Uses the TrackTech announcements structure as a knowledge base to provide
contextual class/event information to OpenAI GPT for more accurate
transcription → class ID + intent mapping.

Flow:
  1. Load knowledge base JSON → chunk per track + shared class sets
  2. Embed chunks via OpenAI text-embedding-3-small (cached in memory)
  3. On each transcript: retrieve top-k chunks via cosine similarity
  4. Send transcript + retrieved context + class list to GPT
  5. Parse structured JSON response into message dicts
"""

import json
import threading
import numpy as np
from pathlib import Path
from openai import OpenAI

from config import (
    OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EMBEDDING_MODEL,
    RAG_KNOWLEDGE_BASE_PATH, RAG_TOP_K, DEBUG,
    get_classmap
)

# ===========================
# OpenAI client (lazy init)
# ===========================
_openai_client = None
_client_lock = threading.Lock()


def _get_client():
    """Lazily initialize and return the OpenAI client."""
    global _openai_client
    if _openai_client is None:
        with _client_lock:
            if _openai_client is None:
                _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


# ===========================
# Knowledge base loading & chunking
# ===========================
_chunks = []           # list of {"text": str, "metadata": dict}
_chunk_embeddings = None  # numpy array of shape (n_chunks, embed_dim)
_kb_lock = threading.Lock()
_kb_initialized = False


def load_knowledge_base(path: Path = None) -> dict:
    """Load the TrackTech announcements structure JSON from disk."""
    if path is None:
        path = RAG_KNOWLEDGE_BASE_PATH

    if not path.exists():
        raise FileNotFoundError(f"RAG knowledge base not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if DEBUG:
        n_tracks = len(data.get("tracks", []))
        n_shared = len(data.get("shared_class_sets", {}))
        print(f"[rag] loaded knowledge base: {n_tracks} tracks, {n_shared} shared class sets")

    return data


def chunk_knowledge_base(data: dict) -> list:
    """
    Split the knowledge base into semantically meaningful chunks.

    Strategy:
      - One chunk for the shared class sets (global reference)
      - One chunk per track (containing all its event families + classes)
      - Each chunk is a self-contained text block that GPT can use as context

    Returns list of {"text": str, "metadata": dict}
    """
    chunks = []

    # --- Shared class sets chunk ---
    shared = data.get("shared_class_sets", {})
    if shared:
        lines = ["=== SHARED CLASS SETS (used across multiple tracks) ===\n"]
        for set_name, classes in shared.items():
            lines.append(f"  {set_name}: {', '.join(classes)}")
        chunk_text = "\n".join(lines)
        chunks.append({
            "text": chunk_text,
            "metadata": {"type": "shared_class_sets"}
        })

    # --- Per-track chunks ---
    for track in data.get("tracks", []):
        track_name = track.get("track_name", "Unknown Track")
        facility = track.get("facility_name", "")
        state = track.get("state", "")
        sanctioning = track.get("sanctioning_bodies", [])

        lines = [
            f"=== TRACK: {track_name} ===",
            f"Facility: {facility}",
            f"State: {state}",
            f"Sanctioning Bodies: {', '.join(sanctioning)}",
            ""
        ]

        for family in track.get("event_families", []):
            family_name = family.get("family_name", "Unknown Family")
            examples = family.get("event_examples", [])
            class_refs = family.get("class_set_refs", [])
            custom = family.get("custom_classes", [])

            lines.append(f"  Event Family: {family_name}")
            if examples:
                lines.append(f"    Event Examples: {', '.join(examples)}")
            if class_refs:
                # Resolve shared class set references
                resolved_classes = []
                for ref in class_refs:
                    resolved_classes.extend(shared.get(ref, []))
                lines.append(f"    Classes (from {', '.join(class_refs)}): {', '.join(resolved_classes)}")
            if custom:
                lines.append(f"    Custom Classes: {', '.join(custom)}")
            lines.append("")

        chunk_text = "\n".join(lines)
        chunks.append({
            "text": chunk_text,
            "metadata": {
                "type": "track",
                "track_name": track_name,
                "facility_name": facility,
                "state": state
            }
        })

    if DEBUG:
        print(f"[rag] created {len(chunks)} chunks from knowledge base")

    return chunks


# ===========================
# Embedding
# ===========================

def embed_texts(texts: list) -> np.ndarray:
    """
    Compute embeddings for a list of text strings using OpenAI embeddings API.
    Returns numpy array of shape (len(texts), embedding_dim).
    """
    client = _get_client()

    # OpenAI embeddings API accepts batches
    response = client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=texts
    )

    embeddings = [item.embedding for item in response.data]
    return np.array(embeddings, dtype=np.float32)


def initialize_knowledge_base():
    """
    Load knowledge base, chunk it, and compute embeddings.
    Call once at startup. Thread-safe.
    """
    global _chunks, _chunk_embeddings, _kb_initialized

    with _kb_lock:
        if _kb_initialized:
            return

        try:
            data = load_knowledge_base()
            _chunks = chunk_knowledge_base(data)

            if not _chunks:
                print("[rag] WARNING: no chunks generated from knowledge base")
                return

            texts = [c["text"] for c in _chunks]
            _chunk_embeddings = embed_texts(texts)
            _kb_initialized = True

            if DEBUG:
                print(f"[rag] embeddings computed: shape={_chunk_embeddings.shape}")

        except Exception as e:
            print(f"[rag] ERROR initializing knowledge base: {e}")
            _kb_initialized = False


# ===========================
# Retrieval
# ===========================

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between vector a and matrix b."""
    # a: (dim,), b: (n, dim) → result: (n,)
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return np.dot(b_norm, a_norm)


def retrieve_relevant_chunks(query: str, top_k: int = None) -> list:
    """
    Retrieve the top-k most relevant knowledge base chunks for a query.

    Returns list of {"text": str, "metadata": dict, "score": float}
    """
    if top_k is None:
        top_k = RAG_TOP_K

    if not _kb_initialized or _chunk_embeddings is None:
        if DEBUG:
            print("[rag] knowledge base not initialized, attempting init...")
        initialize_knowledge_base()

    if not _kb_initialized or _chunk_embeddings is None:
        return []

    # Embed the query
    query_embedding = embed_texts([query])[0]

    # Compute cosine similarities
    similarities = _cosine_similarity(query_embedding, _chunk_embeddings)

    # Get top-k indices
    top_indices = np.argsort(similarities)[::-1][:top_k]

    results = []
    for idx in top_indices:
        results.append({
            "text": _chunks[idx]["text"],
            "metadata": _chunks[idx]["metadata"],
            "score": float(similarities[idx])
        })

    if DEBUG:
        for r in results:
            meta_str = r["metadata"].get("track_name", r["metadata"].get("type", "?"))
            print(f"[rag] retrieved chunk: {meta_str} (score={r['score']:.3f})")

    return results


# ===========================
# RAG Classification
# ===========================

def _build_canonical_class_list_str() -> str:
    """Build a formatted string of all canonical class names."""
    classmap = get_classmap()
    return ", ".join(sorted(classmap.keys()))


def classify_with_rag(transcript: str, timestamp: str) -> list:
    """
    Main RAG classification entry point.

    1. Retrieve relevant knowledge base chunks
    2. Build system prompt with context
    3. Call OpenAI GPT for class + intent classification
    4. Parse and validate response
    5. Return list of message dicts matching pipeline schema

    Falls back to empty list on error (caller handles fallback).
    """
    from classifier import should_send  # avoid circular import

    classmap = get_classmap()
    if not classmap:
        return []

    # Step 1: Retrieve relevant context
    retrieved = retrieve_relevant_chunks(transcript)
    context_text = "\n\n".join([r["text"] for r in retrieved]) if retrieved else "No specific track context available."

    # Step 2: Build the prompt
    canonical_list_str = _build_canonical_class_list_str()

    system_prompt = f"""You are an expert drag racing track announcer AI assistant.
You receive a raw audio transcript from a live drag strip announcer and your job is to:
1. Identify which racing class(es) are being mentioned
2. Determine the intent of the announcement
3. Frame a clean, professional announcement message

You have access to a knowledge base of track and event information to help you understand context:

--- KNOWLEDGE BASE CONTEXT ---
{context_text}
--- END CONTEXT ---

VALID CLASS NAMES (you MUST only use class names from this list):
[{canonical_list_str}]

VALID INTENTS:
- CLASS_TO_LANES: The announcer is directing a class to go to staging lanes, grid, track, line up, etc.
- CLASS_STANDBY: The announcer is telling a class to hold, wait, get ready, standby, be on deck, etc.
- GENERAL_ANNOUNCEMENT: Other important notices, updates, or information about a class.

RULES:
1. ONLY use class names that EXACTLY match one from the valid class list above.
2. Use the knowledge base context to disambiguate class names. For example, if the context shows a specific track only has certain classes, prefer those classes.
3. If multiple classes are mentioned, return ALL of them as separate objects.
4. The "message_text" should be a clean, professional version of what the announcer said, using the exact class name and preserving the announcer's intent/keywords.
5. If no valid class or intent can be identified, return an empty array [].
6. Audio transcription may contain speech-to-text errors. Use the knowledge base and class list to correct likely misheard class names (e.g., "soup or pro" → "Super Pro", "top few" → "Top Fuel").

Output ONLY a valid JSON array. Each object must have:
- "class_name": string (must exactly match a valid class name)
- "intent": string (one of the valid intents)
- "message_text": string (clean announcement text)

If nothing relevant is found, return: []"""

    user_prompt = f"Transcript: \"{transcript}\"\n\nIdentify all class mentions and intents. Output JSON array:"

    # Step 3: Call OpenAI
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # Low temperature for consistent, deterministic output
            max_tokens=500,
            response_format={"type": "json_object"}  # Force JSON mode
        )

        content = response.choices[0].message.content.strip()

        if DEBUG:
            print(f"[rag] OpenAI response: {content}")

        # Step 4: Parse response
        parsed = json.loads(content)

        # Handle both {"results": [...]} and direct [...] formats
        if isinstance(parsed, dict):
            results = parsed.get("results", parsed.get("announcements", parsed.get("classes", [])))
            if not isinstance(results, list):
                results = []
        elif isinstance(parsed, list):
            results = parsed
        else:
            results = []

        # Step 5: Validate and build message dicts
        msgs = []
        for res in results:
            cls_name = res.get("class_name", "")
            intent = res.get("intent", "")
            message_text = res.get("message_text", "")

            # Validate class exists in classmap
            if cls_name not in classmap:
                if DEBUG:
                    print(f"[rag] skipping unknown class: '{cls_name}'")
                continue

            # Validate intent
            valid_intents = {"CLASS_TO_LANES", "CLASS_STANDBY", "GENERAL_ANNOUNCEMENT"}
            if intent not in valid_intents:
                if DEBUG:
                    print(f"[rag] skipping unknown intent: '{intent}'")
                continue

            # Check debounce
            if not should_send(cls_name, intent):
                if DEBUG:
                    print(f"[rag] debounced: {cls_name} / {intent}")
                continue

            msgs.append({
                "class_id": classmap[cls_name]["id"],
                "class_name": cls_name,
                "intent": intent,
                "transcription": transcript,
                "message_text": message_text,
                "timestamp": timestamp
            })

        if DEBUG:
            print(f"[rag] classified {len(msgs)} messages from transcript")

        return msgs

    except Exception as e:
        if DEBUG:
            print(f"[rag] classification error: {e}")
        return []  # Caller will fall back to existing pipeline
