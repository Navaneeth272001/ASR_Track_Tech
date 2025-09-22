AWS_REGION = "us-east-1"
LANGUAGE_CODE = "en-US"

# Mic / audio
MIC_SAMPLE_RATE = 44100   # your laptop mic is usually 44.1k
STREAM_SAMPLE_RATE = 16000  # Amazon Transcribe standard
FRAME_MS = 20

# Class definitions with aliases
CLASS_MAP = {
    "Super Pro": ["super pro", "s pro", "su pro", "supro"],
    "Sportsman": ["sportsman", "sports man", "sportzman"],
    "Amateur": ["amateur", "amature", "amatuer"]
}

# Intents
INTENT_PATTERNS = {
    "CLASS_TO_LANES": ["to the lanes", "to lanes"],
    "CLASS_STANDBY": ["standby", "on standby"]
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
