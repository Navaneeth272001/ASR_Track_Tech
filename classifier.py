import re
import time
import hashlib
import threading
import json
import boto3
import jellyfish
from rapidfuzz import fuzz, process
from config import (
    INTENT_PATTERNS, DEBOUNCE_SECONDS, DEDUP_WINDOW_MS, get_classmap, DEBUG,
    USE_LLM_FRAMING, BEDROCK_MODEL_ID, AWS_REGION
)

# ===========================
# Thread-safe alias mapping
# ===========================
_alias_to_canonical = {}
_alias_choices = []
_canonical_names = []          # flat list of all canonical class names
_phonetic_index = {}           # metaphone → canonical name(s)
_alias_lock = threading.RLock()


def rebuild_alias_map():
    """
    Rebuild _alias_to_canonical and _alias_choices from current CLASS_MAP.
    Call this whenever CLASS_MAP is updated.
    Also rebuilds the phonetic index for Metaphone-based matching.
    """
    global _alias_to_canonical, _alias_choices, _canonical_names, _phonetic_index

    classmap = get_classmap()

    with _alias_lock:
        _alias_to_canonical.clear()
        _phonetic_index.clear()

        # Map canonical name to itself (lowercase)
        for canon in classmap.keys():
            _alias_to_canonical[canon.lower()] = canon

        # Map each alias to canonical name
        for canon, data in classmap.items():
            aliases = data.get("aliases", [])
            for alias in aliases:
                _alias_to_canonical[alias.lower()] = canon

        _alias_choices = list(_alias_to_canonical.keys())
        _canonical_names = list(classmap.keys())

        # Build phonetic index — map Metaphone code to canonical names
        for alias_lower, canon in _alias_to_canonical.items():
            try:
                code = jellyfish.metaphone(alias_lower)
                if code not in _phonetic_index:
                    _phonetic_index[code] = set()
                _phonetic_index[code].add(canon)
            except Exception:
                pass  # skip unparseable aliases (e.g. purely numeric)

    if DEBUG:
        print(f"[classifier] rebuilt alias map: {len(_alias_to_canonical)} entries, "
              f"{len(_phonetic_index)} phonetic codes")


