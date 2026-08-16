"""Revision-driven Scene compilation and a dependency-free preview server."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import tempfile
import threading
import time
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import quote, unquote, urlsplit

import cadflow as cad
import rfc8785

from .runtime import AgentModel, DSLResponse
from .store import ModelStore


_QUALITIES = {
    "draft": (0.35, 0.22),
    "final": (0.1, 0.08),
}
_MAX_REQUEST_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class PreviewEvent:
    """One replayable model-scoped server-sent event."""

    event_id: int
    kind: str
    model_id: str
    revision: int
    data: Mapping[str, Any]

    def to_sse(self) -> bytes:
        payload = {
            "model": self.model_id,
            "revision": self.revision,
            **dict(self.data),
        }
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return (
            f"id: {self.event_id}\nevent: {self.kind}\ndata: {data}\n\n"
        ).encode("utf-8")


class PreviewEventHub:
    """Thread-safe bounded event replay and blocking subscription hub."""

    def __init__(self, *, history_limit: int = 128) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._history_limit = history_limit
        self._events: dict[str, deque[PreviewEvent]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._condition = threading.Condition()
        self._next_id = 1

    def publish(
        self,
        kind: str,
        model_id: str,
        revision: int,
        **data: Any,
    ) -> PreviewEvent:
        with self._condition:
            event = PreviewEvent(
                self._next_id,
                kind,
                model_id,
                revision,
                MappingProxyType(dict(data)),
            )
            self._next_id += 1
            self._events[model_id].append(event)
            self._condition.notify_all()
            return event

    def events_since(self, model_id: str, event_id: int) -> tuple[PreviewEvent, ...]:
        with self._condition:
            return tuple(
                event
                for event in self._events.get(model_id, ())
                if event.event_id > event_id
            )

    def wait(
        self,
        model_id: str,
        event_id: int,
        *,
        timeout: float = 15.0,
    ) -> tuple[PreviewEvent, ...]:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                events = tuple(
                    event
                    for event in self._events.get(model_id, ())
                    if event.event_id > event_id
                )
                if events:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ()
                self._condition.wait(remaining)


@dataclass(frozen=True, slots=True)
class PreviewArtifact:
    model_id: str
    revision: int
    build_id: int
    quality: str
    manifest_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "revision": self.revision,
            "build": self.build_id,
            "quality": self.quality,
            "manifest": self.manifest_url,
        }


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


class PreviewArtifactStore:
    """Publish immutable Scene builds and an atomically updated latest pointer."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._resolved_root = self.root.resolve()

    def write(
        self,
        *,
        model_id: str,
        revision: int,
        build_id: int,
        quality: str,
        package: Any,
    ) -> PreviewArtifact:
        AgentModel(model_id)
        if revision < 0 or build_id < 1:
            raise ValueError("revision and build_id are out of range")
        if quality not in _QUALITIES:
            raise ValueError("quality must be draft or final")
        target = self.root / model_id / str(revision) / str(build_id)
        for uri, payload in sorted(package.blobs.items()):
            relative = Path(str(uri))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe Scene blob URI: {uri}")
            self._write_atomic(target / relative, bytes(payload))
        manifest = rfc8785.dumps(_plain_json(package.manifest))
        self._write_atomic(target / "scene.json", manifest)
        return PreviewArtifact(
            model_id=model_id,
            revision=revision,
            build_id=build_id,
            quality=quality,
            manifest_url=(
                f"/artifacts/{quote(model_id, safe='')}/{revision}/{build_id}/scene.json"
            ),
        )

    def promote(self, artifact: PreviewArtifact) -> None:
        payload = json.dumps(
            artifact.to_dict(), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        self._write_atomic(self.root / artifact.model_id / "latest.json", payload)

    def latest(self, model_id: str) -> PreviewArtifact | None:
        AgentModel(model_id)
        path = self.root / model_id / "latest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        artifact = PreviewArtifact(
            model_id=str(payload["model"]),
            revision=int(payload["revision"]),
            build_id=int(payload["build"]),
            quality=str(payload["quality"]),
            manifest_url=str(payload["manifest"]),
        )
        if artifact.model_id != model_id or artifact.quality not in _QUALITIES:
            raise ValueError("latest preview descriptor is malformed")
        return artifact

    def resolve(self, relative_url_path: str) -> Path:
        decoded = unquote(relative_url_path)
        relative = Path(decoded)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe artifact path")
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self._resolved_root)
        except ValueError as exc:
            raise ValueError("unsafe artifact path") from exc
        return target

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class _PreviewBuild:
    model_id: str
    revision: int
    build_id: int
    quality: str
    value: Any


