"""
mqtt_sender.py - MQTT client with dynamic class config support

This module now subscribes to two topics:
1. racetrack/announcements - outbound announcements (existing)
2. racetrack/config/classes - inbound class configuration updates
"""

import sqlite3
import json
import time
import paho.mqtt.client as mqtt
from config import (
    QUEUE_DB, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_CONFIG_TOPIC,
    MQTT_CONFIG_REQUEST_TOPIC,
    MQTT_USERNAME, MQTT_PASSWORD, MQTT_QOS, DEBUG
)
from config import update_classmap_from_json
from classifier import rebuild_alias_map

_client = None
event_id = None  # global event_id, set from MQTT subscription


def on_connect(client, userdata, flags, rc):
    """Called when client connects to broker."""
    if DEBUG:
        print(f"[mqtt] connected with code {rc} to {MQTT_BROKER}:{MQTT_PORT}")
    
    # Subscribe to event updates
    client.subscribe("racetrack/event")
    
    # Subscribe to class config updates
    client.subscribe(MQTT_CONFIG_TOPIC)
    if DEBUG:
        print(f"[mqtt] subscribed to {MQTT_CONFIG_TOPIC}")
    
    # Request latest config
    client.publish(MQTT_CONFIG_REQUEST_TOPIC, "GET", qos=MQTT_QOS)
    if DEBUG:
        print(f"[mqtt] requested latest config on {MQTT_CONFIG_REQUEST_TOPIC}")


def on_message(client, userdata, msg):
    """Called when a message is received on a subscribed topic."""
    global event_id
    
    try:
        payload_str = msg.payload.decode("utf-8").strip()
        
        # Handle event_id updates
        if msg.topic == "racetrack/event":
            event_id = payload_str
            if DEBUG:
                print(f"[mqtt] event_id updated → {event_id}")
        
        # Handle class config updates
        elif msg.topic == MQTT_CONFIG_TOPIC:
            if DEBUG:
                print(f"[mqtt] received config update on {MQTT_CONFIG_TOPIC}")
            
            try:
                config_json = json.loads(payload_str)
                update_classmap_from_json(config_json)
                rebuild_alias_map()
                if DEBUG:
                    print("[mqtt] class config updated successfully")
            except json.JSONDecodeError as e:
                if DEBUG:
                    print(f"[mqtt] invalid JSON in config message: {e}")
            except Exception as e:
                if DEBUG:
                    print(f"[mqtt] error updating config: {e}")
    
    except Exception as e:
        if DEBUG:
            print(f"[mqtt] error in on_message: {e}")


def init_mqtt():
    """Initialize MQTT client and connect."""
    global _client
    
    _client = mqtt.Client()
    
    if MQTT_USERNAME:
        _client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    _client.on_connect = on_connect
    _client.on_message = on_message
    
    _client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    _client.loop_start()
    
    if DEBUG:
        print(f"[mqtt] connecting to {MQTT_BROKER}:{MQTT_PORT}")


def init_db():
    """Initialize SQLite outbox database."""
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT,
            created_at REAL,
            sent INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def queue_payload(payload):
    """Queue a payload to outbox for later delivery."""
    global event_id
    
    p = dict(payload)
    p["event_id"] = event_id
    
    conn = sqlite3.connect(QUEUE_DB)
    conn.execute(
        "INSERT INTO outbox (payload, created_at, sent) VALUES (?, ?, 0)",
        (json.dumps(p), time.time())
    )
    conn.commit()
    conn.close()
    
    if DEBUG:
        print(f"[queue] queued {len(json.dumps(p))} bytes")


def send_now(payload):
    """Send payload immediately via MQTT."""
    global _client, event_id
    
    if not _client:
        raise RuntimeError("MQTT not initialized")
    
    p = dict(payload)
    p["event_id"] = event_id
    
    msg = json.dumps(p)
    result = _client.publish(MQTT_TOPIC, msg, qos=MQTT_QOS)
    
    if result.rc != 0:
        raise RuntimeError(f"MQTT publish failed with code {result.rc}")
    
    if DEBUG:
        print(f"[mqtt] published on {MQTT_TOPIC}: {msg[:100]}...")


def flush_outbox():
    """Send all queued messages in outbox."""
    conn = sqlite3.connect(QUEUE_DB)
    cur = conn.cursor()
    
    for id_, payload_text in cur.execute(
        "SELECT id, payload FROM outbox WHERE sent=0 LIMIT 10"
    ):
        try:
            p = json.loads(payload_text)
            send_now(p)
            conn.execute("UPDATE outbox SET sent=1 WHERE id=?", (id_,))
            conn.commit()
            if DEBUG:
                print(f"[outbox] flushed id {id_}")
        except Exception as e:
            if DEBUG:
                print(f"[outbox] error flushing id {id_}: {e}")
            break
    
    conn.close()
