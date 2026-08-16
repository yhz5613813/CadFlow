from __future__ import annotations

import json
from pathlib import Path

import pytest

import cadflow as cad
from agent_dsl import AgentModel, DSLParseError, ModelStore, parse


GEOMETRY_PARITY_CASES = {
    "box": "box final 4 3 2 at 1 2 3\nresult final",
    "cylinder": (
        "cylinder final 2 5 at 1 2 3 axis 0 1 0\nresult final"
    ),
    "cone": (
        "cone final 3 5 top_radius 1 at 1 2 3 axis 0 1 0\nresult final"
    ),
    "sphere": "sphere final 2 at 1 2 3\nresult final",
    "cut": """
        box body 4 4 4
        cylinder tool 1 6 at 0 0 -1
        cut final body tool
        result final
    """,
    "union": """
        box left 4 4 4 at 0 0 0
        box right 4 4 4 at 2 0 0
        union final left right
        result final
    """,
    "intersect": """
        box left 4 4 4 at 0 0 0
        box right 4 4 4 at 2 0 0
        intersect final left right
        result final
    """,
    "translate": """
        box source 2 4 6
        translate final source 3 2 1
        result final
    """,
    "rotate": """
        box source 2 4 6 at 2 0 0
        rotate final source 37 axis 0 0 1 origin 1 0 0
        result final
    """,
    "mirror": """
        box source 2 4 6 at 2 0 0
        mirror final source normal 1 0 0 origin 1 0 0
        result final
    """,
    "fillet": """
        box source 4 4 4
        fillet final source 0.2 edges tag:edge.boundary
        result final
    """,
    "chamfer": """
        box source 4 4 4
        chamfer final source 0.2 edges 0
        result final
    """,
    "shell": """
        box source 4 4 4
        shell final source 0.2 faces tag:face.top
        result final
    """,
}


def _build_public_api_case(case: str):
    if case == "box":
        return cad.make_box_rsolid(4, 3, 2, bottom_face_center=(1, 2, 3))
    if case == "cylinder":
        return cad.make_cylinder_rsolid(
            2, 5, bottom_face_center=(1, 2, 3), axis=(0, 1, 0)
        )
    if case == "cone":
        return cad.make_cone_rsolid(
            3,
            5,
            top_radius=1,
            bottom_face_center=(1, 2, 3),
            axis=(0, 1, 0),
        )
    if case == "sphere":
        return cad.make_sphere_rsolid(2, center=(1, 2, 3))
    if case in {"cut", "union", "intersect"}:
        if case == "cut":
            left = cad.make_box_rsolid(4, 4, 4)
            right = cad.make_cylinder_rsolid(
                1, 6, bottom_face_center=(0, 0, -1)
            )
            return cad.cut_rsolid(left, right)
        left = cad.make_box_rsolid(4, 4, 4, bottom_face_center=(0, 0, 0))
        right = cad.make_box_rsolid(4, 4, 4, bottom_face_center=(2, 0, 0))
        return (
            cad.union_rsolid(left, right)
            if case == "union"
            else cad.intersect_rsolid(left, right)
        )
    source = cad.make_box_rsolid(
        2 if case in {"translate", "rotate", "mirror"} else 4,
        4,
        6 if case in {"translate", "rotate", "mirror"} else 4,
        bottom_face_center=(2, 0, 0) if case in {"rotate", "mirror"} else (0, 0, 0),
    )
    if case == "translate":
        return cad.translate_shape(source, (3, 2, 1))
    if case == "rotate":
        return cad.rotate_shape(
            source, 37, axis=(0, 0, 1), origin=(1, 0, 0)
        )
    if case == "mirror":
        return cad.mirror_shape(source, (1, 0, 0), (1, 0, 0))
    if case == "fillet":
        edges = cad.select_edges_by_tag(source, "edge.boundary")
        return cad.fillet_rsolid(source, edges, 0.2)
    if case == "chamfer":
        return cad.chamfer_rsolid(source, [source.get_edges(0)], 0.2)
    if case == "shell":
        faces = cad.select_faces_by_tag(source, "face.top")
        return cad.shell_rsolid(source, faces, 0.2)
    raise AssertionError(f"unknown parity case: {case}")


@pytest.mark.parametrize("case", GEOMETRY_PARITY_CASES)
def test_every_geometry_operation_is_strictly_equal_to_public_api(
    case: str, tmp_path: Path
):
    baseline = tmp_path / f"{case}-public.step"
    candidate = tmp_path / f"{case}-dsl.step"
    with cad.GraphSession(graph_id=f"public_{case}"):
        public_shape = _build_public_api_case(case)
    cad.export_step(shapes=public_shape, filename=str(baseline))

    model = AgentModel(f"dsl_{case}")
    document = f"{GEOMETRY_PARITY_CASES[case]}\nexport final step {candidate}"
    response = model.apply(document)
    assert response.status == "ok", response.to_dict()
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(
        baseline, candidate
    )
    assert comparison.hard_gate_passed, comparison.to_dict()
    assert comparison.target_minus_candidate_volume == pytest.approx(
        0.0, abs=1e-9
    )
    assert comparison.candidate_minus_target_volume == pytest.approx(
        0.0, abs=1e-9
    )


