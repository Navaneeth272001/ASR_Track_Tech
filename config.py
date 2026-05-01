"""
config.py - Centralized configuration with dynamic class loading

This module now loads classes from a JSON file (class_config.json) and
supports hot-reloading of the class map via MQTT.
"""

import json
from pathlib import Path
import threading

# ===========================
# Logging & Debugging
# ===========================
DEBUG = True
VOCABULARY_NAME = "racetrack-classes"

# ===========================
# AWS Transcribe Configuration
# ===========================
AWS_REGION = "us-east-1"
LANGUAGE_CODE = "en-US"

# ===========================
# Audio Configuration
# ===========================
MIC_SAMPLE_RATE = 44100  # Your laptop mic is usually 44.1k
STREAM_SAMPLE_RATE = 16000  # Amazon Transcribe standard
FRAME_MS = 20
MIC_DEVICE_INDEX = None  # Set to an integer to lock to a specific device, or None for auto-detection

# ===========================
# Class Map Configuration (Dynamic)
# ===========================
CLASS_CONFIG_PATH = Path("class_config.json")

_class_map = {}
_class_map_lock = threading.RLock()


def load_class_config(path: Path = None) -> list:
    """
    Load class configuration from JSON file.
    
    Expected JSON structure:
    {
      "classes": [
        {"id": 0, "name": "Class Name", "aliases": ["alias1", "alias2"]},
        ...
      ]
    }
    """
    if path is None:
        path = CLASS_CONFIG_PATH
    
    if not path.exists():
        raise FileNotFoundError(f"Class config JSON not found: {path}")
    
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("classes", [])


def build_classmap(classes: list) -> dict:
    """
    Convert list of {id, name, aliases} into CLASS_MAP shape:
    {
      "Class Name": {"id": 0, "aliases": ["alias1", "alias2"]},
      ...
    }
    """
    classmap = {}
    for cls in classes:
        cid = cls.get("id")
        name = cls.get("name")
        aliases = cls.get("aliases", [])
        
        if name is None or cid is None:
            continue
        
        classmap[name] = {
            "id": cid,
            "aliases": aliases,
        }
    return classmap


def initialize_classmap():
    """Initialize CLASS_MAP at import time from default config file."""
    global _class_map
    try:
        classes = load_class_config()
        _class_map = build_classmap(classes)
        if DEBUG:
            print(f"[config] loaded {len(_class_map)} classes from {CLASS_CONFIG_PATH}")
    except FileNotFoundError as e:
        print(f"[config] WARNING: {e}")
        _class_map = {}


def get_classmap() -> dict:
    """Get current CLASS_MAP (thread-safe)."""
    with _class_map_lock:
        return dict(_class_map)


def update_classmap_from_json(json_payload: dict):
    """
    Update CLASS_MAP from a JSON payload and persist to file.
    
    Payload format:
    {
      "classes": [
        {"id": 0, "name": "Class Name", "aliases": ["alias1", "alias2"]},
        ...
      ]
    }
    """
    global _class_map
    try:
        classes = json_payload.get("classes", [])
        with _class_map_lock:
            _class_map = build_classmap(classes)
        
        # Persist to disk
        with CLASS_CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(json_payload, f, indent=2)
            
        if DEBUG:
            print(f"[config] updated and persisted CLASS_MAP with {len(_class_map)} classes")
            print(f"[config] classes: {list(_class_map.keys())}")
    except Exception as e:
        if DEBUG:
            print(f"[config] failed to update/persist CLASS_MAP: {e}")


# Initialize on import
initialize_classmap()

# Expose as module-level convenience (for classifier.py compatibility)
CLASS_MAP = _class_map

# ===========================
# LLM Intent Framing Configuration
# ===========================
USE_LLM_FRAMING = False  # Set to True to use AWS Bedrock (Claude 3 Haiku) for intelligent intent framing
BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# ===========================
# Intent Patterns (Fallback if LLM is disabled)
# ===========================
INTENT_PATTERNS = {
    "CLASS_TO_LANES": [
        "to the lanes",
        "make your way to",
        "head to",
        "to the staging lanes",
        "please to the lanes",
        "to the grid",
        "bring it to the lanes",
        "proceed to staging",
        "report to staging",
        "pull up to",
        "we need you in the lanes",
        "time to line up",
        "come on down to the staging area",
        "we are calling"
    ],
    "CLASS_STANDBY": [
        "standby",
        "be on standby",
        "on deck",
        "be ready",
        "please be on standby",
        "hold your positions",
        "listen for the call",
        "in the hole",
        "prepare to stage",
        "get ready"
    ],
    "GENERAL_ANNOUNCEMENT": [
        "attention",
        "announcement",
        "briefing",
        "spectators",
        "fans",
        "everyone",
        "audience",
        "public",
        "listen up",
        "drivers meeting",
        "notice to all"
    ]
}

# ===========================
# Delivery Configuration
# ===========================
PUSH_ENDPOINT = "https://YOUR_BACKEND/notify"
DEBOUNCE_SECONDS = 180
DEDUP_WINDOW_MS = 5000  # Utterance-level deduplication window in milliseconds
QUEUE_DB = "outbox.db"

# ===========================
# MQTT Configuration
# ===========================
MQTT_BROKER = "54.152.201.16"  # or AWS IoT Core endpoint
MQTT_PORT = 1883
MQTT_TOPIC = "racetrack/announcements"
MQTT_CONFIG_TOPIC = "racetrack/config/classes"  # Topic for config updates
MQTT_CONFIG_REQUEST_TOPIC = "racetrack/config/request"  # Topic to request updates
MQTT_USERNAME = None  # set if broker requires auth
MQTT_PASSWORD = None
MQTT_QOS = 1  # QoS 0, 1, or 2

DELIVERY_MODE = "MQTT"  # or "HTTP"

