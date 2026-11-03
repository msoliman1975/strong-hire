"""SC-15 (CO-9, D-6): Strova may reword, but never adds a fact. The check is on facts, not
wording: numbers, names and tools, and a hedged number made exact."""

from __future__ import annotations

import pytest

from strong_api.coach import craft, engine
from strong_api.coach.facts import new_facts
from strong_core.schemas import CraftReply, SlotStatus, StoryOutline, StorySection, StoryStyle


def said(*texts: str) -> str:
    return "\n".join(engine.normal(t) for t in texts)


USER = (
    "At Acme I moved checkout to PostgreSQL. It took between 30 and 40 days, and about 25 "
    "engineers were blocked. Errors went from 2% to 0.3%."
)


@pytest.mark.parametrize(
    "text",
    [
        "I moved checkout at Acme to PostgreSQL.",  # reworded, same facts
        "Errors fell from 2% to 0.3%.",
        "About 25 engineers were blocked.",  # the hedge kept
        "It took between 30 and 40 days.",  # the range kept
        "The **move** to PostgreSQL took a while.",  # formatting is not a fact
    ],
)
def test_sc15_rewording_with_the_users_facts_passes(text: str) -> None:
    """SC-15: wording is free when every fact is the user's."""
    assert new_facts(text, said(USER)) == []


@pytest.mark.parametrize(
    ("text", "fact"),
    [
        ("It took 35 days.", "number 35"),  # a point inside the user's range
        ("Errors fell by 85%.", "number 85"),  # a computed result the user never said
        ("25 engineers were blocked.", "25 made exact"),  # "about 25" made exact
        ("I moved checkout to Kafka.", "name Kafka"),  # a tool the user never named
        ("I worked with the Stripe team.", "name Stripe"),  # a proper noun
        ("We ran it on K8s.", "name K8s"),  # a tool with a digit inside
    ],
)
def test_sc15_a_new_fact_is_caught(text: str, fact: str) -> None:
    """SC-15: tempting cases: a number in a range, a computed result, a hedge dropped, a name or
    tool the user never said."""
    found = new_facts(text, said(USER))
    assert any(f.startswith(fact) for f in found), found


def test_sc15_a_craft_turn_drops_an_update_with_a_new_fact() -> None:
    """SC-15, SC-6: an update whose quotes are real but whose text adds a tool is dropped."""
    reply = CraftReply.model_validate(
        {
            "message": "What was the problem?",
            "slot_updates": [
                {
                    "section": "situation",
                    "slot": "role",
                    "text": "At Acme I moved checkout to Kafka.",
                    "quotes": ["At Acme I moved checkout"],
                },
                {
                    "section": "situation",
                    "slot": "org",
                    "text": "Acme.",
                    "quotes": ["At Acme I moved checkout"],
                },
            ],
        }
    )
    applied = craft.apply(StoryOutline.empty(StoryStyle.STAR), reply, said(USER))
    situation = applied.outline.section(StorySection.SITUATION)
    assert situation.slot("role").status == SlotStatus.EMPTY
    assert situation.slot("org").status == SlotStatus.FILLED
    assert any("name Kafka" in d for d in applied.dropped)
