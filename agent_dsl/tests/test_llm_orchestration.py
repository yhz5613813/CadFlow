from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
from pathlib import Path
import signal
from time import perf_counter

import pytest

from agent_dsl import (
    AgentTask,
    DAGExecutionError,
    DAGExecutor,
    LLMRequest,
    LLMProviderPool,
    LLMResponse,
    LLMUsage,
    extract_dsl_document,
)
from agent_dsl.llm import (
    CodexCLIProvider,
    CodexNativeSubagentProvider,
    LLMError,
    _chat_text,
    _chat_usage,
    _responses_text,
    _responses_usage,
    audit_native_subagents,
)


class DelayedProvider:
    def __init__(self, outputs: Mapping[str, str], delay: float = 0.04) -> None:
        self.outputs = outputs
        self.delay = delay
        self.calls: list[tuple[str, float, str]] = []
        self.active = 0
        self.max_active = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = perf_counter()
        self.calls.append((request.agent_id, started, request.prompt))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return LLMResponse(
                text=self.outputs[request.agent_id],
                model="fake-model",
                usage=LLMUsage(
                    input_tokens=10,
                    cached_input_tokens=2,
                    output_tokens=3,
                    reasoning_output_tokens=0,
                    total_tokens=13,
                ),
                latency_seconds=perf_counter() - started,
                response_id=request.agent_id,
                provider="delayed-test",
            )
        finally:
            self.active -= 1


def _tasks() -> tuple[AgentTask, ...]:
    return (
        AgentTask("body", "body_agent", "make body"),
        AgentTask("hole", "hole_agent", "make hole"),
        AgentTask(
            "finish",
            "finish_agent",
            "combine dependencies",
            depends_on=("body", "hole"),
        ),
    )


def _outputs() -> dict[str, str]:
    return {
        "body_agent": "box body 10 10 4",
        "hole_agent": "cylinder hole 1 6 at 0 0 -1",
        "finish_agent": "cut final body hole\nresult final",
    }


def test_ready_nodes_run_concurrently_and_dependency_context_is_forwarded():
    provider = DelayedProvider(_outputs())
    report = asyncio.run(DAGExecutor(provider, max_concurrency=2).run(_tasks()))

    assert report.peak_concurrency == 2
    assert report.wall_time_seconds < report.sum_agent_time_seconds * 0.8
    assert report.input_tokens == 30
    assert report.output_tokens == 9
    assert report.total_tokens == 39
    assert report.usage_complete
    finish_prompt = next(prompt for agent, _started, prompt in provider.calls if agent == "finish_agent")
    assert "box body 10 10 4" in finish_prompt
    assert "cylinder hole 1 6" in finish_prompt
    body_run = report.by_task()["body"]
    finish_run = report.by_task()["finish"]
    assert finish_run.started_offset_seconds >= body_run.finished_offset_seconds


def test_parallel_scheduler_accelerates_same_dag_over_serial_execution():
    serial = asyncio.run(
        DAGExecutor(DelayedProvider(_outputs()), max_concurrency=1).run(_tasks())
    )
    parallel = asyncio.run(
        DAGExecutor(DelayedProvider(_outputs()), max_concurrency=2).run(_tasks())
    )

    assert serial.wall_time_seconds / parallel.wall_time_seconds > 1.35
    assert serial.total_tokens == parallel.total_tokens


def test_provider_pool_leases_independent_replicas_exclusively():
    left = DelayedProvider(_outputs(), delay=0.02)
    right = DelayedProvider(_outputs(), delay=0.02)
    pool = LLMProviderPool((left, right))
    requests = (
        LLMRequest("body_agent", "x", "x"),
        LLMRequest("hole_agent", "x", "x"),
        LLMRequest("finish_agent", "x", "x"),
        LLMRequest("body_agent", "x", "x"),
    )

    async def generate_all():
        return await asyncio.gather(
            *(pool.generate(request) for request in requests)
        )

    responses = asyncio.run(generate_all())

    assert len(left.calls) == 2
    assert len(right.calls) == 2
    assert left.max_active == 1
    assert right.max_active == 1
    assert {response.provider for response in responses} == {
        "pool[0]/delayed-test",
        "pool[1]/delayed-test",
    }


