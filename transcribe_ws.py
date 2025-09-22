# transcribe_ws.py
import asyncio
import json
import datetime
import hmac
import hashlib
import queue
import aiohttp
import sounddevice as sd
import numpy as np
import boto3

from config import AWS_REGION, LANGUAGE_CODE, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE, FRAME_MS, DEBUG

def resample_pcm16(data, in_rate, out_rate):
    if in_rate == out_rate:
        return data
    duration = data.shape[0] / float(in_rate)
    out_len = int(round(duration * out_rate))
    resampled = np.interp(
        np.linspace(0, duration, out_len, endpoint=False),
        np.linspace(0, duration, data.shape[0], endpoint=False),
        data).astype(np.int16)
    return resampled

async def stream_audio(on_transcript):
    """
    Capture audio using sounddevice, push chunks to an asyncio-aware sender task
    which transmits them to the Transcribe websocket.
    """

    # thread-safe queue used by sounddevice callback (runs in a different thread)
    audio_q = queue.Queue()

    # get AWS credentials and build signed URL
    session = boto3.session.Session()
    creds = session.get_credentials().get_frozen_credentials()
    service = "transcribe"
    host = f"transcribestreaming.{AWS_REGION}.amazonaws.com:8443"
    endpoint = f"wss://{host}/stream-transcription-websocket?language-code={LANGUAGE_CODE}&media-encoding=pcm&sample-rate={STREAM_SAMPLE_RATE}"

    def sign_request():
        t = datetime.datetime.utcnow()
        amzdate = t.strftime("%Y%m%dT%H%M%SZ")
        datestamp = t.strftime("%Y%m%d")
        method = "GET"
        canonical_uri = "/stream-transcription-websocket"
        canonical_querystring = f"language-code={LANGUAGE_CODE}&media-encoding=pcm&sample-rate={STREAM_SAMPLE_RATE}"
        canonical_headers = f"host:{host}\n"
        signed_headers = "host"
        payload_hash = hashlib.sha256(("").encode("utf-8")).hexdigest()
        canonical_request = "\n".join([method, canonical_uri, canonical_querystring,
                                       canonical_headers, signed_headers, payload_hash])
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{AWS_REGION}/{service}/aws4_request"
        string_to_sign = "\n".join([algorithm, amzdate, credential_scope,
                                    hashlib.sha256(canonical_request.encode()).hexdigest()])
        def sign(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
        k_date = sign(("AWS4" + creds.secret_key).encode(), datestamp)
        k_region = sign(k_date, AWS_REGION)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{endpoint}&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential={creds.access_key}%2F{credential_scope}&X-Amz-Date={amzdate}&X-Amz-SignedHeaders={signed_headers}&X-Amz-Signature={signature}"

    signed_url = sign_request()

    async def mic_sender(ws):
        """Async task that pulls raw pcm chunks from audio_q and sends them via ws."""
        loop = asyncio.get_running_loop()
        try:
            while True:
                # wait for next chunk in a thread so we don't block the event loop
                chunk = await loop.run_in_executor(None, audio_q.get)
                if chunk is None:
                    # sentinel for shutdown
                    if DEBUG: print("[mic_sender] got shutdown sentinel")
                    break
                try:
                    await ws.send_bytes(chunk)
                    if DEBUG: print("[mic_sender] sent chunk len", len(chunk))
                except Exception as e:
                    if DEBUG: print("[mic_sender] send failed", e)
                    # if send fails, requeue minimally or break
                    # requeue can be dangerous if socket is dead; break to let caller handle
                    break
        except asyncio.CancelledError:
            if DEBUG: print("[mic_sender] cancelled")
            raise

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(signed_url, timeout=10) as ws:
            if DEBUG: print("[transcribe] connected")

            # sounddevice callback (runs in audio thread)
            def callback(indata, frames, time_info, status):
                # indata is float32 in [-1,1] typically; convert to int16 PCM range
                try:
                    mono = (indata[:, 0] * 32767).astype(np.int16)
                except Exception:
                    # if channels==1, indata can be 1-D; handle gracefully
                    mono = (np.asarray(indata).flatten() * 32767).astype(np.int16)
                resampled = resample_pcm16(mono, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE)
                audio_q.put(resampled.tobytes())
                if DEBUG:
                    try:
                        print("[mic cb] frames", frames, "resampled len", len(resampled))
                    except Exception:
                        pass

            # start the sender task before opening mic to ensure ready to send
            sender_task = asyncio.create_task(mic_sender(ws))

            # open the input stream (this blocks only the context, callback runs on audio thread)
            try:
                # with sd.InputStream(samplerate=MIC_SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
                MIC_DEVICE_INDEX=0
                with sd.InputStream(device=MIC_DEVICE_INDEX, samplerate=MIC_SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
                    if DEBUG:
                        dev = sd.query_devices(MIC_DEVICE_INDEX)
                        print("[mic] using device:", dev['name'], "channels:", dev['max_input_channels'], "rate:", MIC_SAMPLE_RATE)
                    # consume websocket messages while mic is active
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if "Transcript" in data:
                                for r in data["Transcript"]["Results"]:
                                    if not r.get("IsPartial") and r.get("Alternatives"):
                                        text = r["Alternatives"][0]["Transcript"]
                                        ts = datetime.datetime.datetime.utcnow().isoformat() + "Z"
                                        await on_transcript(text, ts)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            dev = sd.query_devices(MIC_DEVICE_INDEX)
                            if DEBUG: print("[mic] using device:", dev['name'], "channels:", dev['max_input_channels'])
                            break
            finally:
                # shutdown: tell sender to stop and cancel task
                audio_q.put(None)  # sentinel
                await asyncio.sleep(0)  # let event loop cycle
                if not sender_task.done():
                    sender_task.cancel()
                    try:
                        await sender_task
                    except asyncio.CancelledError:
                        if DEBUG: print("[mic_sender] cancelled on shutdown")
                if DEBUG: print("[transcribe] connection closed")
