"""Speech-to-text service: faster-whisper on CPU behind an OpenAI-compatible API.

    GET  /health
    POST /v1/audio/transcriptions   multipart: file, model, [language], [response_format]

The `model` field names the faster-whisper model to load. LiteLLM sends the id from
config/litellm.<profile>.yaml, so no model name is fixed here. Models load on first use and stay
in memory. STT_DEVICE (cpu), STT_COMPUTE_TYPE (int8) and STT_CPU_THREADS tune inference.
"""

from __future__ import annotations

import io
import os
import threading
import time
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from faster_whisper import WhisperModel

DEVICE = os.environ.get("STT_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("STT_COMPUTE_TYPE", "int8")
CPU_THREADS = int(os.environ.get("STT_CPU_THREADS", "4"))

app = FastAPI(title="stt")
_models: dict[str, WhisperModel] = {}
_lock = threading.Lock()


def _model(name: str) -> WhisperModel:
    with _lock:
        if name not in _models:
            _models[name] = WhisperModel(
                name, device=DEVICE, compute_type=COMPUTE_TYPE, cpu_threads=CPU_THREADS
            )
        return _models[name]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "loaded": sorted(_models), "compute_type": COMPUTE_TYPE}


@app.post("/v1/audio/transcriptions", response_model=None)
def transcribe(
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()],
    language: Annotated[str | None, Form()] = None,
    response_format: Annotated[str, Form()] = "json",
) -> dict[str, Any] | PlainTextResponse:
    if not model.strip():
        raise HTTPException(400, "model must name a faster-whisper model")
    audio = io.BytesIO(file.file.read())
    start = time.perf_counter()
    segments, info = _model(model).transcribe(
        audio, language=language or None, beam_size=1, vad_filter=False
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    if response_format == "text":
        return PlainTextResponse(text)
    return {"text": text, "language": info.language, "duration": info.duration, "ms": elapsed_ms}
