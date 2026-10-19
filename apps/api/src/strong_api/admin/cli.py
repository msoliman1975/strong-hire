"""`strongctl admin`: manage who may use the admin app (AA-1).

    uv run strongctl admin list
    uv run strongctl admin add someone@example.com
    uv run strongctl admin remove someone@example.com    # also ends their sessions (AA-8)

Removing keeps the row with `disabled_at` set, so the history stays and ADMIN_EMAILS never
seeds the table again. `add` turns a removed admin back on. Each change writes an audit row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strong_api.admin.identity import add_admin, disable_admin, find_admin, utcnow
from strong_core.db.models import AdminUser as AdminUserRow
from strong_core.db.models import AuditLog

admin_app = typer.Typer(help="Admins of the admin app: list, add, remove.", no_args_is_help=True)

CLI_ACTOR = "strongctl"


def _actor() -> str:
    from strong_api.profiles import cli

    return f"{CLI_ACTOR}:{cli.default_actor()}"


def _run[T](action: Callable[[AsyncSession], Awaitable[T]], *, commit: bool = False) -> T:
    # Late import: strong_api.profiles.cli registers this app, and its tests swap make_engine.
    from strong_api.profiles import cli

    return cli.run_db(action, commit=commit)


def _audit(db: AsyncSession, action: str, row: AdminUserRow, details: dict[str, object]) -> None:
    db.add(
        AuditLog(
            org_id=None,
            actor=_actor(),
            action=action,
            entity=f"admin_user:{row.id}",
            details_json={"email": row.email, **details},
        )
    )


@admin_app.command("list")
def list_cmd() -> None:
    """Every admin: active ones first, then removed ones."""

    async def _load(db: AsyncSession) -> list[AdminUserRow]:
        return list(await db.scalars(select(AdminUserRow).order_by(AdminUserRow.email)))

    rows = _run(_load)
    if not rows:
        typer.echo("No admins. The API seeds them from ADMIN_EMAILS on its first start.")
        return
    for row in sorted(rows, key=lambda r: (r.disabled_at is not None, r.email)):
        state = "active" if row.disabled_at is None else f"removed {row.disabled_at:%Y-%m-%d}"
        typer.echo(f"{row.email}  {state}  added by {row.added_by or '-'}")


@admin_app.command("add")
def add_cmd(email: Annotated[str, typer.Argument(help="The admin's email.")]) -> None:
    """Add an admin, or turn a removed one back on."""
    if "@" not in email:
        typer.secho("Not an email address.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    async def _add(db: AsyncSession) -> bool:
        row, changed = await add_admin(db, email, added_by=CLI_ACTOR)
        if changed:
            _audit(db, "admin.admin_added", row, {"reason": "strongctl admin add"})
        return changed

    if _run(_add, commit=True):
        typer.secho(f"Added admin {email.strip().lower()}", fg=typer.colors.GREEN)
    else:
        typer.echo(f"{email.strip().lower()} is already an admin.")


@admin_app.command("remove")
def remove_cmd(email: Annotated[str, typer.Argument(help="The admin's email.")]) -> None:
    """Remove an admin. They cannot sign in again, and their sessions end now."""

    async def _remove(db: AsyncSession) -> int | None:
        row = await find_admin(db, email)
        if row is None or row.disabled_at is not None:
            return None
        revoked = await disable_admin(db, row, utcnow())
        _audit(
            db,
            "admin.admin_removed",
            row,
            {"reason": "strongctl admin remove", "sessions_revoked": revoked},
        )
        return revoked

    revoked = _run(_remove, commit=True)
    if revoked is None:
        typer.secho(
            f"{email.strip().lower()} is not an active admin.", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)
    typer.secho(
        f"Removed admin {email.strip().lower()}; {revoked} session(s) ended.",
        fg=typer.colors.GREEN,
    )
