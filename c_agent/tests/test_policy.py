"""Behavior tests for Role C live policy."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from contracts.validate import ROOT, validate_payload

from c_agent.agent import dispatch_live, dispatch_mock
from c_agent.policy import cells_adjacent, cluster_adjacent, decide, select_risk_per_cell
from c_agent.state_store import StateStore
from c_agent.water import load_water_catalogue, nearest_water_source

EXAMPLES = ROOT / "contracts" / "examples"
A_WATER = ROOT / "a_data" / "mock_water_sources.json"
A_WATER_CASES = ROOT / "a_data" / "fixtures" / "water_lookup_examples.json"


def _feature(cell_id: str, *, sm_delta: float, days_since_rain: int = 10, sm: float = 0.14) -> dict:
    lat, lon = (float(part) for part in cell_id.split("_"))
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "ts": "2026-10-17T09:00:00Z",
        "lat": lat,
        "lon": lon,
        "peat": {"peat_fraction": 0.5, "peat_area_km2": 5.0, "polygon_ids": ["{TEST}"]},
        "weather": {
            "temp_c": 34.0,
            "precip_mm": 0.0,
            "wind_kmh": 10.0,
            "wind_dir_deg": 90,
            "sm_0_1": 0.1,
            "sm_1_3": 0.1,
            "sm_3_9": 0.1,
            "sm_9_27": 0.1,
            "sm_27_81": sm,
            "vpd_kpa": 2.0,
            "soil_temp_0_c": 35.0,
            "soil_temp_18_c": 30.0,
            "et_mm": 0.3,
            "et0_mm": 0.4,
        },
        "derived": {
            "rain_24h_mm": 0.0,
            "rain_7d_mm": 0.0,
            "rain_30d_mm": 10.0,
            "days_since_rain": days_since_rain,
            "sm_27_81_delta_7d": sm_delta,
            "vpd_mean_24h": 2.0,
            "soil_air_temp_gap_c": -1.0,
        },
        "fire": {
            "hotspots_in_cell_24h": 0,
            "hotspots_10km_7d": 0,
            "frp_sum_10km_7d": 0.0,
            "nearest_hotspot_km": 20.0,
        },
    }


def _risk(cell_id: str, horizon_h: int, score: float, level: str) -> dict:
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "ts": "2026-10-17T09:00:00Z",
        "horizon_h": horizon_h,
        "risk_score": score,
        "risk_level": level,
        "top_factors": [{"feature": "days_since_rain", "contribution": 0.3}],
        "model_version": "v1",
    }


class PolicyUnitTests(unittest.TestCase):
    def test_adjacency_and_clustering(self) -> None:
        # 0.1° latitude difference ≈ 11 km, so these are within 15 km
        self.assertTrue(cells_adjacent("-2.35_114.05", "-2.35_114.15", 15.0))
        # 0.1° in both directions ≈ 15.5 km, just over 15 km
        self.assertFalse(cells_adjacent("-2.35_114.05", "-2.45_114.15", 15.0))
        # But within 20 km
        self.assertTrue(cells_adjacent("-2.35_114.05", "-2.45_114.15", 20.0))
        groups = cluster_adjacent(["-2.35_114.15", "-2.35_114.05", "-2.55_114.25"], 15.0)
        self.assertEqual(groups, [["-2.35_114.05", "-2.35_114.15"], ["-2.55_114.25"]])

    def test_horizon_prefers_highest_score_then_shortest(self) -> None:
        selected = select_risk_per_cell(
            [
                _risk("-2.35_114.05", 72, 0.87, "CRITICAL"),
                _risk("-2.35_114.05", 48, 0.87, "CRITICAL"),
                _risk("-2.35_114.05", 24, 0.72, "HIGH"),
            ]
        )
        self.assertEqual(selected["-2.35_114.05"]["horizon_h"], 48)

    def test_critical_dispatch_has_five_audiences(self) -> None:
        features = [_feature("-2.35_114.05", sm_delta=-0.06, days_since_rain=22)]
        risk = [
            _risk("-2.35_114.05", 24, 0.72, "HIGH"),
            _risk("-2.35_114.05", 48, 0.87, "CRITICAL"),
            _risk("-2.35_114.05", 72, 0.91, "CRITICAL"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
            payload, created = decide(
                features,
                risk,
                state,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
                water_catalogue_path=A_WATER,
            )
        validate_payload("dispatch", payload)
        self.assertEqual(len(payload), 1)
        self.assertEqual(len(created), 1)
        row = payload[0]
        self.assertEqual(row["action"], "DISPATCH")
        self.assertEqual(row["priority"], 1)
        self.assertEqual(
            row["water_source"],
            {"lat": -2.33, "lon": 114.02, "distance_km": 4.007, "kind": "canal"},
        )
        self.assertEqual(len(row["audiences"]), 5)
        self.assertEqual(set(row["messages"]), set(row["audiences"]))

    def test_matches_role_a_water_lookup_examples(self) -> None:
        catalogue = {row["source_id"]: row for row in load_water_catalogue(A_WATER)}
        cases = json.loads(A_WATER_CASES.read_text(encoding="utf-8"))
        for case in cases:
            candidates = [catalogue[source_id] for source_id in case["candidate_source_ids"]]
            result = nearest_water_source(case["target"], candidates)
            self.assertEqual(result, case["water_source"], case["case_id"])

    def test_uses_water_catalogue_path(self) -> None:
        features = [_feature("-2.35_114.05", sm_delta=-0.06, days_since_rain=22)]
        risk = [_risk("-2.35_114.05", 48, 0.87, "CRITICAL")]
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
            payload, created = decide(
                features,
                risk,
                state,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
                water_catalogue_path=A_WATER,
            )
        validate_payload("dispatch", payload)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["water_source"]["kind"], "canal")

    def test_high_falling_moisture_dispatches(self) -> None:
        features = [_feature("-2.45_114.15", sm_delta=-0.05)]
        risk = [_risk("-2.45_114.15", 72, 0.65, "HIGH")]
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json")
            payload, created = decide(
                features,
                risk,
                state,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
                water_catalogue_path=None,
            )
        validate_payload("dispatch", payload)
        self.assertEqual([row["action"] for row in payload], ["DISPATCH"])
        self.assertEqual(len(created), 1)

    def test_high_without_falling_moisture_dispatches(self) -> None:
        features = [_feature("-2.45_114.15", sm_delta=0.02)]
        risk = [_risk("-2.45_114.15", 72, 0.65, "HIGH")]
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json")
            payload, created = decide(
                features,
                risk,
                state,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
                water_catalogue_path=None,
            )
        self.assertEqual([row["action"] for row in payload], ["DISPATCH"])
        self.assertEqual(len(payload[0]["audiences"]), 5)
        self.assertEqual(len(created), 1)

    def test_cluster_adds_brief(self) -> None:
        features = [
            _feature("-2.35_114.05", sm_delta=-0.06),
            _feature("-2.35_114.15", sm_delta=-0.04),
        ]
        risk = [
            _risk("-2.35_114.05", 48, 0.88, "CRITICAL"),
            _risk("-2.35_114.15", 48, 0.85, "CRITICAL"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json")
            payload, _ = decide(
                features,
                risk,
                state,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
                water_catalogue_path=None,
            )
        validate_payload("dispatch", payload)
        actions = sorted(row["action"] for row in payload)
        self.assertEqual(actions, ["BRIEF", "DISPATCH"])
        brief = next(row for row in payload if row["action"] == "BRIEF")
        self.assertEqual(brief["audiences"], ["leadership"])

    def test_dedupe_reuses_ids_inside_cooldown(self) -> None:
        features = [_feature("-2.35_114.05", sm_delta=-0.06)]
        risk = [_risk("-2.35_114.05", 48, 0.87, "CRITICAL")]
        now = datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
            first, created1 = decide(features, risk, state, now=now, water_catalogue_path=None)
            second, created2 = decide(features, risk, state, now=now, water_catalogue_path=None)
        self.assertEqual(len(created1), 1)
        self.assertEqual(created2, [])
        self.assertEqual(first[0]["dispatch_id"], second[0]["dispatch_id"])

    def test_escalation_mints_new_id(self) -> None:
        features = [_feature("-2.45_114.15", sm_delta=-0.05)]
        high = [_risk("-2.45_114.15", 48, 0.70, "HIGH")]
        critical = [_risk("-2.45_114.15", 48, 0.85, "CRITICAL")]
        now = datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
            first, _ = decide(features, high, state, now=now, water_catalogue_path=None)
            second, created = decide(features, critical, state, now=now, water_catalogue_path=None)
        self.assertEqual(first[0]["action"], "DISPATCH")
        self.assertEqual(second[0]["action"], "DISPATCH")
        self.assertEqual(len(created), 1)
        self.assertNotEqual(first[0]["dispatch_id"], second[0]["dispatch_id"])


class AgentIntegrationTests(unittest.TestCase):
    def test_live_on_contract_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ("features.json", "risk.json", "cells.geojson"):
                shutil.copy(EXAMPLES / name, folder / name)
            payload = dispatch_live(
                folder,
                folder / "dispatch.json",
                state_path=folder / "state.json",
                log_path=folder / "notifications.log",
                cooldown_hours=6,
                water_sources=A_WATER,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
            )
            self.assertTrue((folder / "dispatch.json").exists())
            self.assertGreaterEqual(len(payload), 1)
            self.assertEqual(payload[0]["action"], "DISPATCH")
            self.assertEqual(len(payload[0]["audiences"]), 5)
            self.assertEqual(payload[0]["water_source"]["kind"], "canal")
            log_text = (folder / "notifications.log").read_text(encoding="utf-8")
            self.assertIn("SIMULATED", log_text)
            # Second run dedupes
            again = dispatch_live(
                folder,
                folder / "dispatch.json",
                state_path=folder / "state.json",
                log_path=folder / "notifications.log",
                cooldown_hours=6,
                water_sources=A_WATER,
                now=datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual(payload[0]["dispatch_id"], again[0]["dispatch_id"])

    def test_mock_still_replays_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name in ("features.json", "risk.json", "cells.geojson"):
                shutil.copy(EXAMPLES / name, folder / name)
            dispatch_mock(folder, folder / "dispatch.json")
            payload = json.loads((folder / "dispatch.json").read_text(encoding="utf-8"))
            validate_payload("dispatch", payload)
            self.assertEqual(payload[0]["dispatch_id"], "d_20261017_0001")


if __name__ == "__main__":
    unittest.main()
