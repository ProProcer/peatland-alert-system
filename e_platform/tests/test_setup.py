"""Behavior checks for shared contracts, isolated handoffs and local serving."""

import copy
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from contracts.validate import ROOT, load_json, validate_directory, validate_payload, validate_repository
from e_platform.prepare_demo import prepare_demo
from e_platform.serve import make_server


class ContractTests(unittest.TestCase):
    def example(self, kind):
        filename = "cells.geojson" if kind == "cells" else f"{kind}.json"
        return load_json(ROOT / "contracts/examples" / filename)

    def test_repository_fixtures_and_existing_outputs(self):
        self.assertGreaterEqual(validate_repository(), 14)

    def test_rejects_incorrect_risk_threshold_at_boundary(self):
        payload = self.example("risk")
        payload[0]["risk_score"] = 0.80
        payload[0]["risk_level"] = "HIGH"
        with self.assertRaisesRegex(ValueError, "risk_level"):
            validate_payload("risk", payload)
        payload[0]["risk_level"] = "CRITICAL"
        validate_payload("risk", payload)

    def test_null_measurements_allowed_sentinels_rejected(self):
        payload = self.example("features")
        payload[0]["weather"]["sm_1_3"] = None
        validate_payload("features", payload)
        payload[0]["weather"]["sm_1_3"] = -999
        with self.assertRaises(ValueError):
            validate_payload("features", payload)

    def test_rejects_all_null_weather(self):
        payload = self.example("features")
        payload[0]["weather"] = dict.fromkeys(payload[0]["weather"])
        with self.assertRaisesRegex(ValueError, "all-null"):
            validate_payload("features", payload)

    def test_rejects_local_timestamps_and_duplicate_predictions(self):
        payload = self.example("risk")
        payload[0]["ts"] = "2026-10-17T17:00:00+08:00"
        with self.assertRaises(ValueError):
            validate_payload("risk", payload)
        payload = self.example("risk")
        payload.append(copy.deepcopy(payload[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_payload("risk", payload)

    def test_rejects_invalid_calendar_dates(self):
        payload = self.example("risk")
        payload[0]["ts"] = "2026-02-30T09:00:00Z"
        with self.assertRaises(ValueError):
            validate_payload("risk", payload)

    def test_catches_reversed_coordinates_and_crossing_cell_ring(self):
        payload = self.example("cells")
        ring = payload["features"][0]["geometry"]["coordinates"][0]
        for position in ring:
            position.reverse()
        with self.assertRaises(ValueError):
            validate_payload("cells", payload)
        payload = self.example("cells")
        ring = payload["features"][0]["geometry"]["coordinates"][0]
        ring[1], ring[2] = ring[2], ring[1]
        with self.assertRaisesRegex(ValueError, "diagonal"):
            validate_payload("cells", payload)

    def test_requires_bilingual_messages_for_listed_audiences(self):
        payload = self.example("dispatch")
        del payload[0]["messages"]["bpbd"]
        with self.assertRaisesRegex(ValueError, "missing audience"):
            validate_payload("dispatch", payload)
        payload = self.example("dispatch")
        del payload[0]["messages"]["mpa"]["id"]
        with self.assertRaises(ValueError):
            validate_payload("dispatch", payload)

    def test_rejects_duplicate_json_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            for raw in ('{"risk_score": 0.5, "risk_score": 0.9}', '[NaN]', '[Infinity]'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    load_json(path)


class PipelineTests(unittest.TestCase):
    def test_mock_pipeline_is_complete_and_preserves_checked_in_data(self):
        protected = list((ROOT / "data/processed").glob("*")) + list((ROOT / "b_model/model").glob("*"))
        before = {path: path.read_bytes() for path in protected if path.is_file()}
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["bash", str(ROOT / "scripts/run_pipeline.sh"), "--mock", folder],
                                    cwd="/tmp", env={**os.environ, "PYTHON": sys.executable}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            validate_directory(Path(folder))
            dispatch = load_json(Path(folder) / "dispatch.json")
            self.assertEqual(len(dispatch[0]["audiences"]), 5)
            self.assertIsNone(dispatch[0]["water_source"])
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original, str(path))

    def test_incomplete_handoff_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            prepare_demo(directory)
            risk = load_json(directory / "risk.json")
            risk.pop()
            (directory / "risk.json").write_text(json.dumps(risk))
            with self.assertRaisesRegex(ValueError, "missing risk horizon"):
                validate_directory(directory)

    def test_live_pipeline_fails_before_writing_mock_data(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["bash", "scripts/run_pipeline.sh", "live", folder], cwd=ROOT,
                                    env={**os.environ, "PYTHON": sys.executable}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("live ingestion is not implemented", result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_mock_pipeline_refuses_processed_directory(self):
        with self.assertRaisesRegex(ValueError, "separate mock output"):
            prepare_demo(ROOT / "data/processed")


class ServerTests(unittest.TestCase):
    def test_serves_assets_feeds_and_fallbacks_without_exposing_repo(self):
        with tempfile.TemporaryDirectory() as folder:
            prepare_demo(Path(folder))
            with make_server(Path(folder), port=0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    for path in ("/", "/app.js", "/mocks/risk.json", "/data/risk.json", "/data/cells.geojson"):
                        connection.request("GET", path)
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(response.status, 200, path)
                        if path.endswith(".json"):
                            self.assertIsInstance(json.loads(body), list)
                    for path in ("/.env", "/.git/config", "/TEAM_PLAYBOOK.md.pdf", "/data/history.parquet", "/data/%2e%2e/.env"):
                        connection.request("GET", path)
                        response = connection.getresponse()
                        response.read()
                        self.assertEqual(response.status, 404, path)
                    connection.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
