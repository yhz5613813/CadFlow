from __future__ import annotations

from pathlib import Path

import pytest

from agent_dsl import compare_conversations, measure_conversation
from agent_dsl.benchmarks.context_total import run_benchmark


def test_measure_conversation_counts_whole_history_and_fixed_context():
    without_fixed = measure_conversation(("one", "two"), ("a", "b"))
    with_fixed = measure_conversation(
        ("one", "two"), ("a", "b"), fixed_context="shared instructions"
    )
    assert without_fixed.turns == 2
    assert without_fixed.final_window_tokens > without_fixed.request_tokens
    assert without_fixed.total_processed_tokens > without_fixed.final_window_tokens
    assert with_fixed.final_window_tokens > without_fixed.final_window_tokens
    assert with_fixed.cumulative_input_tokens > without_fixed.cumulative_input_tokens
    with pytest.raises(ValueError):
        measure_conversation(("one",), ())


def test_compare_conversations_reports_absolute_and_relative_savings():
    report = compare_conversations(
        ("long public python request with repeated complete history",),
        ("box a 1 1 1",),
        baseline_responses=("same",),
        dsl_responses=("same",),
    ).to_dict()
    savings = report["savings"]
    assert savings["request_tokens"] > 0
    assert 0 < savings["final_window_token_ratio"] < 1
    assert 0 < savings["total_processed_byte_ratio"] < 1


def test_real_six_turn_total_context_benchmark(tmp_path: Path):
    report = run_benchmark(tmp_path)
    scope = report["scope"]
    savings = report["savings"]
    assert scope["turns"] == 6
    assert scope["geometry_hard_gate_passed"] is True
    assert scope["target_minus_candidate_volume"] == pytest.approx(0.0, abs=1e-9)
    assert scope["candidate_minus_target_volume"] == pytest.approx(0.0, abs=1e-9)
    assert savings["final_window_tokens"] > 0
    assert savings["final_window_token_ratio"] >= 0.20
    assert savings["total_processed_token_ratio"] >= 0.20
    assert savings["wire_byte_ratio"] >= 0.20
    assert savings["total_processed_byte_ratio"] >= 0.20
