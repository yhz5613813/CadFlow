"""Machine-readable reports for Agent modeling loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    hint: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.hint:
            result["hint"] = self.hint
        if self.data:
            result["data"] = dict(self.data)
        return result


@dataclass(frozen=True)
class OperationReport:
    operation: str
    status: str
    output: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"ready", "success", "valid"} and not any(
            item.severity == "error" for item in self.diagnostics
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "ok": self.ok,
            "output": dict(self.output),
            "parameters": dict(self.parameters),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class OperationResult:
    shape: Any | None
    report: OperationReport

    @property
    def value(self) -> Any | None:
        """Alias that also covers scalar query operations."""
        return self.shape

    def to_dict(self) -> dict[str, Any]:
        result = self.report.to_dict()
        if self.shape is not None and hasattr(self.shape, "describe"):
            result["shape"] = self.shape.describe()
        return result