def normalize_text(s):
    """Normalize text for matching."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ===========================
# Fix 1 + Fix 2: Multi-class detection constrained to canonical list
# ===========================

def _exact_substring_scan(normalized_transcript):
    """
    Scan transcript for exact alias substrings.
    Uses longest-match-first to avoid partial overlaps
    (e.g. "super comp" should not also match "comp" → Comp Eliminator
     when "Super Comp" is a valid class).
    """
    found = {}  # canonical_name → matched alias (longest wins)

    with _alias_lock:
        # Sort aliases longest-first so longer matches take priority
        sorted_aliases = sorted(_alias_to_canonical.keys(), key=len, reverse=True)
        # Track which character positions have already been claimed
        claimed = set()

        for alias in sorted_aliases:
            start = 0
            while True:
                idx = normalized_transcript.find(alias, start)
                if idx == -1:
                    break

                # Ensure word boundaries: the match should not be a substring
                # of a longer word in the transcript
                end_idx = idx + len(alias)
                before_ok = (idx == 0 or normalized_transcript[idx - 1] == ' ')
                after_ok = (end_idx == len(normalized_transcript) or
                            normalized_transcript[end_idx] == ' ')

                if before_ok and after_ok:
                    # Check no overlap with already-claimed positions
                    match_positions = set(range(idx, end_idx))
                    if not match_positions & claimed:
                        canon = _alias_to_canonical[alias]
                        # Keep the longest alias match per canonical name
                        if canon not in found or len(alias) > len(found[canon]):
                            found[canon] = alias
                        claimed |= match_positions

                start = idx + 1

    return set(found.keys())


def _fuzzy_scan(normalized_transcript, already_found, threshold=82):
    """
    Fuzzy-match transcript against alias list.
    Only adds classes NOT already found by exact matching.
    Uses a higher threshold (82) to reduce false positives like
    "super street" → "street et".
    """
    additional = set()

    with _alias_lock:
        # Split transcript into sliding windows of 1-4 words for targeted fuzzy
        words = normalized_transcript.split()
        candidates = set()
        for window_size in range(1, min(5, len(words) + 1)):
            for i in range(len(words) - window_size + 1):
                fragment = " ".join(words[i:i + window_size])
                candidates.add(fragment)

        for fragment in candidates:
            matches = process.extract(
                fragment,
                _alias_choices,
                scorer=fuzz.ratio,  # Use full ratio, not partial_ratio, for precision
                limit=2
            )
            for alias, score, _ in matches:
                if score >= threshold:
                    canon = _alias_to_canonical[alias]
                    if canon not in already_found:
                        additional.add(canon)

    return additional


def _phonetic_scan(normalized_transcript, already_found):
    """
    Phonetic matching using Metaphone to catch speech-to-text near-misses.
    Only returns classes that exist in the canonical list.
    """
    additional = set()
    words = normalized_transcript.split()

    with _alias_lock:
        # Try 1-4 word combinations
        for window_size in range(1, min(5, len(words) + 1)):
            for i in range(len(words) - window_size + 1):
                fragment = " ".join(words[i:i + window_size])
                try:
                    code = jellyfish.metaphone(fragment)
                    if code in _phonetic_index:
                        for canon in _phonetic_index[code]:
                            if canon not in already_found:
                                additional.add(canon)
                except Exception:
                    pass

    return additional


def find_classes(transcript, threshold=82):
    """
    Find ALL matching class names from transcript.
    Implements a three-pass strategy:
      1. Exact substring match (longest-first, word-boundary aware)
      2. Fuzzy matching on sliding windows (high threshold)
      3. Phonetic matching via Metaphone

    All results are constrained to the canonical class list — no class name
    that is not in the class map will ever be returned.
    """
    t = normalize_text(transcript)
    if not t:
        return []

    # Pass 1: exact substring
    found = _exact_substring_scan(t)

    # Pass 2: fuzzy matching (always runs — not gated by "if not found")
    fuzzy_found = _fuzzy_scan(t, found, threshold=threshold)
    found |= fuzzy_found

    # Pass 3: phonetic matching
    phonetic_found = _phonetic_scan(t, found)
    found |= phonetic_found

    # Final validation: only return classes that exist in the current classmap
    classmap = get_classmap()
    validated = [cls for cls in found if cls in classmap]

    if DEBUG and validated:
        print(f"[classifier] detected classes: {validated} from: '{transcript}'")

    return validated


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


# ===========================
# Debounce tracking (per class+intent, long window)
# ===========================
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


# ===========================
# Fix 3: Utterance-level deduplication (short window)
# ===========================
_recent_results = {}
_dedup_lock = threading.RLock()


def _clean_stale_dedup_entries():
    """Remove expired entries from the dedup cache to prevent memory leaks."""
    now = time.time() * 1000
    stale_keys = [k for k, ts in _recent_results.items()
                  if (now - ts) > DEDUP_WINDOW_MS * 2]
    for k in stale_keys:
        del _recent_results[k]


def is_duplicate_result(result_classes, intent):
    """
    Check if a result with the same classes + intent was already emitted
    within the DEDUP_WINDOW_MS window.

    Returns True if this is a duplicate (should be suppressed).
    """
    key_data = str(sorted(result_classes) + [intent])
    key = hashlib.md5(key_data.encode()).hexdigest()
    now = time.time() * 1000

    with _dedup_lock:
        _clean_stale_dedup_entries()

        if key in _recent_results and (now - _recent_results[key]) < DEDUP_WINDOW_MS:
            if DEBUG:
                print(f"[classifier] suppressing duplicate: classes={result_classes} intent={intent}")
            return True

        _recent_results[key] = now

    return False


# ===========================
# LLM framing (Bedrock)
# ===========================
_bedrock_client = None

def get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client('bedrock-runtime', region_name=AWS_REGION)
    return _bedrock_client


def _build_canonical_class_list_str():
    """Build a formatted string of all canonical class names for the LLM prompt."""
    classmap = get_classmap()
    return ", ".join(sorted(classmap.keys()))


def build_messages_with_llm(transcript, timestamp, classes):
    """
    Use AWS Bedrock to dynamically frame intents based on keywords and context.
    Updated prompt includes canonical class list constraint and multi-class instruction.
    """
    msgs = []
    classmap = get_classmap()
    canonical_list_str = _build_canonical_class_list_str()

    system_prompt = f'''You are an expert drag racing announcer AI.
You receive a transcript of what the human announcer just said, along with the racing classes detected in the transcript.
Your job is to identify if there is an intent for any of the classes and frame a concise announcement text using the exact fancy terms or keywords the human used.

IMPORTANT CONSTRAINTS:
1. You must only use class names that exactly match one of the following valid classes. Do not infer, guess, or return any class name not on this list:
[{canonical_list_str}]

2. If the user mentions more than one racing class, return ALL of them as separate objects in the JSON array. Do not return only the first class mentioned.

Intents:
- CLASS_TO_LANES: Instructions to go to staging lanes, grid, track, line up, etc.
- CLASS_STANDBY: Instructions to hold, wait, get ready, standby, etc.
- GENERAL_ANNOUNCEMENT: Other important notices.

Output ONLY a JSON array. Each object must have:
- "class_name": exactly as provided in the input list (must match canonical list above)
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

            # Validate: class must be in the detected list AND in the classmap
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
    Applies utterance-level deduplication before returning.
    """
    classes = find_classes(transcript)
    if not classes:
        return []

    if USE_LLM_FRAMING:
        msgs = build_messages_with_llm(transcript, timestamp, classes)
    else:
        msgs = build_messages_fallback(transcript, timestamp, classes)

    # Fix 3: Utterance-level deduplication
    # Group messages by intent to build dedup keys
    if msgs:
        # Build a combined dedup key from all classes + first intent
        all_classes_in_msgs = [m["class_name"] for m in msgs]
        all_intents_in_msgs = list(set(m["intent"] for m in msgs))

        for intent in all_intents_in_msgs:
            classes_for_intent = [m["class_name"] for m in msgs if m["intent"] == intent]
            if is_duplicate_result(classes_for_intent, intent):
                # Suppress all messages for this duplicate group
                msgs = [m for m in msgs if m["intent"] != intent]

    return msgs


# Initialize alias map on import
rebuild_alias_map()
