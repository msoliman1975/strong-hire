"""AL-7: the optional daily digest, off unless ALERT_DIGEST=true. Sent at ALERT_DIGEST_HOUR_UTC
(default 08:00 UTC) to ALERT_EMAIL: yesterday's key numbers, open alerts and new error groups."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_core.db.models import AlertEvent, AlertRule, ErrorGroup, InterviewSession, UsageEvent
from strong_core.ops.alerts import alerts_url, format_value
from strong_core.schemas.enums import AlertEventKind, AlertState, SessionStatus
from strong_worker.alerts.readings import as_utc


async def build_digest(db: AsyncSession, now: datetime, admin_base_url: str) -> tuple[str, str]:
    """(subject, body) for the 24 h of the previous UTC day."""
    end = datetime.combine(now.astimezone(UTC).date(), time(0), tzinfo=UTC)
    start = end - timedelta(days=1)
    day = start.date().isoformat()

    ended = func.coalesce(InterviewSession.ended_at, InterviewSession.created_at)
    rows = await db.execute(
        select(InterviewSession.status, func.count())
        .where(ended >= start, ended < end)
        .group_by(InterviewSession.status)
    )
    by_status: dict[SessionStatus, int] = {status: n for status, n in rows}
    spend = await db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
            UsageEvent.created_at >= start, UsageEvent.created_at < end
        )
    )
    fired = await db.scalar(
        select(func.count()).where(
            AlertEvent.kind == AlertEventKind.FIRED, AlertEvent.at >= start, AlertEvent.at < end
        )
    )
    open_rules = list(
        await db.scalars(
            select(AlertRule)
            .where(AlertRule.enabled.is_(True), AlertRule.state == AlertState.FIRING)
            .order_by(AlertRule.name)
        )
    )
    new_groups = list(
        await db.scalars(
            select(ErrorGroup)
            .where(ErrorGroup.first_seen >= start, ErrorGroup.first_seen < end)
            .order_by(ErrorGroup.first_seen)
        )
    )

    lines = [
        f"Strong Hire, {day} (UTC)",
        "",
        f"Interviews completed: {by_status.get(SessionStatus.COMPLETED, 0)}",
        f"Interviews failed:    {by_status.get(SessionStatus.FAILED, 0)}",
        f"Model cost:           ${float(spend or 0):.2f}",
        f"Alerts fired:         {fired or 0}",
        "",
        f"Open alerts ({len(open_rules)}):",
        *(
            f"- [{r.severity.value}] {r.name}: {format_value(r.last_value, r.metric)}, since "
            f"{as_utc(r.state_since).strftime('%Y-%m-%d %H:%M UTC') if r.state_since else '-'}"
            for r in open_rules
        ),
        *([] if open_rules else ["- none"]),
        "",
        f"New error groups ({len(new_groups)}):",
        *(f"- {g.service}: {g.exception_type}: {g.message[:120]}" for g in new_groups),
        *([] if new_groups else ["- none"]),
        "",
        f"Alerts: {alerts_url(admin_base_url)}",
    ]
    return f"[Strong Hire] Daily digest {day}", "\n".join(lines) + "\n"
