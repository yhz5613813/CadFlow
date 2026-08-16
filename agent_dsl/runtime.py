"""Stateful compiler/runtime for the isolated CadFlow DSL."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

import cadflow as cad

from .parser import DSLParseError, Instruction, MAX_INSPECTION_ITEMS, parse


_MODEL_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_GEOMETRY_OPS = {
    "box", "cylinder", "cone", "sphere", "cut", "union", "intersect",
    "translate", "rotate", "mirror", "fillet", "chamfer", "shell",
}
_EFFECT_OPS = {"inspect", "export", "preview"}
_INSPECTION_FIELDS = {
    "kind", "volume", "area", "surface_area", "bbox", "topology", "tags",
    "center_of_mass", "faces", "edges",
}


class DSLExecutionError(RuntimeError):
    """Raised when a valid instruction cannot be executed."""


@dataclass(frozen=True)
class DSLResponse:
    """Compact result returned after one DSL submission."""

    model_id: str
    revision: int
    status: str
    created: tuple[str, ...] = ()
    result: dict[str, Any] | None = None
    inspections: tuple[dict[str, Any], ...] = ()
    exports: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    previews: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "revision": self.revision,
            "status": self.status,
        }
        if self.created:
            payload["created"] = list(self.created)
        if self.result is not None:
            payload["result"] = self.result
        if self.inspections:
            payload["inspections"] = list(self.inspections)
        if self.exports:
            payload["exports"] = list(self.exports)
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        if self.previews:
            payload["previews"] = list(self.previews)
        if self.error is not None:
            payload["error"] = self.error
        return payload

    def compact_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class _Checkpoint:
    label: str
    instruction_count: int
    result_name: str | None


def _shape_summary(shape: Any, *, fields: Iterable[str] = (), limit: int = 12) -> dict[str, Any]:
    """Return bounded facts only; never serialize a live shape or mesh by default."""
    requested = set(fields)
    if not requested:
        requested = {"kind", "volume", "area", "bbox", "topology"}
    result: dict[str, Any] = {}
    if "kind" in requested:
        result["kind"] = shape.__class__.__name__.lower()
    with tempfile.TemporaryDirectory(prefix="cadflow-agent-dsl-") as tmp:
        step_path = Path(tmp) / "inspection.step"
        cad.export_step(shapes=shape, filename=str(step_path))
        from cadflow.inspect import brep

        report = brep.inspect_step_rbrepinspection(step_path)
    if "kind" in requested:
        result["kind"] = "solid" if report.counts.get("solid", 0) else "shape"
    if "volume" in requested:
        result["volume"] = float(report.volume)
    if "area" in requested or "surface_area" in requested:
        result["area"] = float(report.surface_area)
    if "surface_area" in requested:
        result["surface_area"] = float(report.surface_area)
    if "bbox" in requested:
        result["bbox"] = list(report.bounding_box)
    if "center_of_mass" in requested:
        result["center_of_mass"] = list(report.center_of_mass)
    if "topology" in requested:
        result["topology"] = {
            "faces": report.counts.get("unique_faces", 0),
            "edges": report.counts.get("unique_edges", 0),
            "solids": report.counts.get("solid", 0),
        }
    if "faces" in requested:
        result["faces"] = [
            {"index": int(face["index"]), "area": float(face["area"]), "surface": face["surface"]}
            for face in report.faces[: max(1, limit)]
        ]
    if "edges" in requested:
        result["edges"] = [
            {"index": int(edge["index"]), "length": float(edge["length"]), "type": edge["type"]}
            for edge in report.edges[: max(1, limit)]
        ]
    if "tags" in requested:
        result["tags"] = list(cad.list_tags(shape))
    return result


class AgentModel:
    """Replayable model state addressed by ``model_id`` and revision.

    A submission is applied to the current command history.  The history is
    replayed into a fresh ``GraphSession`` on every revision, which makes
    checkpoints, rollback, and independent parity checks deterministic.
    """

    def __init__(self, model_id: str = "model") -> None:
        if not _MODEL_ID.fullmatch(model_id):
            raise ValueError(
                "model_id must start with a letter or underscore and contain only "
                "letters, numbers, underscores, dots, and hyphens"
            )
        self.model_id = model_id
        self._history: list[Instruction] = []
        self._checkpoints: dict[str, _Checkpoint] = {}
        self._result_name: str | None = None
        self._model_json: str | None = None
        self._values: dict[str, Any] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def model_json(self) -> str:
        if self._model_json is None:
            raise RuntimeError("model has not been built")
        return self._model_json

    @property
    def result_value(self) -> Any:
        """Return the live committed result for in-process preview consumers."""
        if self._result_name is None or self._result_name not in self._values:
            raise RuntimeError("model has no committed result")
        return self._values[self._result_name]

    def named_value(self, name: str) -> Any:
        """Return a named live value from the committed model state.

        Preview effects may target an intermediate shape instead of the
        declared result.  This accessor keeps that lookup on the public DSL
        runtime boundary without exposing the internal value map.
        """
        try:
            return self._values[name]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"model has no committed shape {name!r}") from exc

    def snapshot(self) -> dict[str, Any]:
        """Return the durable state without live geometry handles."""
        return {
            "model": self.model_id,
            "revision": self.revision,
            "commands": [instruction.source.strip() for instruction in self._history],
            "result": self._result_name,
            "checkpoints": {
                label: {"instruction_count": checkpoint.instruction_count, "result": checkpoint.result_name}
                for label, checkpoint in self._checkpoints.items()
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        *,
        model_json: str | None = None,
    ) -> "AgentModel":
        """Restore durable control state and rebuild its named geometry values."""
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be an object")
        model = cls(str(snapshot.get("model", "")))
        commands = snapshot.get("commands")
        if not isinstance(commands, list) or not all(
            isinstance(command, str) for command in commands
        ):
            raise ValueError("snapshot commands must be a list of strings")
        history: list[Instruction] = []
        for command in commands:
            parsed = parse(command)
            if len(parsed) != 1 or parsed[0].op in _EFFECT_OPS | {"rollback"}:
                raise ValueError("snapshot contains a non-durable command")
            history.append(parsed[0])

        values, result_name, rebuilt_json, _created = model._rebuild(history)
        expected_result = snapshot.get("result")
        if expected_result != result_name:
            raise ValueError("snapshot result does not match its command history")
        revision = snapshot.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("snapshot revision must be a non-negative integer")

        checkpoint_payload = snapshot.get("checkpoints", {})
        if not isinstance(checkpoint_payload, dict):
            raise ValueError("snapshot checkpoints must be an object")
        checkpoints: dict[str, _Checkpoint] = {}
        for label, payload in checkpoint_payload.items():
            if not isinstance(label, str) or not isinstance(payload, dict):
                raise ValueError("snapshot checkpoint is malformed")
            parsed_checkpoint = parse(f"checkpoint {label}")[0]
            count = payload.get("instruction_count")
            checkpoint_result = payload.get("result")
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or not 0 <= count <= len(history)
                or checkpoint_result is not None and not isinstance(checkpoint_result, str)
            ):
                raise ValueError(f"snapshot checkpoint {label!r} is malformed")
            checkpoints[label] = _Checkpoint(
                parsed_checkpoint.args[0], count, checkpoint_result
            )

        if model_json is not None:
            replayed = cad.replay_model_json(model_json, strict=True)
            if result_name is not None:
                if len(replayed) != 1:
                    raise ValueError(
                        "stored model JSON result count does not match snapshot"
                    )
                with tempfile.TemporaryDirectory(
                    prefix="cadflow-agent-restore-"
                ) as tmp:
                    rebuilt_step = Path(tmp) / "rebuilt.step"
                    stored_step = Path(tmp) / "stored.step"
                    cad.export_step(
                        shapes=values[result_name], filename=str(rebuilt_step)
                    )
                    cad.export_step(shapes=replayed[0], filename=str(stored_step))
                    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(
                        rebuilt_step, stored_step
                    )
                if not comparison.hard_gate_passed:
                    raise ValueError(
                        "stored model JSON geometry does not match snapshot history"
                    )
        model._history = history
        model._checkpoints = checkpoints
        model._result_name = result_name
        model._model_json = model_json if model_json is not None else rebuilt_json
        model._values = values
        model._revision = revision
        return model

    def apply(self, document: str) -> DSLResponse:
        """Validate and apply a DSL document as one revision."""
        try:
            instructions = parse(document)
            rollback_instructions = [item for item in instructions if item.op == "rollback"]
            if rollback_instructions:
                if len(instructions) != 1:
                    raise DSLExecutionError("rollback must be submitted as its own revision")
                return self.rollback(rollback_instructions[0].args[0])
            effect_seen = False
            for instruction in instructions:
                if instruction.op in _EFFECT_OPS:
                    effect_seen = True
                elif effect_seen and instruction.op in _GEOMETRY_OPS | {"tag"}:
                    raise DSLExecutionError(
                        f"line {instruction.line}: geometry and tag operations must "
                        "precede inspect/export/preview effects"
                    )
            durable = [item for item in instructions if item.op not in _EFFECT_OPS]
            effects = [item for item in instructions if item.op in _EFFECT_OPS]
            prospective = [*self._history, *durable]
            base_count = len(self._history)
            pending_checkpoints: dict[str, _Checkpoint] = {}
            pending_result = self._result_name
            for offset, instruction in enumerate(durable, 1):
                if instruction.op == "result":
                    pending_result = instruction.args[0]
                elif instruction.op == "checkpoint":
                    pending_checkpoints[instruction.args[0]] = _Checkpoint(
                        instruction.args[0], base_count + offset, pending_result
                    )
            if durable:
                evaluation = [*self._history, *instructions]
                (
                    values,
                    result_name,
                    model_json,
                    created,
                    inspections,
                    exports,
                    previews,
                ) = self._rebuild(evaluation, allow_effects=True)
            else:
                values, result_name, model_json, created = (
                    self._values,
                    self._result_name,
                    self._model_json,
                    [],
                )
                inspections, exports, previews = self._run_effects(effects, values)
            result_declared = any(
                instruction.op == "result" for instruction in durable
            )
            result_summary = (
                _shape_summary(values[result_name])
                if result_declared and result_name
                else None
            )
            if durable:
                self._history = prospective
                self._values = values
                self._result_name = result_name
                self._model_json = model_json
                self._revision += 1
                self._checkpoints.update(pending_checkpoints)
            new_names = {
                instruction.args[0]
                for instruction in durable
                if instruction.op in _GEOMETRY_OPS
            }
            return DSLResponse(
                model_id=self.model_id,
                revision=self._revision,
                status="ok",
                created=tuple(name for name in created if name in new_names),
                result=result_summary,
                inspections=tuple(inspections),
                exports=tuple(exports),
                previews=tuple(previews),
            )
        except (DSLParseError, DSLExecutionError, ValueError, TypeError, OSError) as exc:
            return DSLResponse(self.model_id, self._revision, "error", error=str(exc))

    def inspect(
        self,
        name: str,
        *,
        fields: Iterable[str] = (),
        limit: int = 12,
    ) -> DSLResponse:
        """Inspect one named shape without changing durable state or revision."""
        field_tuple = tuple(fields)
        try:
            if any(field not in _INSPECTION_FIELDS for field in field_tuple):
                raise DSLExecutionError("unknown inspect field")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_INSPECTION_ITEMS:
                raise DSLExecutionError(
                    f"inspect limit must be between 1 and {MAX_INSPECTION_ITEMS}"
                )
            shape = self._require(self._values, name, None)
            inspection = {
                "shape": name,
                "facts": _shape_summary(shape, fields=field_tuple, limit=limit),
            }
            return DSLResponse(
                self.model_id,
                self._revision,
                "ok",
                inspections=(inspection,),
            )
        except (DSLExecutionError, ValueError, TypeError, OSError) as exc:
            return DSLResponse(self.model_id, self._revision, "error", error=str(exc))

    def export_step(self, name: str, path: str | Path) -> DSLResponse:
        """Export one named shape without changing durable state or revision."""
        try:
            shape = self._require(self._values, name, None)
            exported = self._write_step(shape, path)
            return DSLResponse(
                self.model_id,
                self._revision,
                "ok",
                exports=(exported,),
            )
        except (DSLExecutionError, ValueError, TypeError, OSError) as exc:
            return DSLResponse(self.model_id, self._revision, "error", error=str(exc))

    def rollback(self, label: str) -> DSLResponse:
        checkpoint = self._checkpoints.get(label)
        if checkpoint is None:
            return DSLResponse(self.model_id, self._revision, "error", error=f"unknown checkpoint {label!r}")
        history = self._history[: checkpoint.instruction_count]
        try:
            values, result_name, model_json, created = self._rebuild(history)
            result_summary = (
                _shape_summary(values[result_name]) if result_name else None
            )
        except (DSLExecutionError, ValueError, TypeError, OSError) as exc:
            return DSLResponse(self.model_id, self._revision, "error", error=str(exc))
        self._history = history
        self._values, self._result_name, self._model_json = values, result_name, model_json
        self._checkpoints = {
            name: checkpoint
            for name, checkpoint in self._checkpoints.items()
            if checkpoint.instruction_count <= len(history)
        }
        self._revision += 1
        return DSLResponse(
            self.model_id,
            self._revision,
            "ok",
            tuple(created),
            result_summary,
        )

    def _rebuild(
        self,
        history: list[Instruction],
        *,
        allow_effects: bool = False,
    ) -> tuple[dict[str, Any], str | None, str, list[str]] | tuple[
        dict[str, Any],
        str | None,
        str,
        list[str],
        list[dict[str, Any]],
        list[str],
        list[dict[str, Any]],
    ]:
        values: dict[str, Any] = {}
        result_name: str | None = None
        created: list[str] = []
        pending_effects: list[Instruction] = []
        with cad.GraphSession(graph_id=self.model_id) as session:
            for instruction in history:
                op, args = instruction.op, instruction.args
                try:
                    if op == "checkpoint":
                        continue
                    if op == "result":
                        self._require(values, args[0], instruction)
                        result_name = args[0]
                        continue
                    if op == "tag":
                        source = self._require(values, args[0], instruction)
                        values[args[0]] = cad.apply_tag(source, args[1])
                        continue
                    if op in _EFFECT_OPS:
                        if not allow_effects:
                            raise DSLExecutionError(
                                f"non-durable operation {op!r} in history"
                            )
                        self._require(values, args[0], instruction)
                        pending_effects.append(instruction)
                        continue
                    if op == "rollback":
                        raise DSLExecutionError("rollback cannot appear in history")
                    if args[0] in values:
                        raise DSLExecutionError(
                            f"line {instruction.line}: shape {args[0]!r} already exists"
                        )
                    value = self._execute_geometry(op, args, values, instruction)
                    values[args[0]] = value
                    created.append(args[0])
                except DSLExecutionError:
                    raise
                except Exception as exc:
                    raise DSLExecutionError(f"line {instruction.line}: {instruction.source.strip()}: {exc}") from exc
            if result_name is not None:
                session.capture_result(value=self._require(values, result_name, None))
            model_json = cad.export_model_json(session=session)
        if allow_effects:
            inspections, exports, previews = self._run_effects(pending_effects, values)
            return values, result_name, model_json, created, inspections, exports, previews
        return values, result_name, model_json, created

    def _run_effects(
        self, effects: Iterable[Instruction], values: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        inspections: list[dict[str, Any]] = []
        exports: list[str] = []
        previews: list[dict[str, Any]] = []
        for instruction in effects:
            args = instruction.args
            shape = self._require(values, args[0], instruction)
            if instruction.op == "inspect":
                inspections.append(
                    {
                        "shape": args[0],
                        "facts": _shape_summary(
                            shape, fields=args[1], limit=args[2]
                        ),
                    }
                )
            elif instruction.op == "export":
                exports.append(self._write_step(shape, args[2]))
            elif instruction.op == "preview":
                previews.append({"shape": args[0], "quality": args[1]})
        return inspections, exports, previews

    @staticmethod
    def _write_step(shape: Any, path: str | Path) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        cad.export_step(shapes=shape, filename=str(target))
        if not target.is_file() or target.stat().st_size == 0:
            raise DSLExecutionError(
                f"export did not create a non-empty file: {target}"
            )
        return str(target)

    @staticmethod
    def _require(values: dict[str, Any], name: str, instruction: Instruction | None) -> Any:
        if name not in values:
            prefix = f"line {instruction.line}: " if instruction else ""
            raise DSLExecutionError(f"{prefix}unknown shape {name!r}")
        return values[name]

    def _execute_geometry(self, op: str, args: tuple[Any, ...], values: dict[str, Any], instruction: Instruction) -> Any:
        if op == "box":
            _, width, height, depth, options = args
            return cad.make_box_rsolid(width, height, depth, bottom_face_center=options.get("at", (0, 0, 0)))
        if op == "cylinder":
            _, radius, height, options = args
            return cad.make_cylinder_rsolid(radius, height, bottom_face_center=options.get("at", (0, 0, 0)), axis=options.get("axis", (0, 0, 1)))
        if op == "cone":
            _, bottom_radius, height, options = args
            return cad.make_cone_rsolid(bottom_radius, height, top_radius=options.get("top_radius", 0.0), bottom_face_center=options.get("at", (0, 0, 0)), axis=options.get("axis", (0, 0, 1)))
        if op == "sphere":
            _, radius, options = args
            return cad.make_sphere_rsolid(radius, center=options.get("at", (0, 0, 0)))
        if op in {"cut", "union", "intersect"}:
            operands = [self._require(values, name, instruction) for name in args[1]]
            function = {"cut": cad.cut_rsolid, "union": cad.union_rsolid, "intersect": cad.intersect_rsolid}[op]
            return function(*operands)
        source = self._require(values, args[1], instruction)
        if op == "translate":
            return cad.translate_shape(source, args[2])
        if op == "rotate":
            options = args[3]
            return cad.rotate_shape(source, args[2], axis=options.get("axis", (0, 0, 1)), origin=options.get("origin", (0, 0, 0)))
        if op == "mirror":
            options = args[2]
            return cad.mirror_shape(
                source,
                options.get("origin", (0, 0, 0)),
                options["normal"],
            )
        if op == "fillet":
            edges = self._resolve_selection(
                source, args[3]["edges"], "edges", instruction
            )
            return cad.fillet_rsolid(source, edges, args[2])
        if op == "chamfer":
            edges = self._resolve_selection(
                source, args[3]["edges"], "edges", instruction
            )
            return cad.chamfer_rsolid(source, edges, args[2])
        if op == "shell":
            faces = self._resolve_selection(
                source, args[3]["faces"], "faces", instruction
            )
            return cad.shell_rsolid(source, faces, args[2])
        raise DSLExecutionError(f"line {instruction.line}: unsupported operation {op!r}")

    @staticmethod
    def _resolve_selection(
        source: Any,
        selection: tuple[str, Any],
        kind: str,
        instruction: Instruction,
    ) -> list[Any]:
        mode, value = selection
        if mode == "tag":
            if kind == "edges":
                selected = cad.select_edges_by_tag(source, value)
            else:
                selected = cad.select_faces_by_tag(source, value)
        else:
            members = list(
                source.get_edges() if kind == "edges" else source.get_faces()
            )
            invalid = [index for index in value if index >= len(members)]
            if invalid:
                raise DSLExecutionError(
                    f"line {instruction.line}: {kind} index {invalid[0]} is out of range "
                    f"for {len(members)} available items"
                )
            selected = [members[index] for index in value]
        if not selected:
            raise DSLExecutionError(
                f"line {instruction.line}: {kind} selection resolved to no items"
            )
        return list(selected)
