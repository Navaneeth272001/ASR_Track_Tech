"""
rag_classifier.py - Bedrock (Claude 3 Haiku) based classifier for drag-strip announcements

Uses the TrackTech announcements structure as a knowledge base to provide
contextual class/event information to Claude for more accurate
transcription → class ID + intent mapping.
"""

import json
import threading
from pathlib import Path
import boto3

from config import (
    RAG_KNOWLEDGE_BASE_PATH, DEBUG, get_classmap, AWS_REGION, BEDROCK_MODEL_ID
)

# ===========================
# Bedrock client (lazy init)
# ===========================
_bedrock_client = None
_client_lock = threading.Lock()

def _get_client():
    """Lazily initialize and return the Bedrock client."""
    global _bedrock_client
    if _bedrock_client is None:
        with _client_lock:
            if _bedrock_client is None:
                _bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)
    return _bedrock_client


# ===========================
# Knowledge base loading
# ===========================
_kb_text = ""
_kb_lock = threading.Lock()
_kb_initialized = False

def load_knowledge_base(path: Path = None) -> str:
    """Load the TrackTech announcements structure JSON from disk as a formatted string."""
    if path is None:
        path = RAG_KNOWLEDGE_BASE_PATH

    if not path.exists():
        raise FileNotFoundError(f"RAG knowledge base not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    # We will just pass the entire JSON as string, Claude can read it easily
    return json.dumps(data, indent=2)

def initialize_knowledge_base():
    """
    Load knowledge base into memory.
    Call once at startup. Thread-safe.
    """
    global _kb_text, _kb_initialized

    with _kb_lock:
        if _kb_initialized:
            return

        try:
            _kb_text = load_knowledge_base()
            _kb_initialized = True

            if DEBUG:
                print(f"[rag] Bedrock KB initialized, length: {len(_kb_text)}")

        except Exception as e:
            print(f"[rag] ERROR initializing knowledge base: {e}")
            _kb_initialized = False

# ===========================
# RAG Classification
# ===========================

def _build_canonical_class_list_str() -> str:
    """Build a formatted string of all canonical class names and their aliases."""
    classmap = get_classmap()
    lines = []
    for cls, data in sorted(classmap.items()):
        aliases = data.get("aliases", [])
        if aliases:
            lines.append(f"- {cls} (aliases/phonetics: {', '.join(aliases)})")
        else:
            lines.append(f"- {cls}")
    return "\n".join(lines)


def classify_with_rag(transcript: str, timestamp: str) -> list:
    """
    Main RAG classification entry point.

    1. Build system prompt with full KB context
    2. Call Bedrock Claude 3 Haiku for class + intent classification
    3. Parse and validate response
    4. Return list of message dicts matching pipeline schema

    Falls back to empty list on error (caller handles fallback).
    """
    from classifier import should_send  # avoid circular import

    classmap = get_classmap()
    if not classmap:
        return []

    if not _kb_initialized:
        initialize_knowledge_base()
        
    context_text = _kb_text if _kb_initialized else "No specific track context available."

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

VALID CLASS NAMES (and their common aliases/mispronunciations):
{canonical_list_str}

VALID INTENTS:
- CLASS_TO_LANES: The announcer is directing a class to go to staging lanes, grid, track, line up, pull up, need you down here, etc.
- CLASS_STANDBY: The announcer is telling a class to hold, wait, get ready, standby, be on deck, in the hole, listen for the call, etc.
- GENERAL_ANNOUNCEMENT: Other important notices, updates, meetings, or information about a class.

RULES:
1. ONLY return the primary canonical class name (e.g., "Super Pro", not an alias).
2. The audio is from a race announcer, so the transcription may be messy, incomplete, or contain speech-to-text errors (e.g. "supertre" -> "Super Street", "stock" -> "Stock Eliminator", "comp" -> "Comp Eliminator"). Perform fuzzy matching, phonetic matching, and contextual deduction to match the transcription to the most accurate class and intent.
3. Use the knowledge base context to disambiguate class names. If context shows a track only has certain classes, prefer those.
4. CRITICAL: If MULTIPLE classes are mentioned in a single announcement (e.g., "super street and stock"), you MUST return ALL of them as separate objects in the JSON array. Do not miss any. Each class gets its own object.
5. Do not hallucinate intents. If the announcer says "standby", the intent is CLASS_STANDBY, NOT CLASS_TO_LANES.
6. The "message_text" should be a clean, professional version of what the announcer said, using the exact class name and preserving the announcer's intent/keywords.
7. If the intent or class is implicit but clear from context, match it. For example, "we need the bikes down here" -> Class: "Motorcycle", Intent: "CLASS_TO_LANES".
8. If no valid class or intent can be identified, return an empty array [].

Output ONLY a valid JSON array. Each object must have:
- "class_name": string (must exactly match a valid primary canonical class name)
- "intent": string (one of the valid intents)
- "message_text": string (clean announcement text)

If nothing relevant is found, return: []"""

    user_prompt = f"Transcript: \"{transcript}\"\n\nIdentify all class mentions and intents. Output JSON array:"

    try:
        client = _get_client()
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1
            }),
            contentType="application/json",
            accept="application/json"
        )
        body = json.loads(response.get('body').read())
        content = body.get('content', [])[0].get('text', '[]')
        
        # Clean up any potential non-JSON prefix/suffix from Claude
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].strip()

        if DEBUG:
            print(f"[rag] Bedrock response: {content}")

        parsed = json.loads(content)

        if isinstance(parsed, dict):
            results = parsed.get("results", parsed.get("announcements", parsed.get("classes", [])))
            if not isinstance(results, list):
                results = []
        elif isinstance(parsed, list):
            results = parsed
        else:
            results = []

        msgs = []
        for res in results:
            cls_name = res.get("class_name", "")
            intent = res.get("intent", "")
            message_text = res.get("message_text", "")

            if cls_name not in classmap:
                if DEBUG:
                    print(f"[rag] skipping unknown class: '{cls_name}'")
                continue

            valid_intents = {"CLASS_TO_LANES", "CLASS_STANDBY", "GENERAL_ANNOUNCEMENT"}
            if intent not in valid_intents:
                if DEBUG:
                    print(f"[rag] skipping unknown intent: '{intent}'")
                continue

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
        return []
