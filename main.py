import asyncio
from transcribe_ws import stream_audio
from classifier import build_messages
from config import DEBUG, DELIVERY_MODE

if DELIVERY_MODE == "HTTP":
    from queue_sender import init_db, queue_payload, flush_outbox, send_now
elif DELIVERY_MODE == "MQTT":
    from mqtt_sender import init_db, init_mqtt, queue_payload, flush_outbox, send_now
else:
    raise ValueError("Unknown DELIVERY_MODE in config.py")

async def on_transcript(text, ts_iso):
    if DEBUG: print("[transcript]", text)
    messages = build_messages(text, ts_iso)
    for m in messages:
        try:
            flush_outbox()
            send_now(m)
            if DEBUG: print("[sent]", m)
        except Exception as e:
            if DEBUG: print("[queueing]", e)
            queue_payload(m)

async def main():
    init_db()
    if DELIVERY_MODE == "MQTT":
        init_mqtt()
    flush_outbox()
    await stream_audio(on_transcript)

if __name__ == "__main__":
    asyncio.run(main())
