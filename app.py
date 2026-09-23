from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import edge_tts
import asyncio
import io
import tempfile
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

async def get_voices():
    return await edge_tts.list_voices()

@app.get("/api/voices")
def voices():
    try:
        data = asyncio.run(get_voices())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

async def synthesize(text, voice, rate, pitch, volume):
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        pitch=pitch,
        volume=volume
    )
    audio = bytearray()
    subtitles = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            subtitles.append(chunk)
    return bytes(audio), subtitles

def make_srt(boundaries):
    def ts(seconds):
        ms = int(round(seconds * 1000))
        h = ms // 3600000
        ms %= 3600000
        m = ms // 60000
        ms %= 60000
        s = ms // 1000
        ms %= 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines=[]
    for i,b in enumerate(boundaries,1):
        # Edge TTS offsets are 100-nanosecond units.
        start = b.get("offset",0) / 10_000_000
        duration = b.get("duration",0) / 10_000_000
        end = start + duration
        word = b.get("text","").strip()
        if not word:
            continue
        lines += [str(i), f"{ts(start)} --> {ts(end)}", word, ""]
    return "\n".join(lines)

@app.post("/api/synthesize")
def synthesize_api():
    data=request.get_json(silent=True) or {}
    text=data.get("text","").strip()
    voice=data.get("voice","")
    rate=data.get("rate","+0%")
    pitch=data.get("pitch","+0Hz")
    volume=data.get("volume","+0%")
    want_srt=bool(data.get("srt", True))

    if not text:
        return jsonify({"error":"Text is required."}),400
    if not voice:
        return jsonify({"error":"Voice is required."}),400
    if len(text) > 20000:
        return jsonify({"error":"Maximum 20,000 characters per request."}),400

    try:
        audio, boundaries=asyncio.run(
            synthesize(text, voice, rate, pitch, volume)
        )
        if not audio:
            return jsonify({"error":"No audio was returned by Edge TTS."}),502

        srt=make_srt(boundaries) if want_srt else ""
        import base64
        return jsonify({
            "audio_base64": base64.b64encode(audio).decode("ascii"),
            "audio_mime": "audio/mpeg",
            "srt": srt,
            "voice": voice
        })
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.get("/health")
def health():
    return jsonify({"ok":True,"service":"Blogger Edge TTS Backend"})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