def test_invalid_graph_and_invalid_llm_document_fail_before_merge():
    with pytest.raises(ValueError, match="unknown task dependencies"):
        asyncio.run(
            DAGExecutor(DelayedProvider(_outputs())).run(
                (AgentTask("finish", "finish_agent", "x", depends_on=("missing",)),)
            )
        )

    provider = DelayedProvider({"body_agent": "This is not DSL"})
    with pytest.raises(DAGExecutionError, match="agent task 'body' failed"):
        asyncio.run(
            DAGExecutor(provider).run((AgentTask("body", "body_agent", "x"),))
        )


def test_markdown_fence_is_accepted_only_when_contents_parse():
    assert extract_dsl_document("```dsl\nbox body 2 3 4\n```") == "box body 2 3 4"
    assert extract_dsl_document(
        "Created shape:\n```plaintext\nsphere body 2\n```"
    ) == "sphere body 2"
    assert extract_dsl_document(
        "Final output: box body 2 3 4"
    ) == "box body 2 3 4"
    with pytest.raises(DAGExecutionError, match="invalid CadFlow DSL"):
        extract_dsl_document("```dsl\nrun arbitrary_python()\n```")


def test_openai_wire_parsers_preserve_provider_usage():
    responses_payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "sphere ball 2"}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
            "input_tokens_details": {"cached_tokens": 8},
            "output_tokens_details": {"reasoning_tokens": 1},
        },
    }
    assert _responses_text(responses_payload) == "sphere ball 2"
    assert _responses_usage(responses_payload) == LLMUsage(20, 8, 5, 1, 25)

    chat_payload = {
        "choices": [{"message": {"content": "box cube 1 1 1"}}],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "total_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }
    assert _chat_text(chat_payload) == "box cube 1 1 1"
    assert _chat_usage(chat_payload) == LLMUsage(12, 4, 6, 2, 18)


def test_codex_cli_closes_stdin_and_parses_jsonl(monkeypatch):
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            stdout = b"\n".join(
                (
                    b'{"type":"thread.started","thread_id":"thread-1"}',
                    b'{"type":"item.completed","item":{"type":"agent_message","text":"box body 1 2 3"}}',
                    b'{"type":"turn.completed","usage":{"input_tokens":20,"cached_input_tokens":8,"output_tokens":5,"reasoning_output_tokens":1}}',
                )
            )
            return stdout, b""

    async def create_process(*command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    response = asyncio.run(
        CodexCLIProvider(model="gpt-5.6-sol").generate(
            LLMRequest("body_agent", "make a box", "emit DSL")
        )
    )

    _command, kwargs = calls[0]
    assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
    assert kwargs["start_new_session"] is (os.name == "posix")
    assert response.text == "box body 1 2 3"
    assert response.response_id == "thread-1"
    assert response.usage == LLMUsage(20, 8, 5, 1, 25)


def test_codex_cli_timeout_kills_process_group(monkeypatch):
    killed = []

    class Process:
        pid = 1234
        returncode = None
        calls = 0

        async def communicate(self):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(10)
            return b"", b""

    process = Process()

    async def create_process(*_command, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(
        "agent_dsl.llm.os.killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    with pytest.raises(LLMError, match="timed out"):
        asyncio.run(
            CodexCLIProvider(
                model="gpt-5.6-sol", timeout_seconds=0.001
            ).generate(LLMRequest("body_agent", "make a box", "emit DSL"))
        )

    assert killed == [(1234, signal.SIGKILL)]


def _write_rollout(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _token_row(timestamp: str, total: int) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total - 2,
                    "cached_input_tokens": total // 2,
                    "output_tokens": 2,
                    "reasoning_output_tokens": 1,
                    "total_tokens": total,
                }
            },
        },
    }


def test_native_subagent_audit_verifies_threads_overlap_outputs_and_incremental_usage(
    tmp_path,
):
    sessions = tmp_path / "sessions" / "2026" / "08" / "15"
    root = "root-thread"
    children = {"alpha": "child-alpha", "beta": "child-beta"}
    root_rows = [
        {
            "timestamp": "2026-08-15T00:00:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "root-turn"},
        }
    ]
    for index, (name, thread_id) in enumerate(children.items(), start=1):
        call_id = f"call-{name}"
        root_rows.extend(
            (
                {
                    "timestamp": f"2026-08-15T00:00:0{index}Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "namespace": "collaboration",
                        "name": "spawn_agent",
                        "call_id": call_id,
                        "arguments": json.dumps({"task_name": name}),
                    },
                },
                {
                    "timestamp": f"2026-08-15T00:00:0{index}Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "sub_agent_activity",
                        "kind": "started",
                        "event_id": call_id,
                        "agent_thread_id": thread_id,
                    },
                },
            )
        )
    root_rows.extend(
        (
            _token_row("2026-08-15T00:00:06Z", 50),
            {
                "timestamp": "2026-08-15T00:00:06Z",
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "root-turn",
                    "last_agent_message": "ALPHA|BETA",
                },
            },
        )
    )
    _write_rollout(sessions / "rollout-root-thread.jsonl", root_rows)

    spans = {
        "alpha": ("2026-08-15T00:00:01Z", "2026-08-15T00:00:04Z", "ALPHA"),
        "beta": ("2026-08-15T00:00:02Z", "2026-08-15T00:00:05Z", "BETA"),
    }
    for name, thread_id in children.items():
        started, completed, output = spans[name]
        _write_rollout(
            sessions / f"rollout-{thread_id}.jsonl",
            [
                {
                    "timestamp": "2026-08-15T00:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": thread_id,
                        "parent_thread_id": root,
                        "thread_source": "subagent",
                        "source": {
                            "subagent": {
                                "thread_spawn": {
                                    "parent_thread_id": root,
                                    "depth": 1,
                                    "agent_path": f"/root/{name}",
                                }
                            }
                        },
                    },
                },
                _token_row("2026-08-15T00:00:00Z", 100),
                {
                    "timestamp": started,
                    "type": "event_msg",
                    "payload": {
                        "type": "task_started",
                        "turn_id": f"turn-{name}",
                    },
                },
                _token_row(completed, 110),
                {
                    "timestamp": completed,
                    "type": "event_msg",
                    "payload": {
                        "type": "task_complete",
                        "turn_id": f"turn-{name}",
                        "last_agent_message": output,
                    },
                },
            ],
        )

    audit = audit_native_subagents(
        codex_home=tmp_path,
        root_thread_id=root,
        expected_task_names=("alpha", "beta"),
        expected_outputs={"alpha": "ALPHA", "beta": "BETA"},
    )

    assert audit.subagent_count == 2
    assert audit.peak_concurrency == 2
    assert audit.overlap_seconds == 2.0
    assert audit.root_usage.total_tokens == 50
    assert audit.child_usage.total_tokens == 20
    assert audit.total_usage.total_tokens == 70
    assert {run.output_text for run in audit.runs} == {"ALPHA", "BETA"}
    assert all(run.tool_calls == () for run in audit.runs)

    with pytest.raises(LLMError, match="required peak 3, observed 2"):
        audit_native_subagents(
            codex_home=tmp_path,
            root_thread_id=root,
            expected_task_names=("alpha", "beta"),
            expected_outputs={"alpha": "ALPHA", "beta": "BETA"},
            required_peak_concurrency=3,
        )


def test_native_provider_pins_v2_depth_model_home_and_thread_capacity(tmp_path):
    provider = CodexNativeSubagentProvider(
        expected_task_names=("alpha", "beta"),
        model="gpt-5.6-sol",
        codex_home=tmp_path,
    )

    assert provider.ephemeral is False
    assert provider.allow_tools is True
    assert provider.environment == {"CODEX_HOME": str(tmp_path)}
    arguments = " ".join(provider.extra_args)
    assert "multi_agent_v2" in arguments
    assert "agents.max_concurrent_threads_per_session=3" in arguments
    assert "agents.max_depth=1" in arguments
    assert 'agents.default_subagent_model="gpt-5.6-sol"' in arguments

    with pytest.raises(ValueError, match="root and every consecutively spawned"):
        CodexNativeSubagentProvider(
            expected_task_names=("alpha", "beta"),
            max_threads=2,
        )
