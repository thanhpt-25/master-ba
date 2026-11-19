import datetime as dt

import pytest

from masterba.change import approve_dr, auto_propagates, new_dr
from masterba.models.enums import DrTrigger, PropagationMode
from masterba.trace_store import ProjectStore, get_config, set_config


def mode(store: ProjectStore, value: PropagationMode) -> None:
    set_config(store, get_config(store).model_copy(update={"propagation_mode": value}))


def approved(store: ProjectStore, trigger: DrTrigger, item: str):  # type: ignore[no-untyped-def]
    dr = new_dr(store, trigger, "Change.", [item], dt.date.today)
    return approve_dr(store, dr.id, "Ms. Sato", "Go")[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(PropagationMode.AUTO, True), (PropagationMode.MANUAL_GATE, False)],
)
def test_only_auto_mode_propagates(
    chain: ProjectStore, value: PropagationMode, expected: bool
) -> None:
    mode(chain, value)
    assert (
        auto_propagates(chain, approved(chain, DrTrigger.REQUIREMENT_CHANGE, "REQ-0002"))
        is expected
    )


def test_a_review_feedback_dr_is_left_to_the_review_flow(chain: ProjectStore) -> None:
    mode(chain, PropagationMode.AUTO)
    dr = approved(chain, DrTrigger.REVIEW_FEEDBACK, "REQ-0002")
    assert auto_propagates(chain, dr) is False


def test_a_dr_without_affected_documents_is_not_propagated(chain: ProjectStore) -> None:
    mode(chain, PropagationMode.AUTO)
    dr = new_dr(chain, DrTrigger.CLARIFICATION, "Q-0001: x", [], dt.date.today)
    dr, _ = approve_dr(chain, dr.id, "Ms. Sato", "Go")
    assert not dr.affected_documents
    assert auto_propagates(chain, dr) is False
