import asyncio, json, datetime, hmac, hashlib
import aiohttp, sounddevice as sd, numpy as np
from config import AWS_REGION, LANGUAGE_CODE, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE, FRAME_MS, DEBUG
import boto3

def resample_pcm16(data, in_rate, out_rate):
    if in_rate == out_rate: return data
    duration = data.shape[0] / float(in_rate)
    out_len = int(round(duration * out_rate))
    resampled = np.interp(
        np.linspace(0, duration, out_len, endpoint=False),
        np.linspace(0, duration, data.shape[0], endpoint=False),
        data).astype(np.int16)
    return resampled

async def stream_audio(on_transcript):
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

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(signed_url, timeout=10) as ws:
            if DEBUG: print("[transcribe] connected")
            # start mic
            def callback(indata, frames, time_info, status):
                mono = (indata[:,0] * 32767).astype(np.int16)
                resampled = resample_pcm16(mono, MIC_SAMPLE_RATE, STREAM_SAMPLE_RATE)
                ws.send_bytes(resampled.tobytes())

            with sd.InputStream(samplerate=MIC_SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if "Transcript" in data:
                            for r in data["Transcript"]["Results"]:
                                if not r["IsPartial"] and r["Alternatives"]:
                                    text = r["Alternatives"][0]["Transcript"]
                                    ts = datetime.datetime.utcnow().isoformat() + "Z"
                                    await on_transcript(text, ts)
