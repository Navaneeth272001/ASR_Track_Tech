"""
verify_config_fetch.py - Mock server to verify ASR configuration fetch

This script:
1. Listens for requests on 'racetrack/config/request'
2. Responds with class configuration on 'racetrack/config/classes'
"""

import json
import time
import paho.mqtt.client as mqtt

# MQTT Configuration
MQTT_BROKER = "54.152.201.16"
MQTT_PORT = 1883
MQTT_CONFIG_TOPIC = "racetrack/config/classes"
MQTT_CONFIG_REQUEST_TOPIC = "racetrack/config/request"

# Mock configuration
mock_config = {
    "classes": [
        {
            "id": 101,
            "name": "Verification Class",
            "aliases": ["verify", "test", "verification"]
        },
        {
            "id": 102,
            "name": "Raspberry Pi Class",
            "aliases": ["pi", "raspberry"]
        }
    ]
}

def on_connect(client, userdata, flags, rc):
    print(f"[mock] connected with code {rc}")
    client.subscribe(MQTT_CONFIG_REQUEST_TOPIC)
    print(f"[mock] subscribed to {MQTT_CONFIG_REQUEST_TOPIC}")

def on_message(client, userdata, msg):
    print(f"[mock] received message on {msg.topic}: {msg.payload.decode()}")
    
    if msg.topic == MQTT_CONFIG_REQUEST_TOPIC:
        print(f"[mock] sending updated config to {MQTT_CONFIG_TOPIC}")
        client.publish(MQTT_CONFIG_TOPIC, json.dumps(mock_config), qos=1)

if __name__ == "__main__":
    client = mqtt.Client(client_id="mock-asr-backend")
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"[mock] connecting to {MQTT_BROKER}...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("[mock] stopping")
