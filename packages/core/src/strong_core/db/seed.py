"""Seed reference data: the 20 launch companies (spec, Scope section). Safe to run twice.

uv run python -m strong_core.db.seed
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from strong_core.config import get_settings
from strong_core.db.models import Company

LAUNCH_COMPANIES: tuple[tuple[str, str], ...] = (
    ("google", "Google"),
    ("amazon", "Amazon"),
    ("microsoft", "Microsoft"),
    ("meta", "Meta"),
    ("apple", "Apple"),
    ("netflix", "Netflix"),
    ("nvidia", "Nvidia"),
    ("salesforce", "Salesforce"),
    ("uber", "Uber"),
    ("stripe", "Stripe"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("airbnb", "Airbnb"),
    ("shopify", "Shopify"),
    ("linkedin", "LinkedIn"),
    ("oracle", "Oracle"),
    ("adobe", "Adobe"),
    ("databricks", "Databricks"),
    ("snowflake", "Snowflake"),
    ("atlassian", "Atlassian"),
)


def seed(db: Session) -> int:
    existing = set(db.scalars(select(Company.slug)))
    added = 0
    for slug, name in LAUNCH_COMPANIES:
        if slug not in existing:
            db.add(Company(slug=slug, name=name, active=True))
            added += 1
    db.commit()
    return added


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with Session(engine) as db:
        added = seed(db)
    print(f"Seed done: {added} companies added, {len(LAUNCH_COMPANIES) - added} already present.")


if __name__ == "__main__":
    main()
