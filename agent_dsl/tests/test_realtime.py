from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from agent_dsl import (
    ModelStore,
    PreviewArtifactStore,
    PreviewEventHub,
    PreviewHTTPServer,
    RealtimePreview,
)


def _terminal_event(
    preview: RealtimePreview,
    model_id: str,
    timeout: float = 20.0,
    *,
    after: int = 0,
):
    cursor = after
    while True:
        events = preview.events.wait(model_id, cursor, timeout=timeout)
        assert events, "preview build timed out"
        cursor = events[-1].event_id
        for event in events:
            if event.kind in {"revision_ready", "revision_failed"}:
                return event


def test_event_hub_replays_bounded_model_scoped_events():
    hub = PreviewEventHub(history_limit=2)
    first = hub.publish("revision_pending", "left", 1, build=1)
    hub.publish("revision_ready", "left", 1, build=1)
    third = hub.publish("revision_pending", "left", 2, build=2)
    hub.publish("revision_ready", "right", 1, build=3)

    assert [event.event_id for event in hub.events_since("left", 0)] == [2, 3]
    assert hub.events_since("left", third.event_id) == ()
    assert b"event: revision_pending" in first.to_sse()
    assert b'"model":"left"' in first.to_sse()


def test_realtime_preview_builds_scene_and_honors_preview_quality(tmp_path: Path):
    models = ModelStore(tmp_path / "models")
    artifacts = PreviewArtifactStore(tmp_path / "artifacts")
    with RealtimePreview(models, artifacts) as preview:
        response = preview.apply(
            "part",
            "box body 20 10 4\nresult body\npreview body final",
            expected_revision=0,
        )
        assert response.status == "ok", response.to_dict()
        terminal = _terminal_event(preview, "part")
        assert terminal.kind == "revision_ready", dict(terminal.data)
        assert terminal.data["quality"] == "final"

        artifact = artifacts.latest("part")
        assert artifact is not None
        manifest_path = artifacts.resolve(
            artifact.manifest_url.removeprefix("/artifacts/")
        )
        manifest = json.loads(manifest_path.read_bytes())
        assert manifest["schema_version"] == "1.0"
        assert manifest["compile_options"]["linear_tolerance"] == 0.1
        assert len(manifest["geometry_assets"]) == 1
        assert len(manifest["edge_assets"]) == 1
        for asset in [*manifest["geometry_assets"], *manifest["edge_assets"]]:
            assert (manifest_path.parent / asset["uri"]).is_file()

        effect = preview.apply(
            "part", "preview body draft", expected_revision=response.revision
        )
        assert effect.status == "ok"
        assert effect.revision == response.revision
        next_terminal = _terminal_event(preview, "part", after=terminal.event_id)
        assert next_terminal.kind == "revision_ready"
        assert next_terminal.data["quality"] == "draft"
        assert int(next_terminal.data["build"]) > int(terminal.data["build"])

    with pytest.raises(ValueError, match="unsafe"):
        artifacts.resolve("../models/part.json")


def test_realtime_preview_targets_the_named_shape(tmp_path: Path):
    models = ModelStore(tmp_path / "models")
    artifacts = PreviewArtifactStore(tmp_path / "artifacts")
    with RealtimePreview(models, artifacts) as preview:
        response = preview.apply(
            "named_target",
            "box body 20 10 4\n"
            "box tool 2 3 1 at 100 200 300\n"
            "result body\n"
            "preview tool final",
            expected_revision=0,
        )
        assert response.status == "ok", response.to_dict()
        terminal = _terminal_event(preview, "named_target")
        assert terminal.kind == "revision_ready", dict(terminal.data)

        artifact = artifacts.latest("named_target")
        assert artifact is not None
        manifest_path = artifacts.resolve(
            artifact.manifest_url.removeprefix("/artifacts/")
        )
        manifest = json.loads(manifest_path.read_bytes())
        bounds = manifest["geometry_assets"][0]["scene_local_bounds"]
        size = tuple(
            maximum - minimum
            for minimum, maximum in zip(bounds["min"], bounds["max"])
        )
        assert size == pytest.approx((2.0, 3.0, 1.0), abs=2e-5)


def test_http_apply_state_and_artifact_routes(tmp_path: Path):
    preview = RealtimePreview(
        ModelStore(tmp_path / "models"),
        PreviewArtifactStore(tmp_path / "artifacts"),
    )
    server = PreviewHTTPServer(("127.0.0.1", 0), preview)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        index = urllib.request.urlopen(base + "/", timeout=5).read()
        assert b"CadFlow" in index

        body = json.dumps(
            {
                "document": "box body 12 8 3\nresult body",
                "expected_revision": 0,
                "quality": "draft",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base + "/models/http_part/apply",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert response["status"] == "ok"
        assert response["revision"] == 1
        terminal = _terminal_event(preview, "http_part")
        assert terminal.kind == "revision_ready", dict(terminal.data)

        state = json.loads(
            urllib.request.urlopen(base + "/models/http_part", timeout=10).read()
        )
        assert state["revision"] == 1
        manifest = urllib.request.urlopen(
            base + state["preview"]["manifest"], timeout=5
        ).read()
        assert json.loads(manifest)["schema_version"] == "1.0"

        stale_request = urllib.request.Request(
            base + "/models/http_part/apply",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(stale_request, timeout=10)
        assert captured.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        preview.close()
        thread.join(timeout=5)
