"""Hand-checked ranking budgets and temporal protocol guardrails."""
import copy

import numpy as np
from omegaconf import OmegaConf
import pandas as pd
import pytest

from b_model.backtest import budget_metrics, validate_protocol
from b_model.config import PROJECT_ROOT


def test_budget_is_per_snapshot_and_counts_misses_outside_top_k():
    frame = pd.DataFrame({"ts": ["2025-01-01T00:00:00Z"] * 3 + ["2025-01-02T00:00:00Z"] * 2,
        "cell_id": ["a", "b", "c", "a", "b"]})
    metric, daily = budget_metrics(frame, [.9, .8, .7, .3, .2], [0, 1, 1, 1, 0], 1)
    assert daily.alerts.tolist() == [1, 1]
    assert metric["hits"] == 1 and metric["false_alerts"] == 1
    assert metric["precision"] == .5 and metric["recall"] == pytest.approx(1 / 3)
    assert metric["random_expected_hits"] == pytest.approx(2 / 3 + 1 / 2)


def test_ties_are_label_blind_and_independent_of_input_row_order():
    frame = pd.DataFrame({"ts": ["2025-01-01T00:00:00Z"] * 3, "cell_id": ["c", "b", "a"]})
    first, _ = budget_metrics(frame, [.5] * 3, [1, 1, 0], 1)
    second, _ = budget_metrics(frame.iloc[::-1], [.5] * 3, [0, 1, 1], 1)
    assert first == second
    assert first["hits"] == 0 and first["boundary_tie_snapshots"] == 1


def test_small_quiet_pools_and_no_positive_windows_are_explicit():
    frame = pd.DataFrame({"ts": ["2025-01-01T00:00:00Z"], "cell_id": ["a"]})
    metric, _ = budget_metrics(frame, [.1], [0], 5)
    assert metric["alerts"] == 1 and metric["snapshots_below_budget"] == 1
    assert metric["recall"] is None and metric["lift_over_random"] is None
    empty, _ = budget_metrics(frame.iloc[:0], [], [], 5)
    assert empty["snapshots"] == 0 and empty["precision"] is None


def test_duplicate_cell_windows_and_bad_scores_fail():
    frame = pd.DataFrame({"ts": ["2025-01-01T00:00:00Z"] * 2, "cell_id": ["a", "a"]})
    with pytest.raises(ValueError, match="unique"):
        budget_metrics(frame, [.1, .2], [0, 1], 5)
    with pytest.raises(ValueError, match="finite"):
        budget_metrics(frame.iloc[:1], [np.nan], [0], 5)


def test_protocol_rejects_future_overlap_and_short_label_gaps():
    plan = OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT / "b_model/conf/backtest.yaml"))
    validate_protocol(plan)
    bad = copy.deepcopy(plan)
    bad["windows"][0]["train_end"] = bad["windows"][0]["calibration_start"]
    with pytest.raises(ValueError, match="embargo"):
        validate_protocol(bad)
    bad = copy.deepcopy(plan)
    bad["windows"][1] = dict(bad["windows"][0], name="overlap")
    with pytest.raises(ValueError, match="overlap"):
        validate_protocol(bad)
