"""Atomic disk persistence for stateful CadFlow agent models."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shlex
import tempfile
from typing import Any, Iterator

from .runtime import AgentModel, DSLResponse


STORE_SCHEMA = "cadflow-agent-store/1"


class ModelStore:
    """Persist models by id with process-safe optimistic revision checks."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError(f"model store is not a directory: {self.root}")

    def open(self, model_id: str, *, create: bool = False) -> AgentModel:
        """Open a model, optionally creating an empty revision-zero model."""
        model_id = self._validated_model_id(model_id)
        with self._lock(model_id):
            try:
                return self._load_unlocked(model_id)
            except FileNotFoundError:
                if not create:
                    raise
                model = AgentModel(model_id)
                self._save_unlocked(model)
                return model

    def state(self, model_id: str) -> dict[str, Any]:
        """Read durable model metadata without replaying its geometry."""
        model_id = self._validated_model_id(model_id)
        with self._lock(model_id):
            path = self._state_path(model_id)
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or payload.get("schema") != STORE_SCHEMA:
                raise ValueError(f"unsupported or malformed model store file: {path}")
            snapshot = payload.get("snapshot")
            if not isinstance(snapshot, dict) or snapshot.get("model") != model_id:
                raise ValueError(f"stored model snapshot is malformed: {path}")
            revision = snapshot.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                raise ValueError(f"stored model revision is malformed: {path}")
            result = snapshot.get("result")
            if result is not None and not isinstance(result, str):
                raise ValueError(f"stored model result is malformed: {path}")
            return {"model": model_id, "revision": revision, "result": result}

    def apply(
        self,
        model_id: str,
        document: str,
        *,
        expected_revision: int,
    ) -> DSLResponse:
        """Apply one submission when the stored revision matches the caller."""
        response, _model = self.apply_with_model(
            model_id,
            document,
            expected_revision=expected_revision,
        )
        return response

    def apply_with_model(
        self,
        model_id: str,
        document: str,
        *,
        expected_revision: int,
        create: bool = False,
    ) -> tuple[DSLResponse, AgentModel]:
        """Atomically apply a submission and return its committed live model.

        The returned model is detached from the store lock. It is useful for
        in-process consumers such as preview compilers that would otherwise
        need to replay the just-committed history a second time.
        """
        model_id = self._validated_model_id(model_id)
        with self._lock(model_id):
            try:
                model = self._load_unlocked(model_id)
            except FileNotFoundError:
                if not create:
                    raise
                model = AgentModel(model_id)
                self._save_unlocked(model)
            conflict = self._revision_conflict(model, expected_revision)
            if conflict is not None:
                return conflict, model
            before = model.revision
            response = model.apply(document)
            if response.status == "ok" and model.revision != before:
                self._save_unlocked(model)
            return response, model

    def inspect(
        self,
        model_id: str,
        name: str,
        *,
        fields: tuple[str, ...] = (),
        limit: int = 12,
        expected_revision: int | None = None,
    ) -> DSLResponse:
        """Return bounded facts without changing the stored revision."""
        model_id = self._validated_model_id(model_id)
        with self._lock(model_id):
            model = self._load_unlocked(model_id)
            if expected_revision is not None:
                conflict = self._revision_conflict(model, expected_revision)
                if conflict is not None:
                    return conflict
            return model.inspect(name, fields=fields, limit=limit)

    def checkpoint(
        self,
        model_id: str,
        label: str,
        *,
        expected_revision: int,
    ) -> DSLResponse:
        return self.apply(
            model_id,
            f"checkpoint {shlex.quote(label)}",
            expected_revision=expected_revision,
        )

    def rollback(
        self,
        model_id: str,
        label: str,
        *,
        expected_revision: int,
    ) -> DSLResponse:
        return self.apply(
            model_id,
            f"rollback {shlex.quote(label)}",
            expected_revision=expected_revision,
        )

    def export_step(
        self,
        model_id: str,
        name: str,
        path: str | Path,
        *,
        expected_revision: int | None = None,
    ) -> DSLResponse:
        """Export a stored named result without changing its revision."""
        model_id = self._validated_model_id(model_id)
        with self._lock(model_id):
            model = self._load_unlocked(model_id)
            if expected_revision is not None:
                conflict = self._revision_conflict(model, expected_revision)
                if conflict is not None:
                    return conflict
            return model.export_step(name, path)

    @staticmethod
    def _validated_model_id(model_id: str) -> str:
        AgentModel(model_id)
        return model_id

    def _state_path(self, model_id: str) -> Path:
        return self.root / f"{model_id}.json"

    @contextmanager
    def _lock(self, model_id: str) -> Iterator[None]:
        lock_path = self.root / f".{model_id}.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self, model_id: str) -> AgentModel:
        path = self._state_path(model_id)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or payload.get("schema") != STORE_SCHEMA:
            raise ValueError(f"unsupported or malformed model store file: {path}")
        snapshot = payload.get("snapshot")
        model_json = payload.get("model_json")
        if model_json is not None and not isinstance(model_json, str):
            raise ValueError(f"stored model_json must be a string or null: {path}")
        model = AgentModel.from_snapshot(snapshot, model_json=model_json)
        if model.model_id != model_id:
            raise ValueError(f"stored model id does not match filename: {path}")
        return model

    def _save_unlocked(self, model: AgentModel) -> None:
        try:
            model_json = model.model_json
        except RuntimeError:
            model_json = None
        payload = {
            "schema": STORE_SCHEMA,
            "snapshot": model.snapshot(),
            "model_json": model_json,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.root,
            prefix=f".{model.model_id}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._state_path(model.model_id))
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _revision_conflict(
        model: AgentModel, expected_revision: int
    ) -> DSLResponse | None:
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            return DSLResponse(
                model.model_id,
                model.revision,
                "error",
                error="expected_revision must be a non-negative integer",
            )
        if model.revision != expected_revision:
            return DSLResponse(
                model.model_id,
                model.revision,
                "error",
                error=(
                    f"revision conflict: expected {expected_revision}, "
                    f"current {model.revision}"
                ),
            )
        return None
