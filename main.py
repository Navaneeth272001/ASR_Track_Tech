# main.py - Updated to work with fixed transcribe_ws.py
import asyncio
import signal
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
    if DEBUG: 
        print("[transcript]", text)
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

    # Create a task for the audio streaming
    audio_task = asyncio.create_task(stream_audio(on_transcript))

    # Graceful shutdown handler
    stop_event = asyncio.Event()

    def shutdown_signal():
        if DEBUG: print("[main] shutdown signal received")
        stop_event.set()

    # Set up signal handlers for graceful shutdown
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, lambda s, f: shutdown_signal())
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda s, f: shutdown_signal())

    try:
        # Wait until a shutdown signal
        await stop_event.wait()
    except KeyboardInterrupt:
        if DEBUG: print("[main] KeyboardInterrupt received")
        shutdown_signal()

    if DEBUG: print("[main] cancelling audio task...")
    audio_task.cancel()
    try:
        await audio_task
    except asyncio.CancelledError:
        if DEBUG: print("[main] audio task cancelled cleanly")

    if DEBUG: print("[main] exiting")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if DEBUG: print("[main] KeyboardInterrupt caught, exiting")
