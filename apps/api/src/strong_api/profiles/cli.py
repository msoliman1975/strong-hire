"""strongctl: admin command line for company profiles (AD-1).

    uv run strongctl profiles validate profiles/examples/example-corp.json
    uv run strongctl profiles import profiles/google.json
    uv run strongctl profiles publish google 2
    uv run strongctl profiles list
    uv run strongctl profiles show google [--version 1] [--json]

The commands use DATABASE_URL (default: the local Docker Postgres on port 55432).
"""

from __future__ import annotations

import asyncio
import getpass
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from strong_api.profiles import repository as repo
from strong_api.profiles.diff import format_diff
from strong_api.profiles.validation import ProfileFileError, load_profile_file
from strong_core.config import get_settings
from strong_core.db.engine import async_database_url
from strong_core.profiles import ProfileError, get_profile_version, get_published_row
from strong_core.schemas import CompanyProfile, Confidence

app = typer.Typer(help="Strong Hire admin commands.", no_args_is_help=True)
profiles_app = typer.Typer(
    help="Company profiles: validate, import, publish.", no_args_is_help=True
)
app.add_typer(profiles_app, name="profiles")

DIFF_FIELDS = [name for name in CompanyProfile.model_fields if name != "meta"]


def make_engine() -> AsyncEngine:
    """Tests replace this to point the commands at a test database."""
    return _create_async_engine(async_database_url(get_settings().database_url))


def run_db[T](action: Callable[[AsyncSession], Awaitable[T]], *, commit: bool = False) -> T:
    async def _run() -> T:
        engine = make_engine()
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                result = await action(db)
                if commit:
                    await db.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def fail(message: str) -> typer.Exit:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


def default_actor() -> str:
    try:
        return getpass.getuser()
    except Exception:  # getuser raises different errors per platform when no name is set
        return "unknown"


