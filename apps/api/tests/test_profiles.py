"""Company profile validation, import, diff and publish (AD-1).

The lookup and generic fallback tests (IV-5, IN-5) moved to packages/core/tests/test_profiles.py
with the code.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from typer.testing import CliRunner

from strong_api.profiles import cli
from strong_api.profiles import repository as repo
from strong_api.profiles.diff import ChangeKind, diff_profiles, flatten, format_diff
from strong_api.profiles.validation import ProfileFileError, load_profile_file, parse_profile
from strong_core.config import get_settings
from strong_core.db.models import AuditLog, Base, Company
from strong_core.db.models import CompanyProfile as ProfileRow
from strong_core.db.seed import LAUNCH_COMPANIES
from strong_core.profiles import (
    ProfileError,
    get_profile_version,
    get_published_profile,
    row_profile,
)
from strong_core.schemas import ProfileStatus

REPO = get_settings().repo_root
EXAMPLE = REPO / "profiles/examples/example-corp.json"


def example_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def as_google(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    out["company_slug"] = "google"
    out["company_name"] = "Google"
    return out


def write(tmp_path: Path, data: dict[str, Any], name: str = "profile.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- validation -----------------------------------------------------------------------------


def test_ad1_example_profile_is_valid() -> None:
    profile = load_profile_file(EXAMPLE)
    assert profile.company_slug == "example-corp"


def test_ad1_authoring_doc_example_matches_the_file() -> None:
    doc = (REPO / "docs/profile-authoring.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", doc, flags=re.DOTALL)
    assert len(blocks) == 1
    assert json.loads(blocks[0]) == example_data()


def test_ad1_schema_has_sources_and_confidence_per_field() -> None:
    schema = json.loads((REPO / "schemas/company_profile.schema.json").read_text("utf-8"))
    assert {"sources", "field_confidence"} <= set(schema["required"])
    source = schema["$defs"]["Source"]
    assert {"url", "retrieved_at", "fields"} <= set(source["required"])


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda d: d["values_framework"]["principles"][0].update(evidence_signals=[]),
            "values_framework.principles[0].evidence_signals",
        ),
        (lambda d: d["persona"].pop("tone"), "persona.tone: Field required"),
        (lambda d: d["scoring_weights"].update(speed=1.0), "scoring_weights.speed (key)"),
        (lambda d: d["case_style"].update(estimation=1.5), "case_style.estimation"),
        (lambda d: d["field_confidence"].pop("case_style"), "missing: case_style"),
        (lambda d: d["scoring_weights"].update(ownership=0), "must be positive: ownership"),
        (lambda d: d.update(company_slug="Bad Slug"), "company_slug"),
        (
            lambda d: d["question_patterns"][0].update(values=["Move fast"]),
            "question_patterns use unknown values: Move fast",
        ),
        (lambda d: d.update(values_share=0.6), "values_share"),
        (
            lambda d: d["values_framework"]["principles"][1].update(weight=0),
            "values_framework.principles[1].weight",
        ),
        (lambda d: d.update(colour="blue"), "colour: unknown field"),
        (lambda d: d["sources"][0].update(retrieved_at="yesterday"), "sources[0].retrieved_at"),
        (
            lambda d: d["loop_structure"][0]["rounds"][1].update(interview_type="coding"),
            "loop_structure[0].rounds[1].interview_type",
        ),
    ],
)
def test_ad1_invalid_file_names_the_bad_field(tmp_path: Path, mutate: Any, expected: str) -> None:
    data = example_data()
    mutate(data)
    with pytest.raises(ProfileFileError) as err:
        load_profile_file(write(tmp_path, data))
    assert any(expected in p for p in err.value.problems), err.value.problems


def test_ad1_bad_json_and_missing_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"company_name": "x",\n  oops}', encoding="utf-8")
    with pytest.raises(ProfileFileError, match=r"not valid JSON.*line 2"):
        load_profile_file(bad)
    with pytest.raises(ProfileFileError, match="file not found"):
        load_profile_file(tmp_path / "nope.json")


# --- diff -----------------------------------------------------------------------------------


def test_ad1_diff_reports_field_paths_and_ignores_meta() -> None:
    old = example_data()
    new = copy.deepcopy(old)
    new["meta"]["version"] = 7
    new["persona"]["tone"] = "Direct"
    new["question_patterns"].pop()
    new["scoring_weights"]["judgment"] = 1.4
    new["values_share"] = 0.3
    changes = {c.path: c for c in diff_profiles(old, new)}
    assert set(changes) == {
        "persona.tone",
        "scoring_weights.judgment",
        "values_share",
        "question_patterns[4].interview_type",
        "question_patterns[4].theme",
        "question_patterns[4].pattern",
        "question_patterns[4].competencies[0]",
        "question_patterns[4].competencies[1]",
        "question_patterns[4].competencies[2]",
        "question_patterns[4].values[0]",
    }
    assert changes["persona.tone"].kind is ChangeKind.CHANGED
    assert changes["persona.tone"].old == "Friendly and curious"
    assert changes["scoring_weights.judgment"].kind is ChangeKind.ADDED
    assert changes["question_patterns[4].theme"].kind is ChangeKind.REMOVED

    lines = format_diff(list(changes.values()), ["persona", "case_style"])
    assert lines[0] == "persona: 1 change"
    assert lines[1] == '  ~ persona.tone: "Friendly and curious" -> "Direct"'
    assert lines[2] == "case_style: unchanged"


def test_ad1_diff_without_old_version_marks_all_added() -> None:
    new = example_data()
    changes = diff_profiles(None, new)
    assert changes and all(c.kind is ChangeKind.ADDED for c in changes)
    assert len(changes) == len(flatten(new))
    assert diff_profiles(new, copy.deepcopy(new)) == []


# --- repository -----------------------------------------------------------------------------


@pytest.fixture
async def db(sessionmaker: async_sessionmaker[AsyncSession]) -> Any:
    async with sessionmaker() as session:
        yield session


async def _import(db: AsyncSession, data: dict[str, Any], **kw: Any) -> repo.ImportResult:
    result = await repo.import_profile(db, parse_profile(data), actor="tester", **kw)
    await db.commit()
    return result


async def test_ad1_import_stores_draft_versions_and_diffs_against_published(
    db: AsyncSession,
) -> None:
    google = as_google(example_data())
    first = await _import(db, google)
    assert first.version == 1
    assert first.row.status is ProfileStatus.DRAFT
    assert first.published_version is None
    assert first.row.sources_json == google["sources"]
    assert first.row.imported_at is not None

    with pytest.raises(ProfileError, match="same content as version 1"):
        await repo.import_profile(db, parse_profile(google), actor="tester")
    await db.rollback()

    await repo.publish_profile(db, "google", 1, reviewer="mo")
    await db.commit()

    changed = copy.deepcopy(google)
    changed["persona"]["pace"] = "Fast"
    second = await _import(db, changed)
    assert second.version == 2
    assert second.published_version == 1
    assert [c.path for c in second.changes] == ["persona.pace"]

    forced = await _import(db, changed, force=True)
    assert forced.version == 3

    actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.at))).all()
    assert actions.count("profile.import") == 3
    assert actions.count("profile.publish") == 1


async def test_ad1_import_unknown_company_needs_create_company(db: AsyncSession) -> None:
    with pytest.raises(ProfileError, match="'example-corp' is not in the companies table"):
        await repo.import_profile(db, parse_profile(example_data()), actor="tester")
    await db.rollback()

    result = await _import(db, example_data(), create_company=True)
    assert result.company_created
    company = await repo.get_company(db, "example-corp")
    assert company is not None and company.active is False


async def test_ad1_publish_switches_active_version_and_keeps_old_readable(
    db: AsyncSession,
) -> None:
    google = as_google(example_data())
    await _import(db, google)
    v2 = copy.deepcopy(google)
    v2["persona"]["tone"] = "Direct and fast"
    await _import(db, v2)
    company = await repo.require_company(db, "google")

    assert await get_published_profile(db, company.id) is None

    first = await repo.publish_profile(db, "google", 1, reviewer="mo")
    await db.commit()
    assert first.previous_version is None
    published = await get_published_profile(db, company.id)
    assert published is not None and published.version == 1
    assert published.persona.tone == "Friendly and curious"
    assert published.profile is not None
    assert published.profile.meta.status is ProfileStatus.PUBLISHED
    assert published.profile.meta.reviewed_by == "mo"

    second = await repo.publish_profile(db, "google", 2, reviewer="mo")
    await db.commit()
    assert second.previous_version == 1
    published = await get_published_profile(db, company.id)
    assert published is not None and published.version == 2
    assert published.persona.tone == "Direct and fast"

    old = await get_profile_version(db, company.id, 1)
    assert old is not None and old.status is ProfileStatus.ARCHIVED
    assert row_profile(old).persona.tone == "Friendly and curious"

    again = await repo.publish_profile(db, "google", 2, reviewer="mo")
    assert again.already_published

    with pytest.raises(ProfileError, match=r"no version 9. Stored versions: 1, 2"):
        await repo.publish_profile(db, "google", 9, reviewer="mo")

    summary = {c.slug: c for c in await repo.list_companies(db)}
    assert summary["google"].published_version == 2
    assert summary["google"].latest_version == 2
    assert summary["amazon"].version_count == 0


async def test_ad1_publish_keeps_one_published_version_per_company(db: AsyncSession) -> None:
    """Publish archives the old version before it publishes the new one, so the unique index on
    Published rows never fails. Many switches cover both update orders of the two rows."""
    google = as_google(example_data())
    for n in range(1, 7):
        data = copy.deepcopy(google)
        data["persona"]["pace"] = f"Pace {n}"
        await _import(db, data)
    company = await repo.require_company(db, "google")

    for version in [1, 2, 3, 4, 5, 6, 1, 6, 2, 5, 3, 4]:
        await repo.publish_profile(db, "google", version, reviewer="mo")
        await db.commit()
        statuses = (
            await db.scalars(select(ProfileRow.status).where(ProfileRow.company_id == company.id))
        ).all()
        assert statuses.count(ProfileStatus.PUBLISHED) == 1
        published = await get_published_profile(db, company.id)
        assert published is not None and published.version == version


# --- strongctl ------------------------------------------------------------------------------


@pytest.fixture
def cli_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A SQLite file database with the launch companies, used by the CLI commands."""
    path = tmp_path / "cli.db"
    sync = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync)
    with sync.begin() as conn:
        conn.execute(
            Company.__table__.insert(),
            [
                {"id": uuid.uuid4(), "slug": s, "name": n, "active": True}
                for s, n in LAUNCH_COMPANIES
            ],
        )
    sync.dispose()

    def make_engine() -> AsyncEngine:
        return create_async_engine(f"sqlite+aiosqlite:///{path}")

    monkeypatch.setattr(cli, "make_engine", make_engine)
    yield path


