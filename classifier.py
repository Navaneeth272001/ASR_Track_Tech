import re, time
from rapidfuzz import fuzz, process
from config import CLASS_MAP, INTENT_PATTERNS, DEBOUNCE_SECONDS

_alias_to_canonical = {}
for canon, aliases in CLASS_MAP.items():
    _alias_to_canonical[canon.lower()] = canon
    for a in aliases:
        _alias_to_canonical[a.lower()] = canon
_alias_choices = list(_alias_to_canonical.keys())

def normalize_text(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def find_classes(transcript, threshold=75):
    t = normalize_text(transcript)
    found = set()
    for alias, canon in _alias_to_canonical.items():
        if alias in t:
            found.add(canon)
    if not found:
        matches = process.extract(t, _alias_choices, scorer=fuzz.partial_ratio, limit=3)
        for alias, score, _ in matches:
            if score >= threshold:
                found.add(_alias_to_canonical[alias])
    return list(found)

def find_intents(transcript):
    t = normalize_text(transcript)
    intents = set()
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if p in t:
                intents.add(intent)
    return list(intents)

_last_sent = {}
def should_send(canonical_class, intent):
    key = (canonical_class, intent)
    now = time.time()
    if now - _last_sent.get(key, 0) < DEBOUNCE_SECONDS:
        return False
    _last_sent[key] = now
    return True

def build_messages(transcript, timestamp):
    classes = find_classes(transcript)
    intents = find_intents(transcript)
    msgs = []
    for cls in classes:
        for intent in intents:
            if should_send(cls, intent):
                text = f"{cls} to the lanes" if intent == "CLASS_TO_LANES" else f"{cls} standby"
                msgs.append({
                    "class_id": cls,
                    "intent": intent,
                    "transcription": transcript,
                    "message_text": text,
                    "timestamp": timestamp
                })
    return msgs
