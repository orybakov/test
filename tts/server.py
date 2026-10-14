"""Optional single-GPU Qwen3 TTS worker, loaded only with the Compose qwen profile."""
import io
import os
from contextlib import asynccontextmanager

import soundfile as sf
import torch
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

model = None


@asynccontextmanager
async def lifespan(app):
    global model
    model = Qwen3TTSModel.from_pretrained(
        os.environ.get("QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"),
        device_map="cuda:0", dtype=torch.float16, attn_implementation="sdpa")
    yield
    model = None


app = FastAPI(lifespan=lifespan)


class Request(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    voice: str = Field(default="Ryan", max_length=64)


@app.get("/health")
def health():
    return {"ok": model is not None}


@app.post("/synthesize")
def synthesize(req: Request):
    speakers = model.get_supported_speakers()
    if speakers and req.voice.lower() not in speakers:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Unsupported speaker; choose one of {speakers}")
    with torch.inference_mode():
        waves, sample_rate = model.generate_custom_voice(
            text=req.text, language="Russian", speaker=req.voice, non_streaming_mode=True)
    buffer = io.BytesIO()
    sf.write(buffer, waves[0], sample_rate, format="WAV", subtype="PCM_16")
    return Response(buffer.getvalue(), media_type="audio/wav")
