import sqlite3, json, time
import paho.mqtt.client as mqtt
from config import QUEUE_DB, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_USERNAME, MQTT_PASSWORD, MQTT_QOS, DEBUG

_client = None
event_id = None  # global event_id, set from MQTT subscription

def on_connect(client, userdata, flags, rc):
    if DEBUG:
        print(f"[mqtt] connected with code {rc} to {MQTT_BROKER}:{MQTT_PORT}")
    # subscribe to the event topic for updates
    client.subscribe("racetracks/event")

def on_message(client, userdata, msg):
    global event_id
    try:
        payload = msg.payload.decode("utf-8").strip()
        event_id = payload
        if DEBUG:
            print(f"[mqtt] event_id updated → {event_id}")
    except Exception as e:
        if DEBUG:
            print("[mqtt] failed to parse event_id:", str(e))

def init_mqtt():
    global _client
    _client = mqtt.Client()
    if MQTT_USERNAME:
        _client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    _client.on_connect = on_connect
    _client.on_message = on_message
    _client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    _client.loop_start()
    if DEBUG:
        print("[mqtt] connecting to broker", MQTT_BROKER)

def init_db():
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT,
        created_at REAL,
        sent INTEGER DEFAULT 0)""")
    conn.commit(); conn.close()

def queue_payload(payload):
    # attach event_id if available
    global event_id
    p = dict(payload)
    p["event_id"] = event_id
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute("INSERT INTO outbox (payload, created_at, sent) VALUES (?, ?, 0)",
                 (json.dumps(p), time.time()))
    conn.commit(); conn.close()
    if DEBUG: print("[queue] queued", p)

def send_now(payload):
    global _client, event_id
    if not _client:
        raise RuntimeError("MQTT not initialized")
    # attach event_id if available
    p = dict(payload)
    p["event_id"] = event_id
    msg = json.dumps(p)
    result = _client.publish(MQTT_TOPIC, msg, qos=MQTT_QOS)
    if result.rc != 0:
        raise RuntimeError("MQTT publish failed")
    if DEBUG: print("[mqtt] published:", msg)

def flush_outbox():
    conn = sqlite3.connect(QUEUE_DB)
    cur = conn.cursor()
    for id_, payload_text in cur.execute("SELECT id, payload FROM outbox WHERE sent=0"):
        try:
            p = json.loads(payload_text)
            send_now(p)
            conn.execute("UPDATE outbox SET sent=1 WHERE id=?", (id_,))
            conn.commit()
            if DEBUG: print("[outbox] sent id", id_)
        except Exception as e:
            if DEBUG: print("[outbox] failed id", id_, str(e))
            break
    conn.close()
