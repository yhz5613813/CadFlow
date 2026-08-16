"""Async LLM providers with provider-reported usage telemetry."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
import os
from pathlib import Path
import signal
from time import perf_counter
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when an LLM provider cannot complete a request."""


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Usage reported by the provider, not a local token estimate."""

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    agent_id: str
    prompt: str
    system_prompt: str
    model: str | None = None
    max_output_tokens: int = 256


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    usage: LLMUsage
    latency_seconds: float
    response_id: str | None = None
    provider: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "usage": self.usage.to_dict(),
            "latency_seconds": self.latency_seconds,
            "response_id": self.response_id,
            "provider": self.provider,
        }


@dataclass(frozen=True, slots=True)
class NativeSubagentRun:
    task_name: str
    thread_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    output_text: str
    usage: LLMUsage
    tool_calls: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["usage"] = self.usage.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class NativeSubagentAudit:
    root_thread_id: str
    rollout_path: str
    runs: tuple[NativeSubagentRun, ...]
    peak_concurrency: int
    overlap_seconds: float
    root_usage: LLMUsage
    child_usage: LLMUsage
    total_usage: LLMUsage

    @property
    def subagent_count(self) -> int:
        return len(self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_thread_id": self.root_thread_id,
            "rollout_path": self.rollout_path,
            "subagent_count": self.subagent_count,
            "peak_concurrency": self.peak_concurrency,
            "overlap_seconds": self.overlap_seconds,
            "root_usage": self.root_usage.to_dict(),
            "child_usage": self.child_usage.to_dict(),
            "total_usage": self.total_usage.to_dict(),
            "runs": [run.to_dict() for run in self.runs],
        }


class LLMProvider(Protocol):
    """Minimal async interface consumed by the DAG executor."""

    async def generate(self, request: LLMRequest) -> LLMResponse: ...


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _responses_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    output = payload.get("output", ())
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content", ())
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                text = part.get("text")
                if isinstance(text, str) and part.get("type") in {
                    "output_text", "text"
                }:
                    chunks.append(text)
    if not chunks:
        raise LLMError("Responses API result contained no output text")
    return "".join(chunks)


def _responses_usage(payload: Mapping[str, Any]) -> LLMUsage:
    usage = payload.get("usage", {})
    if not isinstance(usage, Mapping):
        return LLMUsage()
    input_details = usage.get("input_tokens_details", {})
    output_details = usage.get("output_tokens_details", {})
    if not isinstance(input_details, Mapping):
        input_details = {}
    if not isinstance(output_details, Mapping):
        output_details = {}
    return LLMUsage(
        input_tokens=_integer(usage.get("input_tokens")),
        cached_input_tokens=_integer(input_details.get("cached_tokens")),
        output_tokens=_integer(usage.get("output_tokens")),
        reasoning_output_tokens=_integer(output_details.get("reasoning_tokens")),
        total_tokens=_integer(usage.get("total_tokens")),
    )


def _chat_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices", ())
    if not isinstance(choices, list) or not choices:
        raise LLMError("Chat Completions result contained no choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise LLMError("Chat Completions result contained a malformed choice")
    message = choice.get("message", {})
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise LLMError("Chat Completions result contained no message text")
    return message["content"]


def _chat_usage(payload: Mapping[str, Any]) -> LLMUsage:
    usage = payload.get("usage", {})
    if not isinstance(usage, Mapping):
        return LLMUsage()
    details = usage.get("prompt_tokens_details", {})
    completion = usage.get("completion_tokens_details", {})
    if not isinstance(details, Mapping):
        details = {}
    if not isinstance(completion, Mapping):
        completion = {}
    return LLMUsage(
        input_tokens=_integer(usage.get("prompt_tokens")),
        cached_input_tokens=_integer(details.get("cached_tokens")),
        output_tokens=_integer(usage.get("completion_tokens")),
        reasoning_output_tokens=_integer(completion.get("reasoning_tokens")),
        total_tokens=_integer(usage.get("total_tokens")),
    )


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise LLMError(f"LLM transport error: {exc.reason}") from exc
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMError("LLM endpoint returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise LLMError("LLM endpoint returned a non-object JSON result")
    return decoded


class OpenAICompatibleProvider:
    """Call a Responses or Chat Completions compatible HTTP endpoint."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        wire_api: str = "responses",
        temperature: float | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if wire_api not in {"responses", "chat"}:
            raise ValueError("wire_api must be 'responses' or 'chat'")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.default_model = model
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.wire_api = wire_api
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def endpoint(self) -> str:
        suffix = "/responses" if self.wire_api == "responses" else "/chat/completions"
        return self.base_url if self.base_url.endswith(suffix) else self.base_url + suffix

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        if self.wire_api == "responses":
            payload: dict[str, Any] = {
                "model": model,
                "input": [
                    {"role": "developer", "content": request.system_prompt},
                    {"role": "user", "content": request.prompt},
                ],
                "max_output_tokens": request.max_output_tokens,
            }
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.prompt},
                ],
                "max_tokens": request.max_output_tokens,
            }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.to_thread(
                    _post_json,
                    self.endpoint,
                    payload,
                    headers,
                    self.timeout_seconds,
                )
                break
            except LLMError as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
        else:  # pragma: no cover - loop always returns or raises
            raise LLMError(str(last_error))
        latency = perf_counter() - started
        text = _responses_text(result) if self.wire_api == "responses" else _chat_text(result)
        usage = _responses_usage(result) if self.wire_api == "responses" else _chat_usage(result)
        response_model = result.get("model")
        response_id = result.get("id")
        return LLMResponse(
            text=text,
            model=response_model if isinstance(response_model, str) else model,
            usage=usage,
            latency_seconds=latency,
            response_id=response_id if isinstance(response_id, str) else None,
            provider=f"openai-compatible-{self.wire_api}",
        )


