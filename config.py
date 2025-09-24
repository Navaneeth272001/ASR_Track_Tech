AWS_REGION = "us-east-1"
LANGUAGE_CODE = "en-US"

# Mic / audio
MIC_SAMPLE_RATE = 44100   # your laptop mic is usually 44.1k
STREAM_SAMPLE_RATE = 16000  # Amazon Transcribe standard
FRAME_MS = 20

CLASS_MAP = {
    "Stock Eliminator": {
        "id": 0,
        "aliases": ["stock eliminator", "stk elim", "stk elim.", "stock elim", "stock"]
    },
    "Super Stock": {
        "id": 1,
        "aliases": ["super stock", "s stock", "ss"]
    },
    "Super Street": {
        "id": 2,
        "aliases": ["super street", "s street", "sst"]
    },
    "Super Gas": {
        "id": 3,
        "aliases": ["super gas", "s gas", "sg"]
    },
    "Pro ET": {
        "id": 5,
        "aliases": ["ET", "ProET"]
    },
    "Super Pro": {
        "id": 5,
        "aliases": ["superpro", "su pro", "supro", "s pro", "spro"]
    },
    "Super Comp": {
        "id": 6,
        "aliases": ["super comp", "super competition", "s comp", "sc"]
    },
    "Comp Eliminator": {
        "id": 7,
        "aliases": ["comp eliminator", "competition eliminator", "comp", "ce"]
    },
    "Top Dragster": {
        "id": 8,
        "aliases": ["top dragster", "td", "top drg"]
    },
    "Top Sportsman": {
        "id": 9,
        "aliases": ["top sportsman", "ts", "top sportzman"]
    },
    "General": {
        "id": 10,
        "aliases": ["Audience", "public", "spectators", "fans", "everyone"]
    }
}


# ----------------------------
# Intent patterns
# ----------------------------
INTENT_PATTERNS = {
    "CLASS_TO_LANES": [
        "to the lanes",
        "make your way to",
        "head to",
        "to the staging lanes",
        "please to the lanes"
    ],
    "CLASS_STANDBY": [
        "standby",
        "be on standby",
        "on deck",
        "be ready",
        "please be on standby"
    ],
    "GENERAL_ANNOUNCEMENT": [
        "attention",
        "announcement",
        "briefing",
        "spectators",
        "fans",
        "everyone",
        "audience",
        "public"
    ]
}

# Delivery endpoint (replace with your API / SNS / FCM gateway)
PUSH_ENDPOINT = "https://YOUR_BACKEND/notify"

# Debounce duplicate announcements
DEBOUNCE_SECONDS = 180

# Local persistence
QUEUE_DB = "outbox.db"

DEBUG = True

MQTT_BROKER = "54.152.201.16"   # or AWS IoT Core endpoint
MQTT_PORT = 1883
MQTT_TOPIC = "racetrack/announcements"
MQTT_USERNAME = None   # set if broker requires auth
MQTT_PASSWORD = None
MQTT_QOS = 1           # QoS 0, 1, or 2

DELIVERY_MODE = "MQTT"   # or "HTTP"
VOCABULARY_NAME = "racetrack-classes"
