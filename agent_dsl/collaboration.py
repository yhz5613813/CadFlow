"""Small, deterministic coordination layer for multiple CadFlow agents.

Agents author independent durable DSL proposals.  The coordinator validates
their dependency graph and read/write sets, then submits one ordered document
to :class:`ModelStore` so the existing replay and geometry checks remain the
single execution boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from .parser import Instruction, parse
from .store import ModelStore


COLLABORATION_SCHEMA = "cadflow-multi-agent/1"
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_EFFECTS = {"inspect", "export"}
_GEOMETRY = {
    "box", "cylinder", "cone", "sphere", "cut", "union", "intersect",
    "translate", "rotate", "mirror", "fillet", "chamfer", "shell",
}


@dataclass(frozen=True, slots=True)
class AgentProposal:
    """An immutable, replayable contribution from one agent."""

    proposal_id: str
    model_id: str
    agent_id: str
    base_revision: int
    document: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    status: str = "pending"
    merged_revision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "proposal_id": self.proposal_id,
            "model_id": self.model_id,
            "agent_id": self.agent_id,
            "base_revision": self.base_revision,
            "document": self.document,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "depends_on": list(self.depends_on),
            "status": self.status,
        }
        if self.merged_revision is not None:
            payload["merged_revision"] = self.merged_revision
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentProposal":
        required = {
            "proposal_id", "model_id", "agent_id", "base_revision",
            "document", "reads", "writes", "depends_on", "status",
        }
        if not isinstance(payload, Mapping) or not required <= set(payload):
            raise ValueError("malformed multi-agent proposal")
        values = {
            "proposal_id": payload["proposal_id"],
            "model_id": payload["model_id"],
            "agent_id": payload["agent_id"],
            "base_revision": payload["base_revision"],
            "document": payload["document"],
            "reads": payload["reads"],
            "writes": payload["writes"],
            "depends_on": payload["depends_on"],
            "status": payload["status"],
            "merged_revision": payload.get("merged_revision"),
        }
        if (
            not all(isinstance(values[key], str) for key in ("proposal_id", "model_id", "agent_id", "document", "status"))
            or not isinstance(values["base_revision"], int)
            or isinstance(values["base_revision"], bool)
            or values["base_revision"] < 0
            or not all(isinstance(item, str) for item in values["reads"])
            or not all(isinstance(item, str) for item in values["writes"])
            or not all(isinstance(item, str) for item in values["depends_on"])
            or values["merged_revision"] is not None
            and (not isinstance(values["merged_revision"], int) or isinstance(values["merged_revision"], bool))
        ):
            raise ValueError("malformed multi-agent proposal fields")
        return cls(**values)


@dataclass(frozen=True, slots=True)
class CollaborationMessage:
    """A small structured mailbox item; payloads must be JSON-compatible."""

    message_id: str
    model_id: str
    sender: str
    recipient: str | None
    kind: str
    payload: Mapping[str, Any]
    proposal_id: str | None = None
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "model_id": self.model_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "kind": self.kind,
            "payload": dict(self.payload),
            "proposal_id": self.proposal_id,
            "sequence": self.sequence,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CollaborationMessage":
        required = {"message_id", "model_id", "sender", "recipient", "kind", "payload", "proposal_id", "sequence"}
        if not isinstance(payload, Mapping) or not required <= set(payload):
            raise ValueError("malformed collaboration message")
        if (
            not all(isinstance(payload[key], str) for key in ("message_id", "model_id", "sender", "kind"))
            or payload["recipient"] is not None and not isinstance(payload["recipient"], str)
            or payload["proposal_id"] is not None and not isinstance(payload["proposal_id"], str)
            or not isinstance(payload["payload"], Mapping)
            or not isinstance(payload["sequence"], int)
        ):
            raise ValueError("malformed collaboration message fields")
        return cls(
            message_id=payload["message_id"],
            model_id=payload["model_id"],
            sender=payload["sender"],
            recipient=payload["recipient"],
            kind=payload["kind"],
            payload=dict(payload["payload"]),
            proposal_id=payload["proposal_id"],
            sequence=payload["sequence"],
        )


@dataclass(frozen=True, slots=True)
class MergeConflict:
    proposal_ids: tuple[str, ...]
    resource: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposals": list(self.proposal_ids),
            "resource": self.resource,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MergeResponse:
    model_id: str
    revision: int
    status: str
    merged_proposals: tuple[str, ...] = ()
    conflicts: tuple[MergeConflict, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_id,
            "revision": self.revision,
            "status": self.status,
        }
        if self.merged_proposals:
            payload["merged_proposals"] = list(self.merged_proposals)
        if self.conflicts:
            payload["conflicts"] = [item.to_dict() for item in self.conflicts]
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a simple agent/model identifier")
    return value


def _analyze(instructions: Iterable[Instruction]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    reads: set[str] = set()
    writes: set[str] = set()
    for instruction in instructions:
        op, args = instruction.op, instruction.args
        if op in _EFFECTS:
            raise ValueError("proposals may contain durable modeling operations only")
        if op in {"rollback", "checkpoint"}:
            raise ValueError("rollback/checkpoint are coordinator operations, not proposals")
        if op == "result":
            reads.add(args[0])
            writes.add("$result")
        elif op == "tag":
            reads.add(args[0])
            writes.add(args[0])
        elif op in _GEOMETRY:
            writes.add(args[0])
            if op in {"cut", "union", "intersect"}:
                reads.update(args[1])
            elif op != "box" and op != "cylinder" and op != "cone" and op != "sphere":
                reads.add(args[1])
    return tuple(sorted(reads)), tuple(sorted(writes))


class MultiAgentStore:
    """Coordinate proposals while preserving ``ModelStore`` as the executor."""

    def __init__(self, models: ModelStore):
        self.models = models
        self.root = models.root / ".multiagent"
        self.root.mkdir(parents=True, exist_ok=True)

    def submit_proposal(
        self,
        model_id: str,
        agent_id: str,
        document: str,
        *,
        base_revision: int,
        proposal_id: str | None = None,
        depends_on: Iterable[str] = (),
    ) -> AgentProposal:
        model_id = _id(model_id, "model_id")
        agent_id = _id(agent_id, "agent_id")
        if not isinstance(base_revision, int) or isinstance(base_revision, bool) or base_revision < 0:
            raise ValueError("base_revision must be a non-negative integer")
        proposal_id = _id(proposal_id or f"proposal-{uuid4().hex}", "proposal_id")
        dependency_ids = tuple(dict.fromkeys(_id(item, "dependency") for item in depends_on))
        if proposal_id in dependency_ids:
            raise ValueError("proposal cannot depend on itself")
        instructions = parse(document)
        reads, writes = _analyze(instructions)
        with self._lock(model_id):
            model = self.models.open(model_id)
            if base_revision > model.revision:
                raise ValueError("base_revision is newer than the stored model")
            state = self._load(model_id)
            proposals = {item.proposal_id: item for item in state["proposals"]}
            if proposal_id in proposals:
                raise ValueError(f"proposal {proposal_id!r} already exists")
            missing = [item for item in dependency_ids if item not in proposals]
            if missing:
                raise ValueError(f"unknown proposal dependencies: {', '.join(missing)}")
            proposal = AgentProposal(
                proposal_id, model_id, agent_id, base_revision, document,
                reads, writes, dependency_ids,
            )
            state["proposals"].append(proposal)
            self._save(model_id, state)
            return proposal

    def list_proposals(self, model_id: str, *, status: str | None = None) -> tuple[AgentProposal, ...]:
        model_id = _id(model_id, "model_id")
        with self._lock(model_id):
            proposals = tuple(self._load(model_id)["proposals"])
        if status is not None:
            proposals = tuple(item for item in proposals if item.status == status)
        return tuple(sorted(proposals, key=lambda item: item.proposal_id))

    def merge(
        self,
        model_id: str,
        proposal_ids: Iterable[str],
        *,
        expected_revision: int,
    ) -> MergeResponse:
        model_id = _id(model_id, "model_id")
        selected_ids = tuple(dict.fromkeys(_id(item, "proposal_id") for item in proposal_ids))
        if not selected_ids:
            raise ValueError("merge requires at least one proposal")
        with self._lock(model_id):
            model = self.models.open(model_id)
            state = self._load(model_id)
            by_id = {item.proposal_id: item for item in state["proposals"]}
            missing = [item for item in selected_ids if item not in by_id]
            if missing:
                return MergeResponse(model_id, model.revision, "error", error=f"unknown proposals: {', '.join(missing)}")
            selected = {item: by_id[item] for item in selected_ids}
            if any(item.status != "pending" for item in selected.values()):
                return MergeResponse(model_id, model.revision, "error", error="all proposals must be pending")
            if any(item.base_revision != expected_revision for item in selected.values()):
                return MergeResponse(model_id, model.revision, "error", error="proposals do not share expected base_revision")
            if model.revision != expected_revision:
                return MergeResponse(model_id, model.revision, "error", error=f"revision conflict: expected {expected_revision}, current {model.revision}")
            missing_deps = sorted({dep for item in selected.values() for dep in item.depends_on if dep not in selected})
            if missing_deps:
                return MergeResponse(model_id, model.revision, "conflict", conflicts=(MergeConflict(selected_ids, "$dependencies", f"missing selected dependencies: {', '.join(missing_deps)}"),))
            order, cycle = self._topological_order(selected)
            if cycle:
                return MergeResponse(model_id, model.revision, "conflict", conflicts=(MergeConflict(tuple(cycle), "$dependencies", "dependency cycle"),))
            conflicts = self._conflicts(selected, order)
            if conflicts:
                return MergeResponse(model_id, model.revision, "conflict", conflicts=tuple(conflicts))
            document = "\n".join(selected[item].document.strip() for item in order)
            response = self.models.apply(model_id, document, expected_revision=expected_revision)
            if response.status != "ok":
                return MergeResponse(model_id, response.revision, "error", error=response.error)
            merged = set(selected_ids)
            state["proposals"] = [
                AgentProposal(
                    item.proposal_id, item.model_id, item.agent_id, item.base_revision,
                    item.document, item.reads, item.writes, item.depends_on,
                    "merged" if item.proposal_id in merged else item.status,
                    response.revision if item.proposal_id in merged else item.merged_revision,
                )
                for item in state["proposals"]
            ]
            self._save(model_id, state)
            return MergeResponse(model_id, response.revision, "ok", selected_ids, result=response.result)

    def send_message(
        self,
        model_id: str,
        sender: str,
        kind: str,
        payload: Mapping[str, Any],
        *,
        recipient: str | None = None,
        proposal_id: str | None = None,
        message_id: str | None = None,
    ) -> CollaborationMessage:
        model_id = _id(model_id, "model_id")
        sender = _id(sender, "sender")
        if recipient is not None:
            recipient = _id(recipient, "recipient")
        if not isinstance(kind, str) or not kind:
            raise ValueError("message kind must be non-empty")
        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("message payload must be JSON-compatible") from exc
        message = CollaborationMessage(
            _id(message_id or f"message-{uuid4().hex}", "message_id"),
            model_id, sender, recipient, kind, dict(payload), proposal_id,
        )
        with self._lock(model_id):
            state = self._load(model_id)
            message = CollaborationMessage(
                message.message_id, message.model_id, message.sender,
                message.recipient, message.kind, message.payload,
                message.proposal_id, state["next_sequence"],
            )
            state["next_sequence"] += 1
            state["messages"].append(message)
            self._save(model_id, state)
        return message

    def messages(self, model_id: str, *, recipient: str | None = None, after: int = -1) -> tuple[CollaborationMessage, ...]:
        model_id = _id(model_id, "model_id")
        with self._lock(model_id):
            messages = tuple(self._load(model_id)["messages"])
        return tuple(item for item in messages if item.sequence > after and (recipient is None or item.recipient in {None, recipient}))

    def _topological_order(self, selected: Mapping[str, AgentProposal]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        remaining = set(selected)
        order: list[str] = []
        while remaining:
            ready = sorted(item for item in remaining if not (set(selected[item].depends_on) & remaining))
            if not ready:
                return (), tuple(sorted(remaining))
            order.extend(ready)
            remaining.difference_update(ready)
        return tuple(order), ()

    @staticmethod
    def _ancestors(proposal_id: str, selected: Mapping[str, AgentProposal]) -> set[str]:
        result: set[str] = set()
        pending = list(selected[proposal_id].depends_on)
        while pending:
            item = pending.pop()
            if item in result or item not in selected:
                continue
            result.add(item)
            pending.extend(selected[item].depends_on)
        return result

    def _conflicts(self, selected: Mapping[str, AgentProposal], order: tuple[str, ...]) -> list[MergeConflict]:
        conflicts: list[MergeConflict] = []
        for index, left_id in enumerate(order):
            left = selected[left_id]
            left_ancestors = self._ancestors(left_id, selected)
            for right_id in order[index + 1:]:
                right = selected[right_id]
                right_ancestors = self._ancestors(right_id, selected)
                for resource in sorted(set(left.writes) & set(right.writes)):
                    conflicts.append(MergeConflict((left_id, right_id), resource, "both proposals write the same resource"))
                for resource in sorted(set(left.writes) & set(right.reads)):
                    if left_id not in right_ancestors:
                        conflicts.append(MergeConflict((left_id, right_id), resource, "reader must depend on writer"))
                for resource in sorted(set(right.writes) & set(left.reads)):
                    if right_id not in left_ancestors:
                        conflicts.append(MergeConflict((right_id, left_id), resource, "reader must depend on writer"))
        return conflicts

    @contextmanager
    def _lock(self, model_id: str) -> Iterator[None]:
        path = self.root / f".{model_id}.lock"
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, model_id: str) -> Path:
        return self.root / f"{model_id}.json"

    def _load(self, model_id: str) -> dict[str, Any]:
        path = self._path(model_id)
        if not path.exists():
            return {"proposals": [], "messages": [], "next_sequence": 0}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != COLLABORATION_SCHEMA:
            raise ValueError(f"unsupported collaboration file: {path}")
        return {
            "proposals": [AgentProposal.from_dict(item) for item in payload.get("proposals", [])],
            "messages": [CollaborationMessage.from_dict(item) for item in payload.get("messages", [])],
            "next_sequence": int(payload.get("next_sequence", 0)),
        }

    def _save(self, model_id: str, state: Mapping[str, Any]) -> None:
        payload = {
            "schema": COLLABORATION_SCHEMA,
            "proposals": [item.to_dict() for item in state["proposals"]],
            "messages": [item.to_dict() for item in state["messages"]],
            "next_sequence": state["next_sequence"],
        }
        descriptor, temporary_name = tempfile.mkstemp(dir=self.root, prefix=f".{model_id}.", suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(model_id))
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "AgentProposal",
    "CollaborationMessage",
    "COLLABORATION_SCHEMA",
    "MergeConflict",
    "MergeResponse",
    "MultiAgentStore",
]
