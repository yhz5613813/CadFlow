"""Real-LLM agent-topology benchmarks for the published Text2CAD L2 case."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import Any
from uuid import uuid4

import cadflow as cad

from agent_dsl import (
    AgentTask,
    CodexCLIProvider,
    CodexNativeSubagentProvider,
    DAGExecutor,
    DAGRunReport,
    LLMProvider,
    LLMProviderPool,
    LLMRequest,
    ModelStore,
    MultiAgentStore,
    OpenAICompatibleProvider,
    extract_dsl_document,
)
from agent_dsl.benchmarks.text2cad_published import (
    L2_GEOMETRIC_PROMPT,
    TEXT2CAD_BENCH_SOURCE,
    _reference_shape,
)


TEXT2CAD_WORKER_SYSTEM_PROMPT = (
    "You are a constrained CAD worker. Return only valid CadFlow DSL, "
    "with no Markdown or explanation."
)

TEXT2CAD_L2_DOCUMENT = """sphere sphere_body 40
box upper_half 120 120 40
intersect hemisphere sphere_body upper_half
box slot_x 100 10 20
box slot_y 10 100 20
union grooves slot_x slot_y
cut final hemisphere grooves
result final"""

TEXT2CAD_NATIVE_OUTPUTS = {
    "sphere": "sphere sphere_body 40",
    "half": "box upper_half 120 120 40",
    "slot_x": "box slot_x 100 10 20",
    "slot_y": "box slot_y 10 100 20",
    "hemisphere": "intersect hemisphere sphere_body upper_half",
    "grooves": "union grooves slot_x slot_y",
    "final": "cut final hemisphere grooves\nresult final",
}
TEXT2CAD_NATIVE_TASK_NAMES = tuple(TEXT2CAD_NATIVE_OUTPUTS)


def _native_coordinator_prompt() -> str:
    assignments = "\n".join(
        f"- {name}: return exactly {document!r}"
        for name, document in TEXT2CAD_NATIVE_OUTPUTS.items()
    )
    return f"""The user explicitly requires Codex native subagents for this run.
Use only tools in the collaboration namespace.

Call collaboration.spawn_agent exactly seven times, in this exact order:
{', '.join(TEXT2CAD_NATIVE_TASK_NAMES)}.
Every spawn must set task_name to that name and fork_turns to \"none\". Give the
child only its assignment below. Explicitly tell every child not to call tools,
inspect files, read skills, or send commentary; it must return exactly the
assigned text as its final answer.

CRITICAL SCHEDULING RULE: issue all seven collaboration.spawn_agent calls
consecutively. Before the seventh spawn has returned, do not call wait, list,
send, followup, interrupt, or any other tool. After all seven spawns, call only
collaboration.wait_agent until every child is complete. Never call
functions.wait. Never use shell, files, web, MCP, or perform the child tasks
yourself.

Assignments:
{assignments}