def load_or_exit(path: Path) -> CompanyProfile:
    try:
        return load_profile_file(path)
    except ProfileFileError as exc:
        typer.secho(f"Invalid profile file: {path}", fg=typer.colors.RED, err=True)
        for problem in exc.problems:
            typer.secho(f"  - {problem}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def summary_lines(profile: CompanyProfile) -> list[str]:
    low = [f.value for f, c in profile.field_confidence.items() if c is Confidence.LOW]
    return [
        f"Company: {profile.company_name} ({profile.company_slug})",
        f"Values framework: {profile.values_framework.name}, "
        f"{len(profile.values_framework.principles)} principles, values share "
        f"{profile.values_share:g}",
        f"Loops: {len(profile.loop_structure)}, question patterns: "
        f"{len(profile.question_patterns)}, levels: {len(profile.bar_by_level)}",
        f"Scoring weights: {len(profile.scoring_weights)} competencies, sources: "
        f"{len(profile.sources)}",
        "Low-confidence fields: " + (", ".join(low) if low else "none"),
    ]


@profiles_app.command("validate")
def validate_cmd(
    file: Annotated[Path, typer.Argument(help="Profile JSON file.")],
) -> None:
    """Check a profile file against the CompanyProfile schema. Does not use the database."""
    profile = load_or_exit(file)
    typer.secho(f"Valid: {file}", fg=typer.colors.GREEN)
    for line in summary_lines(profile):
        typer.echo(f"  {line}")


@profiles_app.command("import")
def import_cmd(
    file: Annotated[Path, typer.Argument(help="Profile JSON file.")],
    create_company: Annotated[
        bool,
        typer.Option(
            "--create-company",
            help="Add the company (inactive) if it is not in the companies table.",
        ),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Store a new version even if nothing changed.")
    ] = False,
) -> None:
    """Validate a file, store it as a new Draft version, and show the diff to the published one."""
    profile = load_or_exit(file)
    actor = default_actor()
    try:
        result = run_db(
            lambda db: repo.import_profile(
                db, profile, actor=actor, create_company=create_company, force=force
            ),
            commit=True,
        )
    except ProfileError as exc:
        raise fail(str(exc)) from exc

    slug = result.company.slug
    if result.company_created:
        typer.echo(f"Added company '{slug}' (inactive, so job matching does not use it).")
    typer.secho(f"Stored {slug} version {result.version} as Draft.", fg=typer.colors.GREEN)
    if result.file_version != result.version:
        typer.echo(
            f"Note: the file says meta.version {result.file_version}. "
            f"The database assigns version numbers, so it is version {result.version}."
        )
    if result.published_version is None:
        typer.echo("No published version yet. Every field is new:")
    else:
        typer.echo(f"Diff against published version {result.published_version}:")
    for line in format_diff(result.changes, DIFF_FIELDS):
        typer.echo(f"  {line}")
    typer.echo(f"Total: {len(result.changes)} changed values.")
    typer.echo(f"After review, publish with: strongctl profiles publish {slug} {result.version}")


@profiles_app.command("publish")
def publish_cmd(
    company: Annotated[str, typer.Argument(help="Company slug, for example 'google'.")],
    version: Annotated[int, typer.Argument(help="Version number to publish.")],
    reviewer: Annotated[
        str | None, typer.Option(help="Reviewer name stored with the version.")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask to confirm.")] = False,
) -> None:
    """Make a version the active profile. The version published before becomes Archived."""
    if not yes:
        typer.confirm(f"Publish {company} version {version}? New sessions will use it.", abort=True)
    who = reviewer or default_actor()
    try:
        result = run_db(
            lambda db: repo.publish_profile(db, company, version, reviewer=who), commit=True
        )
    except (ProfileError, ProfileFileError) as exc:
        raise fail(str(exc)) from exc
    if result.already_published:
        typer.echo(f"{company} version {version} is already the published version.")
        return
    typer.secho(f"Published {company} version {version} (reviewer: {who}).", fg=typer.colors.GREEN)
    if result.previous_version is not None:
        typer.echo(f"Version {result.previous_version} is now Archived. It stays readable.")


@profiles_app.command("list")
def list_cmd() -> None:
    """List companies with their published and latest profile versions."""
    companies = run_db(repo.list_companies)
    if not companies:
        typer.echo("No companies. Run the seed first: python -m strong_core.db.seed")
        return
    typer.echo(f"{'slug':<16} {'name':<20} {'published':>9} {'latest':>6} {'versions':>8}  active")
    for c in companies:
        published = str(c.published_version) if c.published_version else "-"
        latest = str(c.latest_version) if c.latest_version else "-"
        typer.echo(
            f"{c.slug:<16} {c.name:<20} {published:>9} {latest:>6} {c.version_count:>8}  "
            f"{'yes' if c.active else 'no'}"
        )


@profiles_app.command("show")
def show_cmd(
    company: Annotated[str, typer.Argument(help="Company slug.")],
    version: Annotated[
        int | None, typer.Option(help="Version to show. Default: the published version.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the stored JSON.")] = False,
) -> None:
    """Show one company's profile versions and the content of one version."""

    async def _load(db: AsyncSession) -> tuple[list[str], dict[str, object] | None, str]:
        found = await repo.require_company(db, company)
        rows = await repo.list_versions(db, found.id)
        lines = [
            f"  v{r.version}: {r.status.value}, imported {r.imported_at:%Y-%m-%d %H:%M}"
            + (f", published {r.published_at:%Y-%m-%d %H:%M}" if r.published_at else "")
            + (f", reviewer {r.reviewed_by}" if r.reviewed_by else "")
            for r in rows
        ]
        if version is not None:
            row = await get_profile_version(db, found.id, version)
            if row is None:
                raise ProfileError(f"'{company}' has no version {version}.")
        else:
            row = await get_published_row(db, found.id)
        label = f"version {row.version} ({row.status.value})" if row else "no published version"
        return lines, (row.profile_json if row else None), label

    try:
        lines, data, label = run_db(_load)
    except ProfileError as exc:
        raise fail(str(exc)) from exc
    if as_json:
        if data is None:
            raise fail(f"'{company}' has no published version. Pass --version.")
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    typer.echo(f"{company}: {len(lines)} stored versions")
    for line in lines:
        typer.echo(line)
    typer.echo(f"Showing {label}:")
    if data is not None:
        for line in summary_lines(CompanyProfile.model_validate(data)):
            typer.echo(f"  {line}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
