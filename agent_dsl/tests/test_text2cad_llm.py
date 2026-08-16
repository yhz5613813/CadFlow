from __future__ import annotations

import asyncio
from time import perf_counter

from agent_dsl import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    NativeSubagentAudit,
    NativeSubagentRun,
)
from agent_dsl.benchmarks.text2cad_llm import (
    TEXT2CAD_L2_DOCUMENT,
    TEXT2CAD_NATIVE_OUTPUTS,
    run_codex_native_multi_l2_case,
    run_llm_l2_case,
    run_serial_parallel_comparison,
    run_single_multi_comparison,
)


class Text2CADProvider:
    outputs = {
        "sphere_agent": "sphere sphere_body 40",
        "trim_agent": "box upper_half 120 120 40",
        "x_groove_agent": "box slot_x 100 10 20",
        "y_groove_agent": "box slot_y 10 100 20",
        "hemisphere_agent": "intersect hemisphere sphere_body upper_half",
        "groove_agent": "union grooves slot_x slot_y",
        "final_agent": "cut final hemisphere grooves\nresult final",
        "single_agent": TEXT2CAD_L2_DOCUMENT,
    }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = perf_counter()
        await asyncio.sleep(0.002)
        return LLMResponse(
            self.outputs[request.agent_id],
            "test-model",
            LLMUsage(10, 0, 3, 0, 13),
            perf_counter() - started,
            request.agent_id,
            "text2cad-test",
        )


class NativeText2CADProvider:
    def __init__(self) -> None:
        child_usage = LLMUsage(70, 0, 21, 0, 91)
        root_usage = LLMUsage(20, 0, 5, 0, 25)
        self.last_audit = NativeSubagentAudit(
            root_thread_id="root-thread",
            rollout_path="/tmp/root-rollout.jsonl",
            runs=tuple(
                NativeSubagentRun(
                    task_name=name,
                    thread_id=f"thread-{name}",
                    started_at=f"2026-08-15T00:00:0{index}Z",
                    completed_at=f"2026-08-15T00:00:1{index}Z",
                    duration_seconds=10.0,
                    output_text=document,
                    usage=LLMUsage(10, 0, 3, 0, 13),
                    tool_calls=(),
                )
                for index, (name, document) in enumerate(
                    TEXT2CAD_NATIVE_OUTPUTS.items()
                )
            ),
            peak_concurrency=7,
            overlap_seconds=8.0,
            root_usage=root_usage,
            child_usage=child_usage,
            total_usage=LLMUsage(90, 0, 26, 0, 116),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            TEXT2CAD_L2_DOCUMENT,
            "gpt-5.6-sol",
            self.last_audit.total_usage,
            0.01,
            "root-thread",
            "codex-cli-native-subagents",
        )


def test_llm_generated_parallel_case_passes_strict_brep_gate(tmp_path):
    report = asyncio.run(
        run_llm_l2_case(
            tmp_path,
            Text2CADProvider(),
            max_concurrency=4,
            mode="parallel",
        )
    )
    assert report.model_calls == 7
    assert report.peak_concurrency == 4
    assert report.brep_hard_gate_passed
    assert report.target_minus_candidate_volume == 0.0
    assert report.candidate_minus_target_volume == 0.0
    assert report.candidate_step_bytes > 0
    assert report.validation_passed
    assert report.validation["length_unit"] == "mm"
    assert report.validation["target"]["summary"]["valid"] is True
    assert report.validation["candidate"]["summary"]["valid"] is True
    assert len(report.validation["target"]["sha256"]) == 64
    assert len(report.validation["candidate"]["sha256"]) == 64
    assert report.validation["target"]["step_header_valid"] is True
    assert report.validation["candidate"]["step_header_valid"] is True
    assert report.validation_report.endswith("validation.json")


def test_serial_parallel_comparison_reports_acceleration_and_equal_tokens(tmp_path):
    comparison = asyncio.run(
        run_serial_parallel_comparison(
            tmp_path, Text2CADProvider(), max_concurrency=4
        )
    )
    assert comparison.serial.peak_concurrency == 1
    assert comparison.parallel.peak_concurrency == 4
    assert comparison.generation_speedup > 1.5
    assert comparison.parallel_to_serial_token_ratio == 1.0
    assert comparison.serial.brep_hard_gate_passed
    assert comparison.parallel.brep_hard_gate_passed


def test_single_multi_comparison_uses_one_vs_seven_calls_and_validates_both(tmp_path):
    comparison = asyncio.run(
        run_single_multi_comparison(
            tmp_path, Text2CADProvider(), max_concurrency=4
        )
    )

    assert comparison.single_agent.agent_count == 1
    assert comparison.single_agent.model_calls == 1
    assert comparison.multi_agent_parallel.agent_count == 7
    assert comparison.multi_agent_parallel.model_calls == 7
    assert comparison.multi_agent_parallel.peak_concurrency == 4
    assert comparison.multi_to_single_token_ratio == 7.0
    assert comparison.single_agent.brep_hard_gate_passed
    assert comparison.multi_agent_parallel.brep_hard_gate_passed
    assert (tmp_path / "single_agent" / "run.json").is_file()
    assert (tmp_path / "multi_agent_parallel" / "run.json").is_file()


def test_native_codex_case_merges_child_outputs_and_records_rollout_audit(tmp_path):
    report = asyncio.run(
        run_codex_native_multi_l2_case(tmp_path, NativeText2CADProvider())
    )

    assert report.mode == "codex-native-multi-agent"
    assert report.model_calls == 8
    assert report.agent_count == 8
    assert report.peak_concurrency == 7
    assert report.total_tokens == 116
    assert report.native_subagent_audit is not None
    assert report.native_subagent_audit["subagent_count"] == 7
    assert report.brep_hard_gate_passed
    assert report.validation_passed
