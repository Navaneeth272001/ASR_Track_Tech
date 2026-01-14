"""
test_config_update.py - Example script to send class config updates over MQTT

Usage:
    python test_config_update.py

This demonstrates how to send a new class configuration to the running system
without restarting it.
"""

import json
import time
import paho.mqtt.client as mqtt

# MQTT Configuration
MQTT_BROKER = "54.152.201.16"
MQTT_PORT = 1883
MQTT_CONFIG_TOPIC = "racetrack/config/classes"

# Example 1: Minimal configuration (2 classes)
config_example_1 = {
    "classes": [
        {
            "id": 0,
            "name": "Junior Class",
            "aliases": ["junior", "jr", "jr class", "junior class"]
        },
        {
            "id": 1,
            "name": "Pro Class",
            "aliases": ["pro", "professional", "pro class"]
        }
    ]
}

# Example 2: Full configuration (all racing classes)
config_example_2 = {
    "classes": [
        {
            "id": 0,
            "name": "Stock Eliminator",
            "aliases": ["stock eliminator", "stk elim", "stk elim.", "stock elim", "stock", "se"]
        },
        {
            "id": 1,
            "name": "Super Stock",
            "aliases": ["super stock", "s stock", "ss"]
        },
        {
            "id": 2,
            "name": "Super Street",
            "aliases": ["super street", "s street", "sst"]
        },
        {
            "id": 3,
            "name": "Super Gas",
            "aliases": ["super gas", "s gas", "sg"]
        },
        {
            "id": 4,
            "name": "Pro ET",
            "aliases": ["pro et", "et", "proet", "pro"]
        },
        {
            "id": 5,
            "name": "Super Pro",
            "aliases": ["superpro", "su pro", "supro", "s pro", "spro"]
        },
        {
            "id": 6,
            "name": "Super Comp",
            "aliases": ["super comp", "super competition", "s comp", "sc"]
        },
        {
            "id": 7,
            "name": "Comp Eliminator",
            "aliases": ["comp eliminator", "competition eliminator", "comp", "ce"]
        },
        {
            "id": 8,
            "name": "Top Dragster",
            "aliases": ["top dragster", "td", "top drg"]
        },
        {
            "id": 9,
            "name": "Top Sportsman",
            "aliases": ["top sportsman", "ts", "top sportzman"]
        },
        {
            "id": 10,
            "name": "General",
            "aliases": ["audience", "public", "spectators", "fans", "everyone"]
        }
    ]
}

# Example 3: Updated config with new classes
config_example_3 = {
    "classes": [
        {
            "id": 0,
            "name": "Street Bike",
            "aliases": ["street bike", "bike", "sb", "street"]
        },
        {
            "id": 1,
            "name": "Modified",
            "aliases": ["modified", "mod", "modified car"]
        },
        {
            "id": 2,
            "name": "Motorcycle",
            "aliases": ["motorcycle", "moto", "bike", "mc"]
        }
    ]
}


def send_config(config_dict, broker=MQTT_BROKER, port=MQTT_PORT, topic=MQTT_CONFIG_TOPIC):
    """
    Send configuration to MQTT broker.
    
    Args:
        config_dict: Configuration dictionary with "classes" key
        broker: MQTT broker host
        port: MQTT broker port
        topic: Topic to publish to
    """
    try:
        client = mqtt.Client(client_id=f"config-sender-{int(time.time())}")
        
        print(f"[test] connecting to {broker}:{port}...")
        client.connect(broker, port, keepalive=60)
        client.loop_start()
        
        # Give it time to connect
        time.sleep(1)
        
        # Convert config to JSON
        payload = json.dumps(config_dict, indent=2)
        
        print(f"[test] publishing to topic: {topic}")
        print(f"[test] payload ({len(payload)} bytes):")
        print(payload)
        
        result = client.publish(topic, payload, qos=1)
        
        if result.rc == 0:
            print(f"[test] ✓ published successfully (mid={result.mid})")
        else:
            print(f"[test] ✗ publish failed with code {result.rc}")
        
        time.sleep(1)
        client.loop_stop()
        client.disconnect()
        
    except Exception as e:
        print(f"[test] error: {e}")


if __name__ == "__main__":
    import sys
    
    print("=" * 70)
    print("MQTT Class Configuration Sender")
    print("=" * 70)
    print()
    
    if len(sys.argv) > 1:
        example_num = int(sys.argv[1])
    else:
        print("Usage: python test_config_update.py [1|2|3]")
        print()
        print("  1 = Minimal config (2 classes)")
        print("  2 = Full config (all racing classes)")
        print("  3 = Custom config (street bikes, motorcycles)")
        print()
        example_num = 1
    
    configs = {
        1: ("Minimal Config (2 Classes)", config_example_1),
        2: ("Full Config (All Racing Classes)", config_example_2),
        3: ("Custom Config (Street Bikes)", config_example_3),
    }
    
    title, config = configs.get(example_num, configs[1])
    
    print(f"Sending: {title}")
    print("=" * 70)
    print()
    
    send_config(config)
    
    print()
    print("=" * 70)
    print("Check main.py logs for:")
    print("  [config] updated CLASS_MAP with N classes")
    print("  [classifier] rebuilt alias map: M entries")
    print("  [mqtt] class config updated successfully")
    print("=" * 70)
