"""The ops_samples metric catalog (admin spec OB-5, OB-6). Fixed: the sampler writes these
names and labels, the Health page and the alert engine read them.

    metric                labels               value
    probe.up              {dep}                1 up, 0 down
    probe.latency_ms      {dep}                probe time in ms (written when the probe ran)
    heartbeat.up          {service}            1 when a live heartbeat:<service>:* key exists
    queue.depth           {queue}              jobs waiting in the Arq queue
    sessions.in_progress  -                    sessions with status in_progress
    host.disk_pct         {mount}              used % of the root or Postgres data file system
    host.mem_pct          -                    (MemTotal - MemAvailable) / MemTotal, in %
    host.load1            -                    1-minute load average
    db.size_bytes         -                    pg_database_size of the app database
    redis.mem_bytes       -                    used_memory from Redis INFO memory
    stripe.webhook_age_s  -                    seconds since the last Stripe webhook

Derived metrics (sessions.failure_rate, voice.e2e_p95_ms, sessions.scoring_stuck,
spend.today_usd, spend.cap_pct, errors.new_groups) are computed from domain tables by their
readers, not sampled.
"""

from __future__ import annotations

PROBE_UP = "probe.up"
PROBE_LATENCY_MS = "probe.latency_ms"
HEARTBEAT_UP = "heartbeat.up"
QUEUE_DEPTH = "queue.depth"
SESSIONS_IN_PROGRESS = "sessions.in_progress"
HOST_DISK_PCT = "host.disk_pct"
HOST_MEM_PCT = "host.mem_pct"
HOST_LOAD1 = "host.load1"
DB_SIZE_BYTES = "db.size_bytes"
REDIS_MEM_BYTES = "redis.mem_bytes"
STRIPE_WEBHOOK_AGE_S = "stripe.webhook_age_s"

SAMPLED_METRICS = (
    PROBE_UP,
    PROBE_LATENCY_MS,
    HEARTBEAT_UP,
    QUEUE_DEPTH,
    SESSIONS_IN_PROGRESS,
    HOST_DISK_PCT,
    HOST_MEM_PCT,
    HOST_LOAD1,
    DB_SIZE_BYTES,
    REDIS_MEM_BYTES,
    STRIPE_WEBHOOK_AGE_S,
)

# Label values.
PROBE_DEPS = ("postgres", "redis", "litellm", "livekit", "stt", "tts", "smtp")
HEARTBEAT_SERVICES = ("api", "worker", "voice")
DISK_MOUNTS = ("root", "pgdata")
