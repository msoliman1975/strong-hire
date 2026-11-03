"""Deep story crafting evals (SC-15, SC-4, SC-5, SC-9) on the fake profile, in CI."""

from __future__ import annotations

import asyncio

from strong_core.gateway import ModelGateway
from strong_core.gateway.registry import fake_models_config
from strong_evals import crafting
from strong_evals.suites import load_suite


def _results() -> list[crafting.CraftingResult]:
    gateway = ModelGateway(fake_models_config())

    async def run() -> list[crafting.CraftingResult]:
        return [await crafting.run_case(c, gateway) for c in crafting.load_cases()]

    return asyncio.run(run())


def test_sc15_crafting_adds_no_fact_on_every_case() -> None:
    """SC-15: every no-new-facts case is kept or dropped as expected, and nothing kept carries a
    fact the user never gave; the tempting cases (range, hedge, tool, name) are all dropped."""
    results = _results()
    assert all(r.error is None for r in results), [r.error for r in results]
    assert crafting.invented_facts(results) == 0
    tempting = {r.case.id: r.outcome for r in results if r.case.id.endswith("-rejected")}
    assert tempting and set(tempting.values()) == {"rejected"}
    kinds = {r.case.kind for r in results}
    assert {"craft_turn", "improve", "organize", "rewrite", "flow"} <= kinds


def test_sc4_sc5_depth_suite_finds_no_violation() -> None:
    """SC-4, SC-5: scripted STAR and CARL sessions ask every context slot, never return to a
    skipped slot, and move on without going back."""
    assert crafting.depth_violations() == []


def test_sc9_flow_suite_finds_each_type_and_none_on_a_coherent_story() -> None:
    """SC-9: the seeded incoherent story keeps all five flag types; the coherent one gets none."""
    assert crafting.flow_recall(_results()) == 1.0


def test_crafting_suite_is_in_full() -> None:
    assert load_suite("crafting").crafting and load_suite("full").crafting