def test_transform_boolean_and_finishing_operations_replay():
    cases = {
        "booleans": """
            box a 4 4 4 at 0 0 0
            box b 4 4 4 at 2 0 0
            union joined a b
            intersect common a b
            result common
        """,
        "transforms": """
            box a 2 4 6 at 2 0 0
            rotate turned a 90 axis 0 0 1 origin 0 0 0
            mirror final turned normal 1 0 0 origin 0 0 0
            result final
        """,
        "fillet_tag": """
            box a 4 4 4
            fillet final a 0.2 edges tag:edge.boundary
            result final
        """,
        "chamfer_indices": """
            box a 4 4 4
            chamfer final a 0.2 edges 0
            result final
        """,
        "shell_tag": """
            box a 4 4 4
            shell final a 0.2 faces tag:face.top
            result final
        """,
    }
    for model_id, document in cases.items():
        model = AgentModel(model_id)
        response = model.apply(document)
        assert response.status == "ok", response.to_dict()
        assert response.result is not None
        replayed = cad.replay_model_json(model.model_json, strict=True)
        assert len(replayed) == 1
        assert replayed[0].get_volume() == pytest.approx(
            response.result["volume"], rel=1e-9
        )

    assert AgentModel("bad_index").apply(
        "box a 2 2 2\nfillet bad a 0.1 edges 99\nresult bad"
    ).status == "error"


def test_mirror_dsl_is_brep_equal_to_public_api(tmp_path: Path):
    baseline = tmp_path / "baseline.step"
    candidate = tmp_path / "candidate.step"
    with cad.GraphSession(graph_id="mirror_baseline"):
        source = cad.make_box_rsolid(2, 4, 6, bottom_face_center=(2, 0, 0))
        turned = cad.rotate_shape(
            source, 90, axis=(0, 0, 1), origin=(0, 0, 0)
        )
        final = cad.mirror_shape(turned, (0, 0, 0), (1, 0, 0))
    cad.export_step(shapes=final, filename=str(baseline))

    model = AgentModel("mirror_parity")
    response = model.apply(
        f"""
        box source 2 4 6 at 2 0 0
        rotate turned source 90 axis 0 0 1 origin 0 0 0
        mirror final turned normal 1 0 0 origin 0 0 0
        result final
        export final step {candidate}
        """
    )
    assert response.status == "ok", response.to_dict()
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(
        baseline, candidate
    )
    assert comparison.hard_gate_passed, comparison.to_dict()
    assert comparison.target_minus_candidate_volume == pytest.approx(
        0.0, abs=1e-9
    )
    assert comparison.candidate_minus_target_volume == pytest.approx(
        0.0, abs=1e-9
    )


def test_effects_are_ephemeral_bounded_and_do_not_change_revision(
    tmp_path: Path,
):
    first_export = tmp_path / "first.step"
    second_export = tmp_path / "second.step"
    model = AgentModel("effects")
    response = model.apply(
        f"""
        box base 4 4 4
        inspect base faces edges limit=2
        result base
        export base step {first_export}
        """
    )
    assert response.status == "ok", response.to_dict()
    assert response.revision == 1
    facts = response.inspections[0]["facts"]
    assert len(facts["faces"]) == 2
    assert len(facts["edges"]) == 2
    assert all(
        not command.startswith(("inspect ", "export ", "preview "))
        for command in model.snapshot()["commands"]
    )

    first_export.unlink()
    query = model.apply("inspect base volume limit=1")
    assert query.status == "ok"
    assert query.revision == 1
    assert query.result is None
    direct_query = model.inspect("base", fields=("bbox",), limit=1)
    assert direct_query.status == "ok"
    assert direct_query.revision == 1
    exported = model.export_step("base", second_export)
    assert exported.status == "ok"
    assert exported.revision == 1

    update = model.apply("translate moved base 1 0 0\nresult moved")
    assert update.status == "ok"
    assert update.revision == 2
    assert not first_export.exists()
    assert second_export.is_file()

    with pytest.raises(DSLParseError):
        parse("inspect base faces limit=65")