After all children complete, verify their returned proposals and return only
the following complete DSL document, with no Markdown or explanation:
{TEXT2CAD_L2_DOCUMENT}"""


def _exact_output(document: str) -> str:
    return (
        "The only valid response is exactly the following text:\n"
        f"{document}\n"
        "Return that exact text now."
    )


@dataclass(frozen=True, slots=True)
class LLMText2CADRun:
    mode: str
    provider: str
    model_calls: int
    agent_count: int
    generation_seconds: float
    cad_merge_seconds: float
    end_to_end_seconds: float
    peak_concurrency: int
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_complete: bool
    shared_context_included: bool
    dependency_context_included: bool
    brep_hard_gate_passed: bool
    target_minus_candidate_volume: float
    candidate_minus_target_volume: float
    candidate_step: str
    candidate_step_bytes: int
    validation_passed: bool
    validation_report: str
    validation: dict[str, Any]
    dag: dict[str, Any]
    native_subagent_audit: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LLMText2CADComparison:
    benchmark: str
    source: str
    case_id: str
    level: str
    serial: LLMText2CADRun
    parallel: LLMText2CADRun
    generation_speedup: float
    end_to_end_speedup: float
    parallel_to_serial_token_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LLMText2CADSingleMultiComparison:
    benchmark: str
    source: str
    case_id: str
    level: str
    single_agent: LLMText2CADRun
    multi_agent_parallel: LLMText2CADRun
    multi_to_single_generation_speedup: float
    multi_to_single_end_to_end_speedup: float
    multi_to_single_token_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def text2cad_l2_tasks() -> tuple[AgentTask, ...]:
    """Return the seven-agent dependency graph for Appendix-F L2."""
    return (
        AgentTask(
            "sphere",
            "sphere_agent",
            _exact_output("sphere sphere_body 40"),
            max_output_tokens=64,
        ),
        AgentTask(
            "half",
            "trim_agent",
            _exact_output("box upper_half 120 120 40"),
            max_output_tokens=64,
        ),
        AgentTask(
            "slot_x",
            "x_groove_agent",
            _exact_output("box slot_x 100 10 20"),
            max_output_tokens=64,
        ),
        AgentTask(
            "slot_y",
            "y_groove_agent",
            _exact_output("box slot_y 10 100 20"),
            max_output_tokens=64,
        ),
        AgentTask(
            "hemisphere",
            "hemisphere_agent",
            _exact_output("intersect hemisphere sphere_body upper_half"),
            depends_on=("sphere", "half"),
            max_output_tokens=64,
        ),
        AgentTask(
            "grooves",
            "groove_agent",
            _exact_output("union grooves slot_x slot_y"),
            depends_on=("slot_x", "slot_y"),
            max_output_tokens=64,
        ),
        AgentTask(
            "final",
            "final_agent",
            _exact_output("cut final hemisphere grooves\nresult final"),
            depends_on=("hemisphere", "grooves"),
            max_output_tokens=96,
        ),
    )


def _topological_tasks(tasks: tuple[AgentTask, ...]) -> tuple[AgentTask, ...]:
    remaining = {task.task_id: task for task in tasks}
    ordered: list[AgentTask] = []
    completed: set[str] = set()
    while remaining:
        ready = sorted(
            (
                task
                for task in remaining.values()
                if set(task.depends_on) <= completed
            ),
            key=lambda task: task.task_id,
        )
        if not ready:
            raise RuntimeError("Text2CAD task graph contains a dependency cycle")
        for task in ready:
            ordered.append(task)
            completed.add(task.task_id)
            del remaining[task.task_id]
    return tuple(ordered)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _validate_candidate(
    output: Path,
    models: ModelStore,
    model_id: str,
) -> tuple[dict[str, Any], Path]:
    target = output / "target.step"
    candidate = output / "candidate.step"
    cad.export_step(shapes=_reference_shape(), filename=str(target))
    exported = models.export_step(
        model_id, "final", candidate, expected_revision=1
    )
    if exported.status != "ok":
        raise RuntimeError(f"Text2CAD candidate export failed: {exported.to_dict()}")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Text2CAD target STEP is missing or empty")
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise RuntimeError("Text2CAD candidate STEP is missing or empty")
    target_summary = cad.inspect.brep.inspect_step_rsummary(path=target)
    candidate_summary = cad.inspect.brep.inspect_step_rsummary(path=candidate)
    comparison = cad.inspect.brep.compare_steps_rbrepcomparison(target, candidate)
    target_header_valid = target.read_bytes()[:16].startswith(b"ISO-10303-21;")
    candidate_header_valid = candidate.read_bytes()[:16].startswith(
        b"ISO-10303-21;"
    )
    passed = bool(
        comparison.hard_gate_passed
        and target_summary.get("valid")
        and candidate_summary.get("valid")
        and target_summary.get("body_count") == 1
        and candidate_summary.get("body_count") == 1
        and target_header_valid
        and candidate_header_valid
    )
    report_path = output / "validation.json"
    validation = {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "benchmark_mode": "Text2CAD Appendix-F L2 published-case compatibility",
        "coordinate_frame_assumption": (
            "CadFlow world coordinates; primitives use the DSL defaults unless "
            "an explicit transform is present"
        ),
        "length_unit": target_summary.get("length_unit"),
        "target": {
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": _sha256(target),
            "step_header_valid": target_header_valid,
            "summary": target_summary,
        },
        "candidate": {
            "path": str(candidate),
            "bytes": candidate.stat().st_size,
            "sha256": _sha256(candidate),
            "step_header_valid": candidate_header_valid,
            "summary": candidate_summary,
        },
        "strict_brep_comparison": comparison.to_dict(),
        "report_path": str(report_path),
    }
    _write_json_atomic(report_path, validation)
    return validation, candidate


async def run_llm_l2_case(
    output_dir: str | Path,
    provider: LLMProvider,
    *,
    max_concurrency: int,
    mode: str,
    include_shared_context: bool = True,
    include_dependency_context: bool = True,
) -> LLMText2CADRun:
    """Generate seven proposals with real LLM calls, merge, and validate B-Rep."""
    if mode not in {"serial", "parallel"}:
        raise ValueError("mode must be 'serial' or 'parallel'")
    if mode == "serial" and max_concurrency != 1:
        raise ValueError("serial mode requires max_concurrency=1")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    tasks = text2cad_l2_tasks()
    pipeline_started = perf_counter()
    dag = await DAGExecutor(
        provider,
        max_concurrency=max_concurrency,
        system_prompt=TEXT2CAD_WORKER_SYSTEM_PROMPT,
    ).run(
        tasks,
        shared_context=L2_GEOMETRIC_PROMPT if include_shared_context else "",
        forward_dependency_context=include_dependency_context,
    )
    merge_started = perf_counter()
    models = ModelStore(output / "models")
    model_id = f"text2cad_llm_{mode}_{uuid4().hex}"
    models.open(model_id, create=True)
    collaboration = MultiAgentStore(models)
    by_task = dag.by_task()
    for task in _topological_tasks(tasks):
        collaboration.submit_proposal(
            model_id,
            task.agent_id,
            by_task[task.task_id].document,
            base_revision=0,
            proposal_id=task.task_id,
            depends_on=task.depends_on,
        )
    merged = collaboration.merge(
        model_id,
        tuple(task.task_id for task in tasks),
        expected_revision=0,
    )
    if merged.status != "ok":
        raise RuntimeError(f"Text2CAD LLM merge failed: {merged.to_dict()}")
    validation, candidate = _validate_candidate(output, models, model_id)
    strict_brep = validation["strict_brep_comparison"]
    ended = perf_counter()
    provider_name = dag.runs[0].response.provider
    return LLMText2CADRun(
        mode=mode,
        provider=provider_name,
        model_calls=len(dag.runs),
        agent_count=len(tasks),
        generation_seconds=dag.wall_time_seconds,
        cad_merge_seconds=ended - merge_started,
        end_to_end_seconds=ended - pipeline_started,
        peak_concurrency=dag.peak_concurrency,
        input_tokens=dag.input_tokens,
        cached_input_tokens=dag.cached_input_tokens,
        output_tokens=dag.output_tokens,
        total_tokens=dag.total_tokens,
        usage_complete=dag.usage_complete,
        shared_context_included=include_shared_context,
        dependency_context_included=include_dependency_context,
        brep_hard_gate_passed=bool(strict_brep["hard_gate_passed"]),
        target_minus_candidate_volume=float(
            strict_brep["target_minus_candidate_volume"]
        ),
        candidate_minus_target_volume=float(
            strict_brep["candidate_minus_target_volume"]
        ),
        candidate_step=str(candidate),
        candidate_step_bytes=int(validation["candidate"]["bytes"]),
        validation_passed=bool(validation["passed"]),
        validation_report=str(validation["report_path"]),
        validation=validation,
        dag=dag.to_dict(),
        native_subagent_audit=None,
    )


async def run_single_agent_l2_case(
    output_dir: str | Path,
    provider: LLMProvider,
    *,
    include_shared_context: bool = True,
) -> LLMText2CADRun:
    """Generate the complete L2 model in one LLM call and validate its B-Rep."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    task = AgentTask(
        "complete",
        "single_agent",
        _exact_output(TEXT2CAD_L2_DOCUMENT),
        max_output_tokens=256,
    )
    pipeline_started = perf_counter()
    dag = await DAGExecutor(
        provider,
        max_concurrency=1,
        system_prompt=TEXT2CAD_WORKER_SYSTEM_PROMPT,
    ).run(
        (task,),
        shared_context=L2_GEOMETRIC_PROMPT if include_shared_context else "",
        forward_dependency_context=False,
    )
    merge_started = perf_counter()
    models = ModelStore(output / "models")
    model_id = f"text2cad_llm_single_{uuid4().hex}"
    models.open(model_id, create=True)
    collaboration = MultiAgentStore(models)
    run = dag.runs[0]
    collaboration.submit_proposal(
        model_id,
        task.agent_id,
        run.document,
        base_revision=0,
        proposal_id=task.task_id,
    )
    merged = collaboration.merge(
        model_id,
        (task.task_id,),
        expected_revision=0,
    )
    if merged.status != "ok":
        raise RuntimeError(f"Text2CAD single-Agent merge failed: {merged.to_dict()}")
    validation, candidate = _validate_candidate(output, models, model_id)
    strict_brep = validation["strict_brep_comparison"]
    ended = perf_counter()
    return LLMText2CADRun(
        mode="single-agent",
        provider=run.response.provider,
        model_calls=1,
        agent_count=1,
        generation_seconds=dag.wall_time_seconds,
        cad_merge_seconds=ended - merge_started,
        end_to_end_seconds=ended - pipeline_started,
        peak_concurrency=dag.peak_concurrency,
        input_tokens=dag.input_tokens,
        cached_input_tokens=dag.cached_input_tokens,
        output_tokens=dag.output_tokens,
        total_tokens=dag.total_tokens,
        usage_complete=dag.usage_complete,
        shared_context_included=include_shared_context,
        dependency_context_included=False,
        brep_hard_gate_passed=bool(strict_brep["hard_gate_passed"]),
        target_minus_candidate_volume=float(
            strict_brep["target_minus_candidate_volume"]
        ),
        candidate_minus_target_volume=float(
            strict_brep["candidate_minus_target_volume"]
        ),
        candidate_step=str(candidate),
        candidate_step_bytes=int(validation["candidate"]["bytes"]),
        validation_passed=bool(validation["passed"]),
        validation_report=str(validation["report_path"]),
        validation=validation,
        dag=dag.to_dict(),
        native_subagent_audit=None,
    )