def invoke(*args: str) -> Any:
    return CliRunner().invoke(cli.app, list(args))


def test_ad1_cli_validate_ok_and_invalid(tmp_path: Path) -> None:
    ok = invoke("profiles", "validate", str(EXAMPLE))
    assert ok.exit_code == 0, ok.output
    assert "Valid:" in ok.output and "2 principles, values share 0.25" in ok.output

    data = example_data()
    del data["persona"]["tone"]
    bad = invoke("profiles", "validate", str(write(tmp_path, data)))
    assert bad.exit_code == 1
    assert "persona.tone: Field required" in bad.output


def test_ad1_cli_end_to_end_with_fictional_example(cli_db: Path, tmp_path: Path) -> None:
    missing = invoke("profiles", "import", str(EXAMPLE))
    assert missing.exit_code == 1
    assert "--create-company" in missing.output

    first = invoke("profiles", "import", str(EXAMPLE), "--create-company")
    assert first.exit_code == 0, first.output
    assert "Stored example-corp version 1 as Draft." in first.output
    assert "No published version yet" in first.output

    pub = invoke("profiles", "publish", "example-corp", "1", "--yes", "--reviewer", "mo")
    assert pub.exit_code == 0, pub.output
    assert "Published example-corp version 1" in pub.output

    data = example_data()
    data["meta"]["version"] = 2
    data["persona"]["tone"] = "Direct"
    second = invoke("profiles", "import", str(write(tmp_path, data)))
    assert second.exit_code == 0, second.output
    assert "Diff against published version 1:" in second.output
    assert '~ persona.tone: "Friendly and curious" -> "Direct"' in second.output
    assert "values_framework: unchanged" in second.output
    assert "Total: 1 changed values." in second.output

    declined = CliRunner().invoke(
        cli.app, ["profiles", "publish", "example-corp", "2"], input="n\n"
    )
    assert declined.exit_code == 1
    shown = invoke("profiles", "show", "example-corp")
    assert "Showing version 1 (published)" in shown.output

    pub2 = invoke("profiles", "publish", "example-corp", "2", "-y")
    assert pub2.exit_code == 0, pub2.output
    assert "Version 1 is now Archived" in pub2.output

    listed = invoke("profiles", "list")
    assert listed.exit_code == 0
    row = next(line for line in listed.output.splitlines() if line.startswith("example-corp"))
    assert row.split()[-4:] == ["2", "2", "2", "no"]
    assert len([ln for ln in listed.output.splitlines()[1:] if ln.strip()]) == 21

    old = invoke("profiles", "show", "example-corp", "--version", "1", "--json")
    assert old.exit_code == 0, old.output
    old_json = json.loads(old.output)
    assert old_json["persona"]["tone"] == "Friendly and curious"
    assert old_json["meta"]["status"] == "archived"

    shown = invoke("profiles", "show", "example-corp")
    assert "v1: archived" in shown.output and "v2: published" in shown.output

    unknown = invoke("profiles", "publish", "example-corp", "5", "-y")
    assert unknown.exit_code == 1 and "no version 5" in unknown.output


def test_ad1_cli_import_rejects_invalid_file_before_database(cli_db: Path, tmp_path: Path) -> None:
    data = as_google(example_data())
    data["case_style"]["estimation"] = 2
    result = invoke("profiles", "import", str(write(tmp_path, data)))
    assert result.exit_code == 1
    assert "case_style.estimation" in result.output

    sync = create_engine(f"sqlite:///{cli_db}")
    with sync.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(ProfileRow)) == 0
    sync.dispose()


def test_launch_companies_are_the_20_from_the_spec() -> None:
    slugs = [slug for slug, _ in LAUNCH_COMPANIES]
    assert len(slugs) == len(set(slugs)) == 20
    assert "atlassian" in slugs and "ebay" not in slugs
