# transcribe_ws.py - Fully patched version with correct AWS signature, EventStream marshalling,
# and fixed asyncio event loop handling for mic callback

import asyncio
import json
import datetime
import hmac
import hashlib
import struct
import zlib
import urllib.parse
import aiohttp
import sounddevice as sd
import numpy as np
import boto3

from config import AWS_REGION, LANGUAGE_CODE, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE, FRAME_MS, DEBUG

# ----------------------------
# Fixed EventStream Marshaller for AWS Transcribe
# ----------------------------
class EventStreamMarshaller:
    """AWS EventStream marshaller for Transcribe WebSocket messages"""

    @staticmethod
    def _calculate_crc32(data):
        return zlib.crc32(data) & 0xffffffff

    @staticmethod
    def _encode_headers(headers):
        encoded_headers = b''

        for name, value in headers.items():
            name_bytes = name.encode('utf-8')
            encoded_headers += struct.pack('!B', len(name_bytes))
            encoded_headers += name_bytes

            if isinstance(value, str):
                encoded_headers += struct.pack('!B', 7)
                value_bytes = value.encode('utf-8')
                encoded_headers += struct.pack('!H', len(value_bytes))
                encoded_headers += value_bytes
            elif isinstance(value, bytes):
                encoded_headers += struct.pack('!B', 6)
                encoded_headers += struct.pack('!H', len(value))
                encoded_headers += value
            elif isinstance(value, bool):
                encoded_headers += struct.pack('!B', 0 if value else 1)
            else:
                raise ValueError(f"Unsupported header value type: {type(value)}")

        return encoded_headers

    @staticmethod
    def marshall_audio_event(audio_chunk):
        headers = {
            ':message-type': 'event',
            ':event-type': 'AudioEvent',
            ':content-type': 'application/octet-stream'
        }

        headers_bytes = EventStreamMarshaller._encode_headers(headers)
        headers_length = len(headers_bytes)

        total_length = 4 + 4 + 4 + headers_length + len(audio_chunk) + 4

        prelude = struct.pack('!I', total_length)
        prelude += struct.pack('!I', headers_length)

        prelude_crc = EventStreamMarshaller._calculate_crc32(prelude)

        message = prelude
        message += struct.pack('!I', prelude_crc)
        message += headers_bytes
        message += audio_chunk

        message_crc = EventStreamMarshaller._calculate_crc32(message)
        message += struct.pack('!I', message_crc)

        return message

    @staticmethod
    def unmarshall_message(data):
        if len(data) < 12:
            return None

        total_length = struct.unpack('!I', data[0:4])[0]
        headers_length = struct.unpack('!I', data[4:8])[0]
        prelude_crc = struct.unpack('!I', data[8:12])[0]

        expected_prelude_crc = EventStreamMarshaller._calculate_crc32(data[0:8])
        if prelude_crc != expected_prelude_crc:
            raise ValueError("Invalid prelude CRC")

        headers_start = 12
        headers_end = headers_start + headers_length
        headers_data = data[headers_start:headers_end]
        headers = EventStreamMarshaller._parse_headers(headers_data)

        payload_start = headers_end
        payload_end = len(data) - 4
        payload = data[payload_start:payload_end]

        message_crc = struct.unpack('!I', data[payload_end:payload_end+4])[0]
        expected_message_crc = EventStreamMarshaller._calculate_crc32(data[0:payload_end])
        if message_crc != expected_message_crc:
            raise ValueError("Invalid message CRC")

        return {'headers': headers, 'payload': payload}

    @staticmethod
    def _parse_headers(headers_data):
        headers = {}
        offset = 0

        while offset < len(headers_data):
            name_length = struct.unpack('!B', headers_data[offset:offset+1])[0]
            offset += 1
            name = headers_data[offset:offset+name_length].decode('utf-8')
            offset += name_length

            value_type = struct.unpack('!B', headers_data[offset:offset+1])[0]
            offset += 1

            if value_type == 7:
                value_length = struct.unpack('!H', headers_data[offset:offset+2])[0]
                offset += 2
                value = headers_data[offset:offset+value_length].decode('utf-8')
                offset += value_length
            elif value_type == 6:
                value_length = struct.unpack('!H', headers_data[offset:offset+2])[0]
                offset += 2
                value = headers_data[offset:offset+value_length]
                offset += value_length
            elif value_type == 0:
                value = True
            elif value_type == 1:
                value = False
            else:
                raise ValueError(f"Unsupported header type: {value_type}")

            headers[name] = value

        return headers

# ----------------------------
# Utility: resample PCM16
# ----------------------------
def resample_pcm16(data, in_rate, out_rate):
    if in_rate == out_rate:
        return data
    duration = data.shape[0] / float(in_rate)
    out_len = int(round(duration * out_rate))
    resampled = np.interp(
        np.linspace(0, duration, out_len, endpoint=False),
        np.linspace(0, duration, data.shape[0], endpoint=False),
        data
    ).astype(np.int16)
    return resampled

