"""Publication, restart context, locking, scheduler and HTTP isolation checks."""
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from contracts.validate import ROOT, validate_directory
from d_frontend.serve_demo import make_server
from e_platform.live_service import Scheduler, current_snapshot, pipeline_lock, refresh_once, service_status, write_json


class LivePipelineTests(unittest.TestCase):
    def stages(self, timestamp="2026-10-18T00:00:00Z", *, fail=False):
        def ingest(source, work, context_dir=None):
            self.context = context_dir
            features = json.loads((ROOT / "a_data/mock_output.json").read_text())
            for row in features:
                row["ts"] = timestamp
            write_json(work / "features.json", features)
            (work / "cells.geojson").write_bytes((ROOT / "a_data/fixtures/cells.geojson").read_bytes())
            (work / "history.parquet").write_bytes(b"test context; production uses Parquet")
            write_json(work / "live_manifest.json", {"weather": {"model": "dwd_icon_global"}})
        def predict(**kwargs):
            if fail:
                raise ValueError("upstream unavailable")
            risk = json.loads((ROOT / "b_model/mock_output.json").read_text())
            for row in risk:
                row["ts"] = timestamp
            write_json(kwargs["output_path"], risk)
        def dispatch(**kwargs):
            state = kwargs["state_path"]
            previous = json.loads(state.read_text()) if state.exists() else {"runs": 0}
            write_json(state, {"runs": previous["runs"] + 1})
            write_json(kwargs["output"], [])
        return ingest, predict, dispatch

    def test_publish_resume_and_failed_refresh_keep_last_good_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            self.assertIsNone(current_snapshot(runtime))
            refresh_once(runtime, stages=self.stages())
            first = current_snapshot(runtime)
            self.assertIsNone(self.context)
            validate_directory(first)
            refresh_once(runtime, stages=self.stages("2026-10-19T00:00:00Z"))
            second = current_snapshot(runtime)
            self.assertEqual(self.context, first)
            self.assertEqual(json.loads((second / "agent_state.json").read_text())["runs"], 2)
            self.assertEqual(json.loads((first / "agent_state.json").read_text())["runs"], 1)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                refresh_once(runtime, stages=self.stages(fail=True))
            self.assertEqual(current_snapshot(runtime), second)
            self.assertEqual(service_status(runtime)["state"], "error")
            self.assertTrue(service_status(runtime)["last_success_available"])

    def test_cross_file_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            ingest, predict, dispatch = self.stages()
            def bad_predict(**kwargs):
                predict(**kwargs)
                rows = json.loads(kwargs["output_path"].read_text())
                rows[0]["ts"] = "2026-10-17T00:00:00Z"
                write_json(kwargs["output_path"], rows)
            with self.assertRaises(ValueError):
                refresh_once(runtime, stages=(ingest, bad_predict, dispatch))
            self.assertIsNone(current_snapshot(runtime))

    def test_process_lock_rejects_overlapping_runs_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            with pipeline_lock(folder):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with pipeline_lock(folder):
                        pass
            with pipeline_lock(folder):
                pass

    def test_live_catalog_waits_without_historical_fallback_and_pins_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            with make_server(port=0, live_root=runtime) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                def get(path):
                    conn.request("GET", path)
                    response = conn.getresponse()
                    return response.status, json.loads(response.read())
                try:
                    self.assertEqual(get("/demo/catalog.json")[1], {"mode": "live", "datasets": []})
                    refresh_once(runtime, stages=self.stages())
                    dataset = get("/demo/catalog.json")[1]["datasets"][0]
                    self.assertEqual(dataset["id"], "live")
                    old_base = dataset["base"]
                    refresh_once(runtime, stages=self.stages("2026-10-19T00:00:00Z"))
                    self.assertEqual(get(old_base + "features.json")[1][0]["ts"], "2026-10-18T00:00:00Z")
                    self.assertNotEqual(get("/demo/catalog.json")[1]["datasets"][0]["base"], old_base)
                    for filename in ("history.parquet", "agent_state.json", "notifications.log", "../../.env"):
                        self.assertEqual(get(old_base + filename)[0], 404)
                    self.assertEqual(get("/live/status")[1]["snapshot"], "2026-10-19T00:00:00Z")
                finally:
                    conn.close()
                    server.shutdown()
                    thread.join(timeout=5)

    def test_scheduler_refreshes_immediately_then_waits_even_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            scheduler = Scheduler(folder)
            waits = []
            def stop_after_first_wait(interval):
                waits.append(interval)
                scheduler.stop.set()
            with patch.object(scheduler.wake, "wait", side_effect=stop_after_first_wait):
                with patch("e_platform.live_service.time.time", return_value=3600 + 57 * 60), \
                     patch("e_platform.live_service.refresh_once", side_effect=ValueError("retry later")) as run:
                    scheduler.loop()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(waits, [180])

    def test_manual_requests_coalesce_and_do_not_overlap(self):
        scheduler = Scheduler('unused')
        self.assertTrue(scheduler.request_refresh())
        self.assertFalse(scheduler.request_refresh())
        scheduler.wake.clear()
        scheduler.busy = True
        self.assertFalse(scheduler.request_refresh())
        scheduler.busy = False
        with patch('e_platform.live_service.time.time', return_value=7200):
            self.assertEqual(scheduler.seconds_until_boundary(), 3600)
        scheduler.close()
        self.assertFalse(scheduler.request_refresh())

    def test_manual_request_wakes_waiting_worker(self):
        scheduler = Scheduler('unused')
        waiting = threading.Event()
        real_wait = scheduler.wake.wait
        runs = []
        def wait(timeout):
            waiting.set()
            return real_wait(timeout)
        def refresh(*args, **kwargs):
            runs.append(1)
            if len(runs) == 2:
                scheduler.close()
            return {'snapshot': 'test', 'cell_count': 40}
        with patch.object(scheduler.wake, 'wait', side_effect=wait), \
             patch('e_platform.live_service.refresh_once', side_effect=refresh):
            scheduler.start()
            try:
                self.assertTrue(waiting.wait(5))
                self.assertTrue(scheduler.request_refresh())
                scheduler.thread.join(5)
                self.assertFalse(scheduler.thread.is_alive())
                self.assertEqual(len(runs), 2)
            finally:
                scheduler.close()
                scheduler.thread.join(5)

    def test_manual_http_refresh_is_async_and_same_origin(self):
        scheduler = Scheduler('unused')
        with tempfile.TemporaryDirectory() as folder, \
             make_server(port=0, live_root=folder, refresh_callback=scheduler.request_refresh) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            def post(origin=None):
                headers = {'Content-Type': 'application/json'}
                if origin:
                    headers['Origin'] = origin
                connection.request('POST', '/live/refresh', '{}', headers)
                response = connection.getresponse()
                response.read()
                return response.status
            try:
                self.assertEqual(post('https://external.example'), 403)
                self.assertFalse(scheduler.wake.is_set())
                self.assertEqual(post(), 202)
                self.assertEqual(post(), 409)
            finally:
                connection.close()
                server.shutdown()
                thread.join(timeout=5)