def test_preview_effect_is_bounded_ephemeral_and_exposes_committed_result():
    parsed = parse("preview body\npreview body final")
    assert parsed[0].args == ("body", "draft")
    assert parsed[1].args == ("body", "final")
    with pytest.raises(DSLParseError, match="draft or final"):
        parse("preview body ultra")

    model = AgentModel("preview_effect")
    built = model.apply("box body 8 6 4\nresult body\npreview body final")
    assert built.status == "ok", built.to_dict()
    assert built.previews == ({"shape": "body", "quality": "final"},)
    assert model.result_value.get_volume() == pytest.approx(192.0)
    assert all(
        not command.startswith("preview ")
        for command in model.snapshot()["commands"]
    )

    effect_only = model.apply("preview body")
    assert effect_only.status == "ok"
    assert effect_only.revision == 1
    assert effect_only.previews == ({"shape": "body", "quality": "draft"},)


def test_errors_do_not_mutate_state_or_allow_silent_name_overwrite():
    model = AgentModel("transactions")
    assert model.apply("box base 2 2 2\nresult base").status == "ok"
    before = model.snapshot()
    before_json = model.model_json

    duplicate = model.apply("sphere base 1")
    assert duplicate.status == "error"
    assert "already exists" in duplicate.error
    assert model.snapshot() == before
    assert model.model_json == before_json

    missing = model.apply("inspect absent volume\nbox later 1 1 1")
    assert missing.status == "error"
    assert model.snapshot() == before
    assert model.model_json == before_json

    late_tag = model.apply("inspect base tags\ntag base role.late")
    assert late_tag.status == "error"
    assert "must precede" in late_tag.error
    assert model.snapshot() == before
    assert model.model_json == before_json


def test_model_store_reopens_replays_and_rejects_stale_revision(tmp_path: Path):
    store = ModelStore(tmp_path / "models")
    assert store.open("part", create=True).revision == 0

    built = store.apply(
        "part",
        "box base 4 4 4\nresult base",
        expected_revision=0,
    )
    assert built.status == "ok"
    assert built.revision == 1

    stale = store.apply(
        "part", "translate stale base 1 0 0", expected_revision=0
    )
    assert stale.status == "error"
    assert "revision conflict" in stale.error
    assert stale.revision == 1

    checkpointed = store.checkpoint("part", "base", expected_revision=1)
    assert checkpointed.status == "ok"
    moved = store.apply(
        "part",
        "translate moved base 3 0 0\nresult moved",
        expected_revision=2,
    )
    assert moved.status == "ok"
    rolled_back = store.rollback("part", "base", expected_revision=3)
    assert rolled_back.status == "ok"
    assert rolled_back.revision == 4

    reopened = ModelStore(tmp_path / "models").open("part")
    assert reopened.revision == 4
    assert reopened.snapshot()["result"] == "base"
    replayed = cad.replay_model_json(reopened.model_json, strict=True)
    assert len(replayed) == 1
    assert replayed[0].get_volume() == pytest.approx(64.0)

    inspected = store.inspect(
        "part", "base", fields=("volume",), expected_revision=4
    )
    assert inspected.status == "ok"
    assert inspected.revision == 4
    output = tmp_path / "stored.step"
    exported = store.export_step(
        "part", "base", output, expected_revision=4
    )
    assert exported.status == "ok"
    assert exported.revision == 4
    assert output.is_file() and output.stat().st_size > 0

    persisted = json.loads((tmp_path / "models" / "part.json").read_text())
    assert persisted["schema"] == "cadflow-agent-store/1"
    assert persisted["snapshot"]["revision"] == 4
    assert all(
        not command.startswith(("inspect ", "export ", "rollback "))
        for command in persisted["snapshot"]["commands"]
    )


def test_model_store_reopens_intermediate_state_without_result(tmp_path: Path):
    store = ModelStore(tmp_path / "models")
    store.open("draft", create=True)
    drafted = store.apply(
        "draft", "box base 2 2 2", expected_revision=0
    )
    assert drafted.status == "ok"
    assert drafted.result is None

    reopened = ModelStore(tmp_path / "models").open("draft")
    assert reopened.revision == 1
    finalized = store.apply("draft", "result base", expected_revision=1)
    assert finalized.status == "ok"
    assert finalized.result["volume"] == pytest.approx(8.0)


def test_model_store_returns_committed_live_model_without_second_open(tmp_path: Path):
    store = ModelStore(tmp_path / "models")
    response, model = store.apply_with_model(
        "live",
        "box body 5 4 3\nresult body",
        expected_revision=0,
        create=True,
    )
    assert response.status == "ok"
    assert response.revision == 1
    assert model.revision == 1
    assert model.result_value.get_volume() == pytest.approx(60.0)

    conflict, current = store.apply_with_model(
        "live",
        "sphere stale 1",
        expected_revision=0,
    )
    assert conflict.status == "error"
    assert current.revision == 1
