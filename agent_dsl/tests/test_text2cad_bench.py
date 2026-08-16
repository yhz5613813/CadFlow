from __future__ import annotations

from pathlib import Path

import pytest

from agent_dsl.benchmarks.text2cad_published import run_published_l2_case


def test_text2cad_bench_published_l2_multi_agent_case(tmp_path: Path):
    report = run_published_l2_case(tmp_path / "text2cad-l2")
    assert report.level == "L2"
    assert report.agent_count == 7
    assert report.proposal_count == 7
    assert report.execution_valid is True
    assert report.invalidity_rate == 0.0
    assert report.brep_hard_gate_passed is True
    assert report.target_minus_candidate_volume == pytest.approx(0.0, abs=1e-9)
    assert report.candidate_minus_target_volume == pytest.approx(0.0, abs=1e-9)