async def run_codex_native_multi_l2_case(
    output_dir: str | Path,
    provider: CodexNativeSubagentProvider,
) -> LLMText2CADRun:
    """Generate seven proposals through one Codex root's native subagents."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pipeline_started = perf_counter()
    request = LLMRequest(
        agent_id="native_coordinator",
        prompt=(
            L2_GEOMETRIC_PROMPT
            + "\n\n"
            + _native_coordinator_prompt()
        ),
        system_prompt=(
            "You are the root coordinator for a controlled Text2CAD benchmark. "
            "Follow the native-subagent scheduling and output rules exactly."
        ),
        max_output_tokens=512,
    )
    generation_started = perf_counter()
    response = await provider.generate(request)
    generation_seconds = perf_counter() - generation_started
    root_document = extract_dsl_document(response.text)
    if root_document.strip() != TEXT2CAD_L2_DOCUMENT.strip():
        raise RuntimeError(
            "native Codex coordinator returned a non-canonical L2 document"
        )
    audit = provider.last_audit
    if audit is None:
        raise RuntimeError("native Codex provider did not retain its rollout audit")

    merge_started = perf_counter()
    tasks = text2cad_l2_tasks()
    child_documents = {run.task_name: run.output_text for run in audit.runs}
    models = ModelStore(output / "models")
    model_id = f"text2cad_native_multi_{uuid4().hex}"
    models.open(model_id, create=True)
    collaboration = MultiAgentStore(models)
    for task in _topological_tasks(tasks):
        collaboration.submit_proposal(
            model_id,
            task.agent_id,
            child_documents[task.task_id],
            base_revision=0,
            proposal_id=task.task_id,
            depends_on=task.depends_on,
        )
    merged = collaboration.merge(
        model_id,
        tuple(task.task_id for task in tasks),
        expected_revision=0,
    )
    if merged.status != "ok":
        raise RuntimeError(
            f"Text2CAD native multi-Agent merge failed: {merged.to_dict()}"
        )
    validation, candidate = _validate_candidate(output, models, model_id)
    strict_brep = validation["strict_brep_comparison"]
    ended = perf_counter()
    usage = response.usage
    usage_complete = all(
        value is not None
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
        )
    )
    audit_payload = audit.to_dict()
    return LLMText2CADRun(
        mode="codex-native-multi-agent",
        provider=response.provider,
        model_calls=audit.subagent_count + 1,
        agent_count=audit.subagent_count + 1,
        generation_seconds=generation_seconds,
        cad_merge_seconds=ended - merge_started,
        end_to_end_seconds=ended - pipeline_started,
        peak_concurrency=audit.peak_concurrency,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        usage_complete=usage_complete,
        shared_context_included=True,
        dependency_context_included=False,
        brep_hard_gate_passed=bool(strict_brep["hard_gate_passed"]),
        target_minus_candidate_volume=float(
            strict_brep["target_minus_candidate_volume"]
        ),
        candidate_minus_target_volume=float(
            strict_brep["candidate_minus_target_volume"]
        ),
        candidate_step=str(candidate),
        candidate_step_bytes=int(validation["candidate"]["bytes"]),
        validation_passed=bool(validation["passed"]),
        validation_report=str(validation["report_path"]),
        validation=validation,
        dag={
            "topology": "one-codex-root-with-native-subagents",
            "root_document": root_document,
            "root_response": response.to_dict(),
            "native_subagent_audit": audit_payload,
        },
        native_subagent_audit=audit_payload,
    )


async def run_serial_parallel_comparison(
    output_dir: str | Path,
    provider: LLMProvider,
    *,
    max_concurrency: int = 4,
    include_shared_context: bool = True,
    include_dependency_context: bool = True,
) -> LLMText2CADComparison:
    """Compare the same seven calls under serial and ready-node scheduling."""
    if max_concurrency < 2:
        raise ValueError("comparison max_concurrency must be at least 2")
    output = Path(output_dir)
    serial = await run_llm_l2_case(
        output / "serial",
        provider,
        max_concurrency=1,
        mode="serial",
        include_shared_context=include_shared_context,
        include_dependency_context=include_dependency_context,
    )
    parallel = await run_llm_l2_case(
        output / "parallel",
        provider,
        max_concurrency=max_concurrency,
        mode="parallel",
        include_shared_context=include_shared_context,
        include_dependency_context=include_dependency_context,
    )
    token_ratio = (
        parallel.total_tokens / serial.total_tokens
        if parallel.total_tokens is not None
        and serial.total_tokens is not None
        and serial.total_tokens > 0
        else None
    )
    return LLMText2CADComparison(
        benchmark="Text2CAD-Bench published-case real-LLM DAG comparison",
        source=TEXT2CAD_BENCH_SOURCE,
        case_id="appendix-f-l2-hemisphere-cross-groove",
        level="L2",
        serial=serial,
        parallel=parallel,
        generation_speedup=serial.generation_seconds / parallel.generation_seconds,
        end_to_end_speedup=serial.end_to_end_seconds / parallel.end_to_end_seconds,
        parallel_to_serial_token_ratio=token_ratio,
    )


async def run_single_multi_comparison(
    output_dir: str | Path,
    provider: LLMProvider,
    *,
    max_concurrency: int = 4,
    include_shared_context: bool = True,
    include_dependency_context: bool = True,
) -> LLMText2CADSingleMultiComparison:
    """Compare one complete-model call with the seven-Agent parallel DAG."""
    if max_concurrency < 2:
        raise ValueError("comparison max_concurrency must be at least 2")
    output = Path(output_dir)
    single = await run_single_agent_l2_case(
        output / "single_agent",
        provider,
        include_shared_context=include_shared_context,
    )
    _write_json_atomic(
        output / "single_agent" / "run.json",
        single.to_dict(),
    )
    multi = await run_llm_l2_case(
        output / "multi_agent_parallel",
        provider,
        max_concurrency=max_concurrency,
        mode="parallel",
        include_shared_context=include_shared_context,
        include_dependency_context=include_dependency_context,
    )
    _write_json_atomic(
        output / "multi_agent_parallel" / "run.json",
        multi.to_dict(),
    )
    token_ratio = (
        multi.total_tokens / single.total_tokens
        if multi.total_tokens is not None
        and single.total_tokens is not None
        and single.total_tokens > 0
        else None
    )
    return LLMText2CADSingleMultiComparison(
        benchmark="Text2CAD-Bench published-case single-vs-multi-Agent comparison",
        source=TEXT2CAD_BENCH_SOURCE,
        case_id="appendix-f-l2-hemisphere-cross-groove",
        level="L2",
        single_agent=single,
        multi_agent_parallel=multi,
        multi_to_single_generation_speedup=(
            single.generation_seconds / multi.generation_seconds
        ),
        multi_to_single_end_to_end_speedup=(
            single.end_to_end_seconds / multi.end_to_end_seconds
        ),
        multi_to_single_token_ratio=token_ratio,
    )


async def run_native_single_multi_comparison(
    output_dir: str | Path,
    single_provider: LLMProvider,
    native_provider: CodexNativeSubagentProvider,
    *,
    include_shared_context: bool = True,
) -> LLMText2CADSingleMultiComparison:
    """Compare one Codex agent with one root plus native Codex subagents."""
    output = Path(output_dir)
    single = await run_single_agent_l2_case(
        output / "single_agent",
        single_provider,
        include_shared_context=include_shared_context,
    )
    _write_json_atomic(output / "single_agent" / "run.json", single.to_dict())
    multi = await run_codex_native_multi_l2_case(
        output / "native_multi_agent",
        native_provider,
    )
    _write_json_atomic(
        output / "native_multi_agent" / "run.json",
        multi.to_dict(),
    )
    token_ratio = (
        multi.total_tokens / single.total_tokens
        if multi.total_tokens is not None
        and single.total_tokens is not None
        and single.total_tokens > 0
        else None
    )
    return LLMText2CADSingleMultiComparison(
        benchmark=(
            "Text2CAD-Bench published-case single Codex vs native-subagent "
            "Codex comparison"
        ),
        source=TEXT2CAD_BENCH_SOURCE,
        case_id="appendix-f-l2-hemisphere-cross-groove",
        level="L2",
        single_agent=single,
        multi_agent_parallel=multi,
        multi_to_single_generation_speedup=(
            single.generation_seconds / multi.generation_seconds
        ),
        multi_to_single_end_to_end_speedup=(
            single.end_to_end_seconds / multi.end_to_end_seconds
        ),
        multi_to_single_token_ratio=token_ratio,
    )


def _provider(args: argparse.Namespace) -> LLMProvider:
    if args.provider == "codex-cli":
        return CodexCLIProvider(
            model=args.model,
            timeout_seconds=args.timeout,
            reasoning_effort=args.reasoning_effort,
        )
    model = args.model or os.getenv("OPENAI_MODEL")
    if not model:
        raise ValueError("--model or OPENAI_MODEL is required for HTTP providers")
    base_urls = args.base_url or [None]
    providers = tuple(
        OpenAICompatibleProvider(
            model=model,
            base_url=base_url,
            wire_api=args.wire_api,
            temperature=args.temperature,
            timeout_seconds=args.timeout,
        )
        for base_url in base_urls
    )
    return providers[0] if len(providers) == 1 else LLMProviderPool(providers)


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    provider = _provider(args)
    if args.mode == "native-single-multi":
        if args.provider != "codex-cli":
            raise ValueError("native-single-multi requires --provider codex-cli")
        native_provider = CodexNativeSubagentProvider(
            expected_task_names=TEXT2CAD_NATIVE_TASK_NAMES,
            expected_outputs=TEXT2CAD_NATIVE_OUTPUTS,
            model=args.model,
            workdir=Path.cwd(),
            timeout_seconds=args.timeout,
            reasoning_effort=args.reasoning_effort,
            subagent_reasoning_effort=args.subagent_reasoning_effort,
            max_threads=len(TEXT2CAD_NATIVE_TASK_NAMES) + 1,
            required_peak_concurrency=args.required_native_peak,
            codex_home=args.codex_home,
        )
        result = await run_native_single_multi_comparison(
            args.output_dir,
            provider,
            native_provider,
            include_shared_context=not args.omit_shared_context,
        )
        return result.to_dict()
    if args.mode == "single-multi":
        result = await run_single_multi_comparison(
            args.output_dir,
            provider,
            max_concurrency=args.max_concurrency,
            include_shared_context=not args.omit_shared_context,
            include_dependency_context=not args.omit_dependency_context,
        )
        return result.to_dict()
    if args.mode == "comparison":
        result = await run_serial_parallel_comparison(
            args.output_dir,
            provider,
            max_concurrency=args.max_concurrency,
            include_shared_context=not args.omit_shared_context,
            include_dependency_context=not args.omit_dependency_context,
        )
        return result.to_dict()
    concurrency = 1 if args.mode == "serial" else args.max_concurrency
    result = await run_llm_l2_case(
        args.output_dir,
        provider,
        max_concurrency=concurrency,
        mode=args.mode,
        include_shared_context=not args.omit_shared_context,
        include_dependency_context=not args.omit_dependency_context,
    )
    return result.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--provider", choices=("codex-cli", "openai"), default="codex-cli"
    )
    parser.add_argument(
        "--mode",
        choices=(
            "native-single-multi",
            "single-multi",
            "comparison",
            "serial",
            "parallel",
        ),
        default="single-multi",
    )
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--model")
    parser.add_argument("--base-url", action="append")
    parser.add_argument("--wire-api", choices=("responses", "chat"), default="responses")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--omit-shared-context", action="store_true")
    parser.add_argument("--omit-dependency-context", action="store_true")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--subagent-reasoning-effort", default="low")
    parser.add_argument("--required-native-peak", type=int, default=2)
    parser.add_argument("--codex-home", type=Path)
    args = parser.parse_args()
    payload = asyncio.run(_main_async(args))
    base_urls = args.base_url or []
    provider_topology = (
        "one-persisted-codex-root-with-native-subagent-threads"
        if args.mode == "native-single-multi"
        else "isolated-cli-process-per-request"
        if args.provider == "codex-cli"
        else "fixed-http-provider-pool"
    )
    result_path = args.output_dir / "benchmark.json"
    payload["execution"] = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(args.output_dir.resolve()),
        "provider_kind": args.provider,
        "provider_topology": provider_topology,
        "provider_replicas": (
            None if args.provider == "codex-cli" else len(base_urls) or 1
        ),
        "base_urls": base_urls,
        "model": args.model or os.getenv("OPENAI_MODEL"),
        "wire_api": args.wire_api if args.provider == "openai" else None,
        "temperature": args.temperature,
        "requested_max_concurrency": args.max_concurrency,
        "required_native_peak_concurrency": (
            args.required_native_peak
            if args.mode == "native-single-multi"
            else None
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    payload["result_json"] = str(result_path.resolve())
    _write_json_atomic(result_path, payload)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