class LLMProviderPool:
    """Lease independent provider replicas for real request parallelism."""

    def __init__(self, providers: tuple[LLMProvider, ...]) -> None:
        if not providers:
            raise ValueError("provider pool requires at least one provider")
        self.providers = providers
        self._available: asyncio.Queue[int] = asyncio.Queue()
        for index in range(len(providers)):
            self._available.put_nowait(index)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        index = await self._available.get()
        try:
            response = await self.providers[index].generate(request)
            return replace(
                response,
                provider=f"pool[{index}]/{response.provider}",
            )
        finally:
            self._available.put_nowait(index)


class CodexCLIProvider:
    """Run isolated Codex CLI turns and parse its JSONL usage events."""

    def __init__(
        self,
        *,
        model: str | None = None,
        executable: str = "codex",
        workdir: str | Path = "/tmp",
        timeout_seconds: float = 180.0,
        reasoning_effort: str = "low",
        extra_args: tuple[str, ...] = (),
        ephemeral: bool = True,
        allow_tools: bool = False,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.model = model
        self.executable = executable
        self.workdir = str(Path(workdir))
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.extra_args = extra_args
        self.ephemeral = ephemeral
        self.allow_tools = allow_tools
        self.environment = dict(environment) if environment is not None else None

    @staticmethod
    async def _kill_process_group(
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            # The process is already dead; do not let an inherited pipe delay
            # the caller's timeout error indefinitely.
            pass

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.model
        command = [
            self.executable,
            "exec",
        ]
        if self.ephemeral:
            command.append("--ephemeral")
        command.extend(
            (
                "--ignore-rules",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "-c",
                "mcp_servers.openaiDeveloperDocs.enabled=false",
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
                "--json",
            )
        )
        if model:
            command.extend(("--model", model))
        command.extend(self.extra_args)
        combined_prompt = (
            request.system_prompt.strip()
            + "\n\nTASK\n"
            + request.prompt.strip()
        )
        if not self.allow_tools:
            combined_prompt += (
                "\n\nDo not call tools. Return only the requested final text."
            )
        command.append(combined_prompt)
        started = perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workdir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
                env=(
                    {**os.environ, **self.environment}
                    if self.environment is not None
                    else None
                ),
            )
        except FileNotFoundError as exc:
            raise LLMError(f"Codex CLI executable not found: {self.executable}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            await self._kill_process_group(process)
            raise LLMError(
                f"Codex CLI request timed out after {self.timeout_seconds:g}s"
            ) from exc
        except asyncio.CancelledError:
            await self._kill_process_group(process)
            raise
        latency = perf_counter() - started
        events: list[Mapping[str, Any]] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, Mapping):
                events.append(event)
        failed = next(
            (event for event in reversed(events) if event.get("type") == "turn.failed"),
            None,
        )
        if process.returncode != 0 or failed is not None:
            detail = failed if failed is not None else stderr.decode("utf-8", errors="replace")[-1000:]
            raise LLMError(f"Codex CLI request failed: {detail}")
        text: str | None = None
        usage_payload: Mapping[str, Any] = {}
        response_id: str | None = None
        for event in events:
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                response_id = event["thread_id"]
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if (
                    isinstance(item, Mapping)
                    and item.get("type") == "agent_message"
                    and isinstance(item.get("text"), str)
                ):
                    text = item["text"]
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), Mapping):
                usage_payload = event["usage"]
        if text is None:
            detail = stderr.decode("utf-8", errors="replace")[-1000:]
            raise LLMError(f"Codex CLI produced no agent message: {detail}")
        input_tokens = _integer(usage_payload.get("input_tokens"))
        output_tokens = _integer(usage_payload.get("output_tokens"))
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return LLMResponse(
            text=text,
            model=model or "codex-config-default",
            usage=LLMUsage(
                input_tokens=input_tokens,
                cached_input_tokens=_integer(usage_payload.get("cached_input_tokens")),
                output_tokens=output_tokens,
                reasoning_output_tokens=_integer(
                    usage_payload.get("reasoning_output_tokens")
                ),
                total_tokens=total_tokens,
            ),
            latency_seconds=latency,
            response_id=response_id,
            provider="codex-cli",
        )


