import re
import time
import threading
import json
import boto3
from rapidfuzz import fuzz, process
from config import (
    INTENT_PATTERNS, DEBOUNCE_SECONDS, get_classmap, DEBUG,
    USE_LLM_FRAMING, BEDROCK_MODEL_ID, AWS_REGION
)

# Thread-safe alias mapping
_alias_to_canonical = {}
_alias_choices = []
_alias_lock = threading.RLock()


def rebuild_alias_map():
    """
    Rebuild _alias_to_canonical and _alias_choices from current CLASS_MAP.
    Call this whenever CLASS_MAP is updated.
    """
    global _alias_to_canonical, _alias_choices
    
    classmap = get_classmap()
    
    with _alias_lock:
        _alias_to_canonical.clear()
        
        # Map canonical name to itself (lowercase)
        for canon in classmap.keys():
            _alias_to_canonical[canon.lower()] = canon
        
        # Map each alias to canonical name
        for canon, data in classmap.items():
            aliases = data.get("aliases", [])
            for alias in aliases:
                _alias_to_canonical[alias.lower()] = canon
        
        _alias_choices = list(_alias_to_canonical.keys())
    
    if DEBUG:
        print(f"[classifier] rebuilt alias map: {len(_alias_to_canonical)} entries")


def normalize_text(s):
    """Normalize text for matching."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_classes(transcript, threshold=75):
    """
    Find matching class names from transcript.
    Uses fuzzy matching on aliases.
    """
    t = normalize_text(transcript)
    found = set()
    
    with _alias_lock:
        # First pass: exact substring match on aliases
        for alias, canon in _alias_to_canonical.items():
            if alias in t:
                found.add(canon)
        
        # Second pass: fuzzy matching if no exact matches
        if not found:
            matches = process.extract(
                t, 
                _alias_choices, 
                scorer=fuzz.partial_ratio, 
                limit=3
            )
            for alias, score, _ in matches:
                if score >= threshold:
                    found.add(_alias_to_canonical[alias])
    
    return list(found)


def find_intents_with_context(transcript):
    """Find matching intent types and their matched keywords from transcript."""
    t = normalize_text(transcript)
    intents = []
    
    for intent, patterns in INTENT_PATTERNS.items():
        matched = False
        # Exact match
        for p in patterns:
            if p.lower() in t:
                intents.append((intent, p.lower()))
                matched = True
                break
                
        # Fuzzy match if no exact match
        if not matched:
            matches = process.extract(
                t, 
                [p.lower() for p in patterns], 
                scorer=fuzz.partial_ratio, 
                limit=3
            )
            for pattern, score, _ in matches:
                if score >= 80:  # threshold for intent match
                    intents.append((intent, pattern))
                    break
    
    return intents


# Debounce tracking
_last_sent = {}
_debounce_lock = threading.RLock()


def should_send(canonical_class, intent):
    """Check if we should send this message (debounce)."""
    key = (canonical_class, intent)
    now = time.time()
    
    with _debounce_lock:
        if now - _last_sent.get(key, 0) < DEBOUNCE_SECONDS:
            return False
        _last_sent[key] = now
    
    return True


_bedrock_client = None

def get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)
    return _bedrock_client

def build_messages_with_llm(transcript, timestamp, classes):
    """
    Use AWS Bedrock to dynamically frame intents based on keywords and context.
    """
    msgs = []
    classmap = get_classmap()
    
    system_prompt = '''You are an expert drag racing announcer AI.
You receive a transcript of what the human announcer just said, along with the racing classes detected in the transcript.
Your job is to identify if there is an intent for any of the classes and frame a concise announcement text using the exact fancy terms or keywords the human used.

Intents:
- CLASS_TO_LANES: Instructions to go to staging lanes, grid, track, line up, etc.
- CLASS_STANDBY: Instructions to hold, wait, get ready, standby, etc.
- GENERAL_ANNOUNCEMENT: Other important notices.

Output ONLY a JSON array. Each object must have:
- "class_name": exactly as provided in the input list
- "intent": the identified intent string
- "message_text": a beautifully framed sentence combining the class name and the human's keywords (e.g. "Super Pro, please make your way down to the staging lanes")
If no intent is detected, return an empty array [].'''

    prompt = f"Transcript: {transcript}\nDetected Classes: {classes}\n\nOutput JSON array:"
    
    try:
        client = get_bedrock_client()
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 200,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
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
            
        results = json.loads(content)
        
        for res in results:
            cls = res.get("class_name")
            intent = res.get("intent")
            text = res.get("message_text")
            
            if cls in classes and cls in classmap and should_send(cls, intent):
                msgs.append({
                    "class_id": classmap[cls]["id"],
                    "class_name": cls,
                    "intent": intent,
                    "transcription": transcript,
                    "message_text": text,
                    "timestamp": timestamp
                })
                
    except Exception as e:
        if DEBUG:
            print(f"[classifier] Bedrock framing error: {e}")
        # Fallback if LLM fails
        return build_messages_fallback(transcript, timestamp, classes)
        
    return msgs


def build_messages_fallback(transcript, timestamp, classes):
    """Fallback logic that uses the detected phrase/keywords to frame the message."""
    intents = find_intents_with_context(transcript)
    msgs = []
    classmap = get_classmap()
    
    for cls in classes:
        if cls not in classmap:
            if DEBUG:
                print(f"[classifier] warning: class '{cls}' not in classmap")
            continue
        
        for intent, matched_kw in intents:
            if should_send(cls, intent):
                class_id = classmap[cls]["id"]
                
                if intent == "CLASS_TO_LANES":
                    # Frame the intent using the keyword present in audio
                    text = f"{cls} {matched_kw}"
                elif intent == "CLASS_STANDBY":
                    text = f"{cls} {matched_kw}"
                elif intent == "GENERAL_ANNOUNCEMENT":
                    text = f"Attention {cls}: {transcript}"
                else:
                    text = transcript
                
                msgs.append({
                    "class_id": class_id,
                    "class_name": cls,
                    "intent": intent,
                    "transcription": transcript,
                    "message_text": text,
                    "timestamp": timestamp
                })
    
    return msgs


def build_messages(transcript, timestamp):
    """
    Build message list from transcript.
    Routes to LLM framing or fallback based on config.
    """
    classes = find_classes(transcript)
    if not classes:
        return []
        
    if USE_LLM_FRAMING:
        return build_messages_with_llm(transcript, timestamp, classes)
    else:
        return build_messages_fallback(transcript, timestamp, classes)


# Initialize alias map on import
rebuild_alias_map()

