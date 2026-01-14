"""
classifier.py - Class and intent recognition with thread-safe dynamic class map

This module now pulls CLASS_MAP dynamically from config and rebuilds alias
lookup tables whenever CLASS_MAP is updated.
"""

import re
import time
import threading
from rapidfuzz import fuzz, process
from config import INTENT_PATTERNS, DEBOUNCE_SECONDS, get_classmap, DEBUG

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


def find_intents(transcript):
    """Find matching intent types from transcript."""
    t = normalize_text(transcript)
    intents = set()
    
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if p.lower() in t:
                intents.add(intent)
    
    return list(intents)


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


def build_messages(transcript, timestamp):
    """
    Build message list from transcript.
    Each (class, intent) pair gets one message.
    """
    classes = find_classes(transcript)
    intents = find_intents(transcript)
    msgs = []
    
    classmap = get_classmap()
    
    for cls in classes:
        if cls not in classmap:
            if DEBUG:
                print(f"[classifier] warning: class '{cls}' not in classmap")
            continue
        
        for intent in intents:
            if should_send(cls, intent):
                class_id = classmap[cls]["id"]
                
                if intent == "CLASS_TO_LANES":
                    text = f"{cls} to the lanes"
                elif intent == "CLASS_STANDBY":
                    text = f"{cls} standby"
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


# Initialize alias map on import
rebuild_alias_map()
