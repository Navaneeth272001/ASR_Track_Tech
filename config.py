AWS_REGION = "us-east-1"
LANGUAGE_CODE = "en-US"

# Mic / audio
MIC_SAMPLE_RATE = 44100   # your laptop mic is usually 44.1k
STREAM_SAMPLE_RATE = 16000  # Amazon Transcribe standard
FRAME_MS = 20

# Class definitions with aliases
CLASS_MAP = {
    # Existing drag race style
    "amateur": ["amateur", "amateurs"],
    "pro": ["pro", "pros", "professional"],
    "junior": ["junior", "juniors"],

    # New race-track categories
    "safety_car": ["safety car", "pace car"],
    "medical_car": ["medical car", "ambulance"],
    "marshal": ["marshal", "marshals", "track official"],
    "spectators": ["spectator", "spectators", "audience", "fans"],
    "weather": ["rain", "storm", "wet track", "dry track"],
    "winner": ["winner", "champion", "podium", "first place"],
}

# Intents
INTENT_PATTERNS = {
    "CLASS_TO_LANES": ["to the lanes", "proceed to the lanes", "report to the lanes"],
    "CLASS_STANDBY": ["standby", "get ready", "prepare"],
    "RACE_CONTROL": [
        "blue flag", "yellow flag", "red flag",
        "safety car", "virtual safety car",
        "under investigation"
    ],
    "PIT_STRATEGY": ["box", "pit", "tire", "strategy", "stay out"],
    "INCIDENT": ["crash", "accident", "stopped", "fire", "debris"],
    "RACE_END": ["checkered flag", "winner", "podium", "end of race", "race complete"],
    "GENERAL_INFO": ["attention", "briefing", "announcement", "spectators"],
}

# Delivery endpoint (replace with your API / SNS / FCM gateway)
PUSH_ENDPOINT = "https://YOUR_BACKEND/notify"

# Debounce duplicate announcements
DEBOUNCE_SECONDS = 180

# Local persistence
QUEUE_DB = "outbox.db"

DEBUG = True

MQTT_BROKER = "node.kaatru.org"   # or AWS IoT Core endpoint
MQTT_PORT = 1883
MQTT_TOPIC = "racetrack/announcements"
MQTT_USERNAME = None   # set if broker requires auth
MQTT_PASSWORD = None
MQTT_QOS = 1           # QoS 0, 1, or 2

DELIVERY_MODE = "MQTT"   # or "HTTP"
VOCABULARY_NAME = "racetrack-classes"
