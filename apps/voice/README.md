# Voice agent (P1 spike)

A LiveKit Agents worker that joins every new room and runs a fixed two-question interview.
It exists to prove the voice loop and measure latency. The real interviewer is P7.

## Pipeline

1. Silero VAD finds speech. The LiveKit turn detector decides when the candidate's turn ends.
2. The final speech segment goes to the gateway's `stt` role (`transcribe`).
3. The `interviewer` role streams its reply (`stream`).
4. Each complete sentence goes to the `tts` role (`synthesize_stream`, raw PCM), so audio
   starts before the reply is finished.
5. Barge-in: when the candidate talks over the agent, the agent stops speaking.

All three model calls go through `strong_core.gateway`. `MODEL_PROFILE` alone decides which
models answer. The adapters are in `src/strong_voice/plugins.py`.

## Run it locally

```powershell
./scripts/models.ps1 pull                 # once: pulls the Ollama models named in config/
# in .env: MODEL_PROFILE=local and LITELLM_PROFILE=local
./scripts/dev.ps1 up -Profile all
```

Open <http://localhost:8081>, select **Join**, allow the microphone, and answer the two
questions. The page is a bare test page, not the product web app.

Expect 2 to 4 seconds per turn on CPU with the local profile.

## Latency

The worker writes one row per turn to `var/latency/<profile>.csv` and logs the p50 and p95
when a room closes. Columns, in milliseconds:

| Column | Meaning |
| --- | --- |
| `total_ms` | End of the candidate's speech to the agent's first audio out |
| `turn_detection_ms` | Wait for the turn decision after the transcript is ready |
| `stt_ms` | End of speech to final transcript |
| `llm_ttft_ms` | Interviewer request to first token |
| `tts_ttfb_ms` | First sentence sent to TTS to first audio chunk |
| `other_ms` | The rest: queues and audio buffers |

To compare both profiles with a simulated candidate (no microphone needed):

```powershell
./scripts/latency.ps1                     # local and hosted, 5 sessions (10 turns) each
uv run python -m strong_voice.latency report var/latency/local.csv var/latency/hosted.csv
```

The hosted profile needs `HOSTED_API_KEY` in `.env`; the script skips it otherwise.
The phase 1 gate is a hosted p50 `total_ms` under 1000 ms.

## Settings

Environment variables (see `src/strong_voice/settings.py`):

| Variable | Default | Effect |
| --- | --- | --- |
| `VAD_MIN_SILENCE_S` | 0.35 | Silence before VAD reports end of speech |
| `ENDPOINTING_MIN_DELAY_S` | 0.2 | Shortest wait before the turn ends |
| `ENDPOINTING_MAX_DELAY_S` | 2.5 | Longest wait when the turn detector expects more speech |
| `INTERRUPTION_MIN_DURATION_S` | 0.4 | Speech needed to interrupt the agent |
| `LATENCY_DIR` | `var/latency` | Where the CSV files go |