def _parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _find_rollout(codex_home: Path, thread_id: str) -> Path:
    matches = tuple(
        (codex_home / "sessions").rglob(f"*{thread_id}.jsonl")
    )
    if len(matches) != 1:
        raise LLMError(
            f"expected one persisted rollout for native root {thread_id}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _read_rollout(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping):
            rows.append(row)
    return rows


def _token_count_usage(row: Mapping[str, Any]) -> LLMUsage | None:
    if row.get("type") != "event_msg":
        return None
    payload = row.get("payload", {})
    if not isinstance(payload, Mapping) or payload.get("type") != "token_count":
        return None
    info = payload.get("info", {})
    total = info.get("total_token_usage", {}) if isinstance(info, Mapping) else {}
    if not isinstance(total, Mapping):
        return None
    return LLMUsage(
        input_tokens=_integer(total.get("input_tokens")),
        cached_input_tokens=_integer(total.get("cached_input_tokens")),
        output_tokens=_integer(total.get("output_tokens")),
        reasoning_output_tokens=_integer(total.get("reasoning_output_tokens")),
        total_tokens=_integer(total.get("total_tokens")),
    )


def _subtract_usage(final: LLMUsage, baseline: LLMUsage | None) -> LLMUsage:
    def subtract(field: str) -> int | None:
        value = getattr(final, field)
        prior = getattr(baseline, field) if baseline is not None else 0
        if value is None or prior is None or value < prior:
            return None
        return value - prior

    return LLMUsage(
        input_tokens=subtract("input_tokens"),
        cached_input_tokens=subtract("cached_input_tokens"),
        output_tokens=subtract("output_tokens"),
        reasoning_output_tokens=subtract("reasoning_output_tokens"),
        total_tokens=subtract("total_tokens"),
    )


def _sum_usage(usages: tuple[LLMUsage, ...]) -> LLMUsage:
    def total(field: str) -> int | None:
        values = tuple(getattr(usage, field) for usage in usages)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    return LLMUsage(
        input_tokens=total("input_tokens"),
        cached_input_tokens=total("cached_input_tokens"),
        output_tokens=total("output_tokens"),
        reasoning_output_tokens=total("reasoning_output_tokens"),
        total_tokens=total("total_tokens"),
    )


def _task_span(
    rows: list[Mapping[str, Any]],
    *,
    label: str,
) -> tuple[str, str, str, LLMUsage]:
    start_index: int | None = None
    started_at: str | None = None
    turn_id: str | None = None
    for index, row in enumerate(rows):
        payload = row.get("payload", {})
        if (
            row.get("type") == "event_msg"
            and isinstance(payload, Mapping)
            and payload.get("type") == "task_started"
            and isinstance(row.get("timestamp"), str)
            and isinstance(payload.get("turn_id"), str)
        ):
            start_index = index
            started_at = row["timestamp"]
            turn_id = payload["turn_id"]
            break
    if start_index is None or started_at is None or turn_id is None:
        raise LLMError(f"{label} rollout has no task_started event")

    complete_index: int | None = None
    completed_at: str | None = None
    output_text: str | None = None
    for index in range(start_index + 1, len(rows)):
        row = rows[index]
        payload = row.get("payload", {})
        if (
            row.get("type") == "event_msg"
            and isinstance(payload, Mapping)
            and payload.get("type") == "task_complete"
            and payload.get("turn_id") == turn_id
            and isinstance(row.get("timestamp"), str)
        ):
            complete_index = index
            completed_at = row["timestamp"]
            message = payload.get("last_agent_message")
            output_text = message if isinstance(message, str) else ""
            break
    if complete_index is None or completed_at is None or output_text is None:
        raise LLMError(f"{label} rollout has no task_complete event")

    baseline: LLMUsage | None = None
    for row in rows[:start_index]:
        usage = _token_count_usage(row)
        if usage is not None:
            baseline = usage
    final: LLMUsage | None = None
    for row in rows[start_index + 1 : complete_index + 1]:
        usage = _token_count_usage(row)
        if usage is not None:
            final = usage
    if final is None:
        raise LLMError(f"{label} rollout has no completed token_count event")
    return started_at, completed_at, output_text, _subtract_usage(final, baseline)


def _task_tool_calls(
    rows: list[Mapping[str, Any]],
    started_at: str,
    completed_at: str,
) -> tuple[str, ...]:
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    calls: list[str] = []
    for row in rows:
        timestamp = row.get("timestamp")
        payload = row.get("payload", {})
        if not isinstance(timestamp, str) or not isinstance(payload, Mapping):
            continue
        try:
            within_task = started <= _parse_timestamp(timestamp) <= completed
        except ValueError:
            continue
        if (
            within_task
            and row.get("type") == "response_item"
            and payload.get("type") in {"function_call", "custom_tool_call"}
        ):
            namespace = payload.get("namespace")
            name = payload.get("name")
            if isinstance(name, str):
                calls.append(
                    f"{namespace}.{name}" if isinstance(namespace, str) else name
                )
    return tuple(calls)


def audit_native_subagents(
    *,
    codex_home: Path,
    root_thread_id: str,
    expected_task_names: tuple[str, ...],
    expected_outputs: Mapping[str, str] | None = None,
    require_parallel: bool = True,
    required_peak_concurrency: int = 2,
    allow_child_tools: bool = False,
) -> NativeSubagentAudit:
    """Verify native collaboration spawns and child-thread time overlap."""
    rollout = _find_rollout(codex_home, root_thread_id)
    rows = _read_rollout(rollout)
    spawn_names: dict[str, str] = {}
    child_threads: dict[str, str] = {}
    for row in rows:
        payload = row.get("payload", {})
        if not isinstance(payload, Mapping):
            continue
        if (
            row.get("type") == "response_item"
            and payload.get("type") == "function_call"
            and payload.get("namespace") == "collaboration"
            and payload.get("name") == "spawn_agent"
        ):
            arguments = payload.get("arguments")
            call_id = payload.get("call_id")
            if isinstance(arguments, str) and isinstance(call_id, str):
                try:
                    decoded = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
                task_name = decoded.get("task_name")
                if isinstance(task_name, str):
                    spawn_names[call_id] = task_name
        if (
            row.get("type") == "event_msg"
            and payload.get("type") == "sub_agent_activity"
            and payload.get("kind") == "started"
        ):
            call_id = payload.get("event_id")
            thread_id = payload.get("agent_thread_id")
            if isinstance(call_id, str) and isinstance(thread_id, str):
                child_threads[call_id] = thread_id
    actual_names = tuple(sorted(spawn_names.values()))
    expected_names = tuple(sorted(expected_task_names))
    if actual_names != expected_names:
        raise LLMError(
            "native Codex subagent hard gate failed: "
            f"expected tasks {expected_names}, observed {actual_names}"
        )
    native_runs: list[NativeSubagentRun] = []
    for call_id, task_name in spawn_names.items():
        child = child_threads.get(call_id)
        if child is None:
            raise LLMError(
                f"native Codex subagent {task_name!r} has no started event"
            )
        thread_id = child
        child_rollout = _find_rollout(codex_home, thread_id)
        child_rows = _read_rollout(child_rollout)
        metadata = next(
            (
                row.get("payload")
                for row in child_rows
                if row.get("type") == "session_meta"
                and isinstance(row.get("payload"), Mapping)
            ),
            None,
        )
        source = metadata.get("source", {}) if isinstance(metadata, Mapping) else {}
        subagent = source.get("subagent", {}) if isinstance(source, Mapping) else {}
        spawn = subagent.get("thread_spawn", {}) if isinstance(subagent, Mapping) else {}
        expected_path_suffix = f"/{task_name}"
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("id") != thread_id
            or metadata.get("thread_source") != "subagent"
            or metadata.get("parent_thread_id") != root_thread_id
            or not isinstance(spawn, Mapping)
            or spawn.get("parent_thread_id") != root_thread_id
            or spawn.get("depth") != 1
            or not isinstance(spawn.get("agent_path"), str)
            or not spawn["agent_path"].endswith(expected_path_suffix)
        ):
            raise LLMError(
                f"native Codex child {task_name!r} is not a verified subagent "
                f"of root {root_thread_id}"
            )
        started_at, completed_at, output_text, usage = _task_span(
            child_rows,
            label=f"native Codex subagent {task_name!r}",
        )
        tool_calls = _task_tool_calls(child_rows, started_at, completed_at)
        if tool_calls and not allow_child_tools:
            raise LLMError(
                "native Codex subagent hard gate failed: "
                f"task {task_name!r} called tools {tool_calls}"
            )
        if expected_outputs is not None:
            expected = expected_outputs.get(task_name)
            if expected is None or output_text.strip() != expected.strip():
                raise LLMError(
                    "native Codex subagent hard gate failed: "
                    f"task {task_name!r} returned {output_text!r}, expected {expected!r}"
                )
        native_runs.append(
            NativeSubagentRun(
                task_name=task_name,
                thread_id=thread_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(
                    _parse_timestamp(completed_at) - _parse_timestamp(started_at)
                ),
                output_text=output_text,
                usage=usage,
                tool_calls=tool_calls,
            )
        )
    events = sorted(
        (
            (timestamp, delta)
            for run in native_runs
            for timestamp, delta in (
                (_parse_timestamp(run.started_at), 1),
                (_parse_timestamp(run.completed_at), -1),
            )
        ),
        key=lambda item: (item[0], item[1]),
    )
    active = 0
    peak = 0
    overlap = 0.0
    previous: float | None = None
    for timestamp, delta in events:
        if previous is not None and active >= 2:
            overlap += timestamp - previous
        active += delta
        peak = max(peak, active)
        previous = timestamp
    if required_peak_concurrency < 2:
        raise ValueError("required_peak_concurrency must be at least two")
    if require_parallel and (
        peak < required_peak_concurrency or overlap <= 0.0
    ):
        raise LLMError(
            "native Codex subagent hard gate failed: "
            f"required peak {required_peak_concurrency}, observed {peak} "
            f"with {overlap:g}s overlap"
        )
    _root_started, _root_completed, _root_output, root_usage = _task_span(
        rows,
        label="native Codex root",
    )
    child_usage = _sum_usage(tuple(run.usage for run in native_runs))
    total_usage = _sum_usage((root_usage, child_usage))
    return NativeSubagentAudit(
        root_thread_id=root_thread_id,
        rollout_path=str(rollout),
        runs=tuple(sorted(native_runs, key=lambda run: run.started_at)),
        peak_concurrency=peak,
        overlap_seconds=overlap,
        root_usage=root_usage,
        child_usage=child_usage,
        total_usage=total_usage,
    )