# ----------------------------
# Main streaming function
# ----------------------------
async def stream_audio(on_transcript):
    audio_q = asyncio.Queue()
    MIC_DEVICE_INDEX = 0

    session = boto3.session.Session()
    creds = session.get_credentials().get_frozen_credentials()
    service = "transcribe"
    host = f"transcribestreaming.{AWS_REGION}.amazonaws.com:8443"

    def sign_request():
        t = datetime.datetime.utcnow()
        amzdate = t.strftime("%Y%m%dT%H%M%SZ")
        datestamp = t.strftime("%Y%m%d")
        method = "GET"
        canonical_uri = "/stream-transcription-websocket"

        params = {
            'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
            'X-Amz-Credential': f'{creds.access_key}/{datestamp}/{AWS_REGION}/{service}/aws4_request',
            'X-Amz-Date': amzdate,
            'X-Amz-Expires': '300',
            'X-Amz-SignedHeaders': 'host',
            'language-code': LANGUAGE_CODE,
            'media-encoding': 'pcm',
            'sample-rate': str(STREAM_SAMPLE_RATE)
        }

        sorted_params = sorted(params.items())
        canonical_querystring = '&'.join([f'{k}={urllib.parse.quote_plus(str(v))}' for k, v in sorted_params])

        canonical_headers = f"host:{host}\n"
        signed_headers = "host"
        payload_hash = hashlib.sha256(("").encode("utf-8")).hexdigest()

        canonical_request = "\n".join([method, canonical_uri, canonical_querystring,
                                       canonical_headers, signed_headers, payload_hash])

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{AWS_REGION}/{service}/aws4_request"
        string_to_sign = "\n".join([algorithm, amzdate, credential_scope,
                                    hashlib.sha256(canonical_request.encode()).hexdigest()])

        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign(("AWS4" + creds.secret_key).encode(), datestamp)
        k_region = sign(k_date, AWS_REGION)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        base_url = f"wss://{host}{canonical_uri}"
        final_params = dict(params)
        final_params['X-Amz-Signature'] = signature

        sorted_final_params = sorted(final_params.items())
        final_querystring = '&'.join([f'{k}={urllib.parse.quote_plus(str(v))}' for k, v in sorted_final_params])

        return f"{base_url}?{final_querystring}"

    signed_url = sign_request()

    # ----------------------------
    # Sender task
    # ----------------------------
    async def mic_sender(ws):
        try:
            while True:
                chunk = await audio_q.get()
                if chunk is None:
                    if DEBUG: print("[mic_sender] shutdown")
                    break
                marshalled_chunk = EventStreamMarshaller.marshall_audio_event(chunk)
                await ws.send_bytes(marshalled_chunk)
                if DEBUG: print("[mic_sender] sent EventStream chunk len", len(marshalled_chunk))
        except asyncio.CancelledError:
            if DEBUG: print("[mic_sender] cancelled")
            raise

    # ----------------------------
    # Connect to AWS Transcribe
    # ----------------------------
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(signed_url, timeout=10) as ws:
            if DEBUG: print("[transcribe] connected")

            # Capture the main loop here
            loop = asyncio.get_running_loop()

            def callback(indata, frames, time_info, status):
                if status:
                    print("[mic cb] status:", status)
                try:
                    mono = (indata[:, 0] * 32767).astype(np.int16)
                except Exception:
                    mono = (np.asarray(indata).flatten() * 32767).astype(np.int16)

                resampled = resample_pcm16(mono, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE)
                max_chunk_size = 8000

                for i in range(0, len(resampled), max_chunk_size):
                    chunk = resampled[i:i+max_chunk_size]
                    chunk_bytes = chunk.tobytes()
                    asyncio.run_coroutine_threadsafe(audio_q.put(chunk_bytes), loop)

                if DEBUG:
                    print("[mic cb] frames", frames, "resampled len", len(resampled))

            sender_task = asyncio.create_task(mic_sender(ws))

            try:
                dev = sd.query_devices(MIC_DEVICE_INDEX)
                if DEBUG:
                    print("[mic] using device:", dev['name'], "channels:", dev['max_input_channels'], "rate:", MIC_SAMPLE_RATE)

                with sd.InputStream(device=MIC_DEVICE_INDEX,
                                    samplerate=MIC_SAMPLE_RATE,
                                    channels=1,
                                    dtype="float32",
                                    callback=callback,
                                    blocksize=int(MIC_SAMPLE_RATE * FRAME_MS / 1000)):
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            decoded = EventStreamMarshaller.unmarshall_message(msg.data)
                            if decoded['headers'].get(':event-type') == 'TranscriptEvent':
                                transcript_data = json.loads(decoded['payload'].decode('utf-8'))
                                if "Transcript" in transcript_data:
                                    for r in transcript_data["Transcript"]["Results"]:
                                        if not r.get("IsPartial") and r.get("Alternatives"):
                                            text = r["Alternatives"][0]["Transcript"]
                                            ts = datetime.datetime.utcnow().isoformat() + "Z"
                                            await on_transcript(text, ts)
                            elif decoded['headers'].get(':message-type') == 'exception':
                                error_data = json.loads(decoded['payload'].decode('utf-8'))
                                if DEBUG: print("[transcribe] exception:", error_data)
                                break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            if DEBUG: print("[transcribe] ws error", msg)
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            if DEBUG: print("[transcribe] ws closed")
                            break
            finally:
                await audio_q.put(None)
                await asyncio.sleep(0.1)
                if not sender_task.done():
                    sender_task.cancel()
                    try:
                        await sender_task
                    except asyncio.CancelledError:
                        if DEBUG: print("[mic_sender] cancelled on shutdown")
                if DEBUG: print("[transcribe] connection closed")
