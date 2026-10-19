"""Operations plumbing shared by api, worker and voice (admin spec OB-1..OB-7).

logs       JSON or text log lines with service, request_id and session_id (OB-7)
heartbeat  heartbeat:<service>:<instance> keys in Redis every 15 s (OB-1)
errors     a logging handler that groups ERROR records into error_groups/error_events (OB-4)
metrics    the ops_samples metric catalog (OB-5, OB-6); the worker sampler writes it
costs      hosted-equivalent speech cost and server share per session (D-12, OB-15)
runtime    start_ops / OpsRuntime: what each service starts at boot and stops at shutdown
alerts     the alert engine's shared rules and evaluation (AL-1..AL-7)
"""
