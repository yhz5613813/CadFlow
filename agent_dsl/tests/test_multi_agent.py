from __future__ import annotations

import math
from pathlib import Path

import pytest

import cadflow as cad
from agent_dsl import ModelStore, MultiAgentStore


def _stores(path: Path) -> tuple[ModelStore, MultiAgentStore]:
    models = ModelStore(path / "models")
    models.open("shared", create=True)
    return models, MultiAgentStore(models)


def test_agents_communicate_and_merge_dependency_graph_atomically(tmp_path: Path):
    models, collaboration = _stores(tmp_path)
    base = collaboration.submit_proposal(
        "shared",
        "body_agent",
        "box base 10 10 4",
        base_revision=0,
        proposal_id="body",
    )
    hole = collaboration.submit_proposal(
        "shared",
        "hole_agent",
        "cylinder hole 1 6 at 0 0 -1",
        base_revision=0,
        proposal_id="hole",
    )
    finish = collaboration.submit_proposal(
        "shared",
        "boolean_agent",
        "cut final base hole\nresult final",
        base_revision=0,
        proposal_id="finish",
        depends_on=(base.proposal_id, hole.proposal_id),
    )

    message = collaboration.send_message(
        "shared",
        "boolean_agent",
        "artifact_ready",
        {"shape": "final", "dependencies": ["body", "hole"]},
        recipient="review_agent",
        proposal_id=finish.proposal_id,
        message_id="ready",
    )
    assert message.sequence == 0
    assert collaboration.messages("shared", recipient="review_agent") == (message,)

    merged = collaboration.merge(
        "shared",
        (finish.proposal_id, hole.proposal_id, base.proposal_id),
        expected_revision=0,
    )
    assert merged.status == "ok", merged.to_dict()
    assert merged.revision == 1
    assert merged.result is not None
    assert merged.result["volume"] == pytest.approx(400.0 - 4.0 * math.pi)

    model = models.open("shared")
    replayed = cad.replay_model_json(model.model_json, strict=True)
    assert len(replayed) == 1
    assert replayed[0].get_volume() == pytest.approx(merged.result["volume"])

    reopened = MultiAgentStore(ModelStore(tmp_path / "models"))
    proposals = reopened.list_proposals("shared")
    assert {item.proposal_id for item in proposals} == {"body", "hole", "finish"}
    assert all(item.status == "merged" and item.merged_revision == 1 for item in proposals)
    assert reopened.messages("shared", recipient="review_agent")[0].payload["shape"] == "final"


def test_conflicting_writes_and_missing_dependencies_do_not_mutate_model(tmp_path: Path):
    models, collaboration = _stores(tmp_path)
    collaboration.submit_proposal(
        "shared", "box_agent", "box shared_shape 2 2 2",
        base_revision=0, proposal_id="box",
    )
    collaboration.submit_proposal(
        "shared", "sphere_agent", "sphere shared_shape 1",
        base_revision=0, proposal_id="sphere",
    )
    conflict = collaboration.merge(
        "shared", ("box", "sphere"), expected_revision=0
    )
    assert conflict.status == "conflict"
    assert conflict.conflicts[0].resource == "shared_shape"
    assert models.open("shared").revision == 0

    collaboration.submit_proposal(
        "shared", "base_agent", "box base 2 2 2",
        base_revision=0, proposal_id="base",
    )
    collaboration.submit_proposal(
        "shared", "move_agent", "translate moved base 1 0 0\nresult moved",
        base_revision=0, proposal_id="move",
    )
    missing_dependency = collaboration.merge(
        "shared", ("base", "move"), expected_revision=0
    )
    assert missing_dependency.status == "conflict"
    assert any(item.reason == "reader must depend on writer" for item in missing_dependency.conflicts)
    assert models.open("shared").revision == 0


def test_execution_failure_is_atomic_and_proposals_remain_pending(tmp_path: Path):
    models, collaboration = _stores(tmp_path)
    collaboration.submit_proposal(
        "shared", "good_agent", "box good 2 2 2",
        base_revision=0, proposal_id="good",
    )
    collaboration.submit_proposal(
        "shared", "bad_agent", "translate bad absent 1 0 0\nresult bad",
        base_revision=0, proposal_id="bad",
    )
    failed = collaboration.merge(
        "shared", ("good", "bad"), expected_revision=0
    )
    assert failed.status == "error"
    assert "unknown shape 'absent'" in failed.error
    assert models.open("shared").revision == 0
    assert all(item.status == "pending" for item in collaboration.list_proposals("shared"))


def test_agents_continue_from_committed_revision_and_reject_stale_proposal(tmp_path: Path):
    models, collaboration = _stores(tmp_path)
    collaboration.submit_proposal(
        "shared", "base_agent", "box base 2 2 2\nresult base",
        base_revision=0, proposal_id="base_v1",
    )
    assert collaboration.merge(
        "shared", ("base_v1",), expected_revision=0
    ).status == "ok"

    collaboration.submit_proposal(
        "shared", "stale_agent", "translate stale base 1 0 0",
        base_revision=0, proposal_id="stale",
    )
    stale = collaboration.merge("shared", ("stale",), expected_revision=1)
    assert stale.status == "error"
    assert "base_revision" in stale.error
    assert models.open("shared").revision == 1

    collaboration.submit_proposal(
        "shared", "move_agent", "translate moved base 1 0 0\nresult moved",
        base_revision=1, proposal_id="move_v2",
    )
    updated = collaboration.merge("shared", ("move_v2",), expected_revision=1)
    assert updated.status == "ok", updated.to_dict()
    assert updated.revision == 2
    assert updated.result["bbox"] == pytest.approx([0, -1, 0, 2, 1, 2])


def test_proposals_reject_transient_or_history_control_operations(tmp_path: Path):
    _models, collaboration = _stores(tmp_path)
    with pytest.raises(ValueError, match="durable modeling operations"):
        collaboration.submit_proposal(
            "shared", "agent", "inspect base volume",
            base_revision=0, proposal_id="inspect",
        )
    with pytest.raises(ValueError, match="coordinator operations"):
        collaboration.submit_proposal(
            "shared", "agent", "rollback old",
            base_revision=0, proposal_id="rollback",
        )