class CodexNativeSubagentProvider(CodexCLIProvider):
    """Run one Codex root that must fan out through native subagent tools."""

    def __init__(
        self,
        *,
        expected_task_names: tuple[str, ...],
        expected_outputs: Mapping[str, str] | None = None,
        model: str | None = None,
        executable: str = "codex",
        workdir: str | Path = ".",
        timeout_seconds: float = 600.0,
        reasoning_effort: str = "low",
        subagent_reasoning_effort: str = "low",
        max_threads: int | None = None,
        required_peak_concurrency: int = 2,
        allow_child_tools: bool = False,
        codex_home: str | Path | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> None:
        if (
            not expected_task_names
            or len(set(expected_task_names)) != len(expected_task_names)
            or any(not name.strip() for name in expected_task_names)
        ):
            raise ValueError("native provider requires expected subagent tasks")
        if expected_outputs is not None and set(expected_outputs) != set(expected_task_names):
            raise ValueError("expected_outputs must match expected_task_names")
        required_threads = len(expected_task_names) + 1
        if max_threads is None:
            max_threads = required_threads
        if max_threads < required_threads:
            raise ValueError(
                "max_threads must include the root and every consecutively spawned child"
            )
        native_args = (
            "--enable",
            "multi_agent",
            "--enable",
            "multi_agent_v2",
            "-c",
            f"agents.max_concurrent_threads_per_session={max_threads}",
            "-c",
            "agents.max_depth=1",
            "-c",
            (
                "agents.default_subagent_reasoning_effort="
                f'"{subagent_reasoning_effort}"'
            ),
        )
        if model:
            native_args += (
                "-c",
                f"agents.default_subagent_model={json.dumps(model)}",
            )
        configured_home = codex_home or os.getenv("CODEX_HOME")
        self.codex_home = (
            Path(configured_home) if configured_home else Path.home() / ".codex"
        )
        super().__init__(
            model=model,
            executable=executable,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
            extra_args=native_args + extra_args,
            ephemeral=False,
            allow_tools=True,
            environment={"CODEX_HOME": str(self.codex_home)},
        )
        self.expected_task_names = expected_task_names
        self.expected_outputs = dict(expected_outputs) if expected_outputs else None
        self.required_peak_concurrency = required_peak_concurrency
        self.allow_child_tools = allow_child_tools
        self.last_audit: NativeSubagentAudit | None = None
        self._generate_lock = asyncio.Lock()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        async with self._generate_lock:
            self.last_audit = None
            response = await super().generate(request)
            if response.response_id is None:
                raise LLMError("native Codex root did not report a thread id")
            audit = audit_native_subagents(
                codex_home=self.codex_home,
                root_thread_id=response.response_id,
                expected_task_names=self.expected_task_names,
                expected_outputs=self.expected_outputs,
                require_parallel=True,
                required_peak_concurrency=self.required_peak_concurrency,
                allow_child_tools=self.allow_child_tools,
            )
            self.last_audit = audit
            return replace(
                response,
                usage=audit.total_usage,
                provider="codex-cli-native-subagents",
            )


__all__ = [
    "CodexNativeSubagentProvider",
    "CodexCLIProvider",
    "LLMError",
    "LLMProvider",
    "LLMProviderPool",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "NativeSubagentAudit",
    "NativeSubagentRun",
    "OpenAICompatibleProvider",
    "audit_native_subagents",
]
