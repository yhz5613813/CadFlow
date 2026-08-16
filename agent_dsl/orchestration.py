"""Dependency-aware concurrent execution for LLM-authored CAD proposals."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import re
from time import perf_counter
from typing import Any, Iterable, Mapping

from .llm import LLMProvider, LLMRequest, LLMResponse
from .parser import DSLParseError, parse


_TASK_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_OP_START = re.compile(
    r"\b(?:box|cylinder|cone|sphere|cut|union|intersect|translate|rotate|"
    r"mirror|fillet|chamfer|shell|tag|result)\b"
)

CADFLOW_DSL_SYSTEM_PROMPT = """You are one worker in a CadFlow CAD pipeline.
Return only a valid CadFlow DSL document, with no Markdown or explanation.
Relevant exact syntax is:
box OUTPUT WIDTH HEIGHT DEPTH
sphere OUTPUT RADIUS
union OUTPUT INPUT1 INPUT2
intersect OUTPUT INPUT1 INPUT2
cut OUTPUT BASE TOOL
result SHAPE
Numbers never have a unit suffix. Each operation is one line. Use only the
shape names and dimensions requested by the task. Do not inspect, export,
checkpoint, rollback, add braces, or add punctuation."""


class DAGExecutionError(RuntimeError):
    """Raised when the task graph or one of its LLM calls fails."""


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_id: str
    agent_id: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    model: str | None = None
    max_output_tokens: int = 256

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentRun:
    task: AgentTask
    document: str
    response: LLMResponse
    started_offset_seconds: float
    finished_offset_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.finished_offset_seconds - self.started_offset_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "document": self.document,
            "response": self.response.to_dict(),
            "started_offset_seconds": self.started_offset_seconds,
            "finished_offset_seconds": self.finished_offset_seconds,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class DAGRunReport:
    runs: tuple[AgentRun, ...]
    wall_time_seconds: float
    sum_agent_time_seconds: float
    critical_path_seconds: float
    peak_concurrency: int
    max_concurrency: int
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_complete: bool

    def by_task(self) -> dict[str, AgentRun]:
        return {run.task.task_id: run for run in self.runs}

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": [run.to_dict() for run in self.runs],
            "wall_time_seconds": self.wall_time_seconds,
            "sum_agent_time_seconds": self.sum_agent_time_seconds,
            "critical_path_seconds": self.critical_path_seconds,
            "peak_concurrency": self.peak_concurrency,
            "max_concurrency": self.max_concurrency,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_complete": self.usage_complete,
        }


def extract_dsl_document(text: str) -> str:
    """Extract and validate one DSL document from a model response."""
    if not isinstance(text, str) or not text.strip():
        raise DAGExecutionError("LLM returned an empty CAD document")
    candidates = [match.strip() for match in _FENCE.findall(text)]
    candidates.append(text.strip())
    candidates.extend(text[match.start():].strip() for match in _OP_START.finditer(text))
    errors: list[str] = []
    for candidate in candidates:
        try:
            parse(candidate)
        except DSLParseError as exc:
            errors.append(str(exc))
        else:
            return candidate
    raise DAGExecutionError(f"LLM returned invalid CadFlow DSL: {errors[-1]}")


def _validated_tasks(tasks: Iterable[AgentTask]) -> dict[str, AgentTask]:
    by_id: dict[str, AgentTask] = {}
    for task in tasks:
        if not isinstance(task, AgentTask):
            raise TypeError("tasks must contain AgentTask values")
        if not _TASK_ID.fullmatch(task.task_id) or not _TASK_ID.fullmatch(task.agent_id):
            raise ValueError("task_id and agent_id must be simple identifiers")
        if task.task_id in by_id:
            raise ValueError(f"duplicate task id: {task.task_id}")
        if task.task_id in task.depends_on:
            raise ValueError(f"task {task.task_id!r} cannot depend on itself")
        if len(set(task.depends_on)) != len(task.depends_on):
            raise ValueError(f"task {task.task_id!r} has duplicate dependencies")
        by_id[task.task_id] = task
    if not by_id:
        raise ValueError("DAG execution requires at least one task")
    missing = sorted(
        {
            dependency
            for task in by_id.values()
            for dependency in task.depends_on
            if dependency not in by_id
        }
    )
    if missing:
        raise ValueError(f"unknown task dependencies: {', '.join(missing)}")
    indegree = {task_id: len(set(task.depends_on)) for task_id, task in by_id.items()}
    children: dict[str, list[str]] = {task_id: [] for task_id in by_id}
    for task in by_id.values():
        for dependency in task.depends_on:
            children[dependency].append(task.task_id)
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    visited: list[str] = []
    while ready:
        task_id = ready.pop(0)
        visited.append(task_id)
        for child in sorted(children[task_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(visited) != len(by_id):
        cycle = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        raise ValueError(f"task dependency cycle: {', '.join(cycle)}")
    return by_id


def _dependency_context(task: AgentTask, completed: Mapping[str, AgentRun]) -> str:
    if not task.depends_on:
        return ""
    sections = ["Dependency outputs are validated DSL and may be referenced by shape name:"]
    for dependency in task.depends_on:
        sections.append(f"[{dependency}]\n{completed[dependency].document}")
    return "\n\n".join(sections)


def _sum_optional(values: Iterable[int | None]) -> tuple[int | None, bool]:
    materialized = tuple(values)
    complete = all(value is not None for value in materialized)
    return (sum(value for value in materialized if value is not None) if complete else None, complete)


class DAGExecutor:
    """Run ready DAG nodes concurrently and cancel the graph on first failure."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_concurrency: int = 4,
        system_prompt: str = CADFLOW_DSL_SYSTEM_PROMPT,
    ) -> None:
        if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        self.provider = provider
        self.max_concurrency = max_concurrency
        self.system_prompt = system_prompt

    async def run(
        self,
        tasks: Iterable[AgentTask],
        *,
        shared_context: str = "",
        forward_dependency_context: bool = True,
    ) -> DAGRunReport:
        by_id = _validated_tasks(tasks)
        remaining = dict(by_id)
        completed: dict[str, AgentRun] = {}
        running: dict[asyncio.Task[AgentRun], str] = {}
        started = perf_counter()
        active = 0
        peak = 0

        async def invoke(task: AgentTask) -> AgentRun:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            run_started = perf_counter()
            dependency_context = (
                _dependency_context(task, completed)
                if forward_dependency_context
                else ""
            )
            prompt_parts = [part for part in (shared_context.strip(), dependency_context, task.prompt.strip()) if part]
            request = LLMRequest(
                agent_id=task.agent_id,
                prompt="\n\n".join(prompt_parts),
                system_prompt=self.system_prompt,
                model=task.model,
                max_output_tokens=task.max_output_tokens,
            )
            try:
                response = await self.provider.generate(request)
                document = extract_dsl_document(response.text)
            finally:
                active -= 1
            run_finished = perf_counter()
            return AgentRun(
                task=task,
                document=document,
                response=response,
                started_offset_seconds=run_started - started,
                finished_offset_seconds=run_finished - started,
            )

        try:
            while remaining or running:
                capacity = self.max_concurrency - len(running)
                ready = sorted(
                    (
                        task
                        for task in remaining.values()
                        if all(dependency in completed for dependency in task.depends_on)
                    ),
                    key=lambda item: item.task_id,
                )[:capacity]
                for task in ready:
                    del remaining[task.task_id]
                    future = asyncio.create_task(invoke(task))
                    running[future] = task.task_id
                if not running:
                    raise DAGExecutionError("task graph made no progress")
                done, _pending = await asyncio.wait(
                    tuple(running), return_when=asyncio.FIRST_COMPLETED
                )
                for future in done:
                    task_id = running.pop(future)
                    try:
                        completed[task_id] = future.result()
                    except Exception as exc:
                        for pending in running:
                            pending.cancel()
                        await asyncio.gather(*running, return_exceptions=True)
                        raise DAGExecutionError(
                            f"agent task {task_id!r} failed: {exc}"
                        ) from exc
        except BaseException:
            for future in running:
                if not future.done():
                    future.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            raise
        wall_time = perf_counter() - started
        ordered = tuple(sorted(completed.values(), key=lambda run: run.started_offset_seconds))
        critical: dict[str, float] = {}
        for task_id in _topological_ids(by_id):
            run = completed[task_id]
            prior = max((critical[item] for item in run.task.depends_on), default=0.0)
            critical[task_id] = prior + run.duration_seconds
        input_tokens, input_complete = _sum_optional(
            run.response.usage.input_tokens for run in ordered
        )
        cached_tokens, _cached_complete = _sum_optional(
            run.response.usage.cached_input_tokens for run in ordered
        )
        output_tokens, output_complete = _sum_optional(
            run.response.usage.output_tokens for run in ordered
        )
        total_tokens, total_complete = _sum_optional(
            run.response.usage.total_tokens for run in ordered
        )
        return DAGRunReport(
            runs=ordered,
            wall_time_seconds=wall_time,
            sum_agent_time_seconds=sum(run.duration_seconds for run in ordered),
            critical_path_seconds=max(critical.values()),
            peak_concurrency=peak,
            max_concurrency=self.max_concurrency,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_complete=(
                input_complete
                and output_complete
                and total_complete
            ),
        )


def _topological_ids(tasks: Mapping[str, AgentTask]) -> tuple[str, ...]:
    remaining = set(tasks)
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            task_id
            for task_id in remaining
            if set(tasks[task_id].depends_on) <= set(ordered)
        )
        if not ready:
            raise DAGExecutionError("task dependency cycle")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return tuple(ordered)


__all__ = [
    "AgentRun",
    "AgentTask",
    "CADFLOW_DSL_SYSTEM_PROMPT",
    "DAGExecutionError",
    "DAGExecutor",
    "DAGRunReport",
    "extract_dsl_document",
]