class RealtimePreview:
    """Apply DSL revisions and compile their committed result in the background."""

    def __init__(
        self,
        models: ModelStore,
        artifacts: PreviewArtifactStore,
        *,
        events: PreviewEventHub | None = None,
    ) -> None:
        self.models = models
        self.artifacts = artifacts
        self.events = events or PreviewEventHub()
        self._condition = threading.Condition()
        self._pending: dict[str, _PreviewBuild] = {}
        self._latest_build: dict[str, int] = {}
        self._next_build = 1
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="cadflow-preview-compiler",
            daemon=True,
        )
        self._worker.start()

    def apply(
        self,
        model_id: str,
        document: str,
        *,
        expected_revision: int,
        quality: str | None = None,
    ) -> DSLResponse:
        if quality is not None and quality not in _QUALITIES:
            raise ValueError("quality must be draft or final")
        response, model = self.models.apply_with_model(
            model_id,
            document,
            expected_revision=expected_revision,
            create=True,
        )
        if response.status != "ok":
            return response
        requested_quality = (
            str(response.previews[-1]["quality"])
            if response.previews
            else quality or "draft"
        )
        changed = response.revision != expected_revision
        if not changed and not response.previews:
            return response
        try:
            preview_name = (
                str(response.previews[-1]["shape"])
                if response.previews
                else None
            )
            value = (
                model.named_value(preview_name)
                if preview_name is not None
                else model.result_value
            )
        except RuntimeError:
            return response
        self.schedule(model_id, response.revision, value, quality=requested_quality)
        return response

    def schedule(
        self,
        model_id: str,
        revision: int,
        value: Any,
        *,
        quality: str = "draft",
    ) -> int:
        if quality not in _QUALITIES:
            raise ValueError("quality must be draft or final")
        AgentModel(model_id)
        with self._condition:
            if self._closed:
                raise RuntimeError("realtime preview is closed")
            build_id = self._next_build
            self._next_build += 1
            build = _PreviewBuild(model_id, revision, build_id, quality, value)
            self._pending[model_id] = build
            self._latest_build[model_id] = build_id
            self.events.publish(
                "revision_pending",
                model_id,
                revision,
                build=build_id,
                quality=quality,
            )
            self._condition.notify()
        return build_id

    def state(self, model_id: str) -> dict[str, Any]:
        payload = self.models.state(model_id)
        latest = self.artifacts.latest(model_id)
        if latest is not None:
            payload["preview"] = latest.to_dict()
        return payload

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=30)

    def __enter__(self) -> "RealtimePreview":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _is_current(self, build: _PreviewBuild) -> bool:
        with self._condition:
            return self._latest_build.get(build.model_id) == build.build_id

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed and not self._pending:
                    return
                model_id = next(iter(self._pending))
                build = self._pending.pop(model_id)
            started = time.monotonic()
            try:
                linear, angular = _QUALITIES[build.quality]
                package = cad.compile_scene(
                    scene_id=f"{build.model_id}-r{build.revision}",
                    roots=(cad.SceneRoot(root_id="result", value=build.value),),
                    source=cad.SceneSource(
                        kind="manual",
                        source_id=(
                            f"agent-dsl-{build.model_id}-r{build.revision}"
                        ),
                    ),
                    options=cad.SceneCompileOptions(
                        linear_tolerance=linear,
                        angular_tolerance=angular,
                    ),
                )
                if not self._is_current(build):
                    continue
                artifact = self.artifacts.write(
                    model_id=build.model_id,
                    revision=build.revision,
                    build_id=build.build_id,
                    quality=build.quality,
                    package=package,
                )
                if not self._is_current(build):
                    continue
                self.artifacts.promote(artifact)
                self.events.publish(
                    "revision_ready",
                    build.model_id,
                    build.revision,
                    build=artifact.build_id,
                    quality=artifact.quality,
                    manifest=artifact.manifest_url,
                    elapsed_ms=round((time.monotonic() - started) * 1000, 1),
                )
            except Exception as exc:
                if self._is_current(build):
                    self.events.publish(
                        "revision_failed",
                        build.model_id,
                        build.revision,
                        build=build.build_id,
                        quality=build.quality,
                        error=str(exc),
                    )


class PreviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        preview: RealtimePreview,
        *,
        web_root: str | Path | None = None,
    ) -> None:
        self.preview = preview
        self.web_root = Path(web_root or Path(__file__).with_name("web"))
        super().__init__(server_address, PreviewRequestHandler)


class PreviewRequestHandler(BaseHTTPRequestHandler):
    server: PreviewHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send_file(self.server.web_root / "index.html", cache=False)
            return
        if path == "/viewer.js":
            self._send_file(self.server.web_root / "viewer.js", cache=False)
            return
        if path == "/styles.css":
            self._send_file(self.server.web_root / "styles.css", cache=False)
            return
        if path.startswith("/models/"):
            model_id = unquote(path.removeprefix("/models/"))
            if not model_id or "/" in model_id:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                self._send_json(HTTPStatus.OK, self.server.preview.state(model_id))
            except (FileNotFoundError, ValueError) as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        if path.startswith("/events/"):
            self._serve_events(unquote(path.removeprefix("/events/")))
            return
        if path.startswith("/artifacts/"):
            try:
                target = self.server.preview.artifacts.resolve(
                    path.removeprefix("/artifacts/")
                )
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_file(target, cache=True)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if not path.startswith("/models/") or not path.endswith("/apply"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        model_id = unquote(path.removeprefix("/models/").removesuffix("/apply"))
        if not model_id or "/" in model_id:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid model id"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= _MAX_REQUEST_BYTES:
                raise ValueError("request body length is out of range")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            document = payload.get("document")
            expected_revision = payload.get("expected_revision")
            quality = payload.get("quality")
            if not isinstance(document, str):
                raise ValueError("document must be a string")
            if (
                not isinstance(expected_revision, int)
                or isinstance(expected_revision, bool)
            ):
                raise ValueError("expected_revision must be an integer")
            if quality is not None and not isinstance(quality, str):
                raise ValueError("quality must be a string")
            response = self.server.preview.apply(
                model_id,
                document,
                expected_revision=expected_revision,
                quality=quality,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        status = HTTPStatus.OK
        if response.status != "ok":
            status = (
                HTTPStatus.CONFLICT
                if response.error and response.error.startswith("revision conflict")
                else HTTPStatus.UNPROCESSABLE_ENTITY
            )
        self._send_json(status, response.to_dict())

    def _serve_events(self, model_id: str) -> None:
        try:
            AgentModel(model_id)
            last_id = int(self.headers.get("Last-Event-ID", "0") or 0)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                events = self.server.preview.events.wait(
                    model_id, last_id, timeout=15.0
                )
                if events:
                    for event in events:
                        self.wfile.write(event.to_sse())
                        last_id = event.event_id
                else:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def _send_file(self, path: Path, *, cache: bool) -> None:
        try:
            body = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control", "public, max-age=31536000, immutable" if cache else "no-store"
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def log_message(self, format: str, *args: Any) -> None:
        return


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    state_dir: str | Path = ".cadflow-preview/models",
    artifact_dir: str | Path = ".cadflow-preview/artifacts",
) -> PreviewHTTPServer:
    preview = RealtimePreview(
        ModelStore(state_dir),
        PreviewArtifactStore(artifact_dir),
    )
    return PreviewHTTPServer((host, port), preview)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve CadFlow real-time previews")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", default=".cadflow-preview/models")
    parser.add_argument("--artifact-dir", default=".cadflow-preview/artifacts")
    args = parser.parse_args(argv)
    server = make_server(
        host=args.host,
        port=args.port,
        state_dir=args.state_dir,
        artifact_dir=args.artifact_dir,
    )
    host, port = server.server_address[:2]
    print(f"CadFlow preview: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        server.preview.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PreviewArtifact",
    "PreviewArtifactStore",
    "PreviewEvent",
    "PreviewEventHub",
    "PreviewHTTPServer",
    "RealtimePreview",
    "main",
    "make_server",
]
