"""Offline live-ingestion tests with real cell geometry and mocked providers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from shapely.geometry import box

from a_data.common import ROOT, GROUPS, WEATHER_MAP
from a_data.live import _fetch_firms, refresh_live


class LiveContinuityTests(unittest.TestCase):
    def test_firms_uses_geographic_coordinates_for_buffer_filter(self):
        response = Mock(status_code=200)
        response.text = ('latitude,longitude,acq_date,acq_time,satellite,confidence,frp\n'
                         '-1.5,113.5,2026-01-04,1200,N20,n,5\n'
                         '-1.5,112.98,2026-01-04,1200,N20,h,6\n'
                         '-1.5,110,2026-01-04,1200,N20,n,7\n')
        session = Mock()
        session.get.return_value = response
        frame, report = _fetch_firms(session, 'test-key', box(113, -2, 114, -1),
                                     self.root / 'firms', pd.Timestamp('2026-01-04', tz='UTC'))
        self.assertEqual(set(frame.longitude), {113.5, 112.98})
        self.assertEqual(int(frame.in_scope.sum()), 1)
        self.assertTrue(frame.alert_eligible.all())
        self.assertEqual(report['retained_in_buffer'], 2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        actual = ROOT / "data/demo/role_a_real/regional_40"
        for name in ("cells.geojson", "features.json", "selection.json"):
            (self.source / name).write_bytes((actual / name).read_bytes())
        features = json.loads((self.source / "features.json").read_text())
        rows = []
        for record in features:
            row = {key: record[key] for key in ("schema_version", "cell_id", "lat", "lon")}
            row["ts"] = "2026-01-01T23:00:00Z"
            for group, columns in GROUPS.items():
                row.update({name: record[group][name] for name in columns})
            row.update(target_24h=0, target_48h=0, target_72h=0)
            rows.append(row)
        self.history = pd.DataFrame(rows)
        self.history.to_parquet(self.source / "history.parquet", index=False)

    def tearDown(self):
        self.temp.cleanup()

    def run_refresh(self, destination, now, context=None, weather_start="2025-12-01"):
        def weather(session, cell, cache):
            times = pd.date_range(pd.Timestamp(weather_start, tz="UTC"), pd.Timestamp(now).normalize() + pd.Timedelta(days=3), freq="h")
            values = {name: np.full(len(times), .3 if name.startswith('sm_') else 0.) for name in WEATHER_MAP.values()}
            return pd.DataFrame({"ts": times, "cell_id": cell["cell_id"], **values}), {}
        def firms(*args):
            frame = pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "time_ns": pd.Series(dtype="int64"), "latitude": pd.Series(dtype="float64"),
                "longitude": pd.Series(dtype="float64"), "frp": pd.Series(dtype="float64"),
                "cell_id": pd.Series(dtype="object"), "in_scope": pd.Series(dtype="bool"),
                "alert_eligible": pd.Series(dtype="bool")})
            return frame, {"queries": []}
        with patch("a_data.live._firms_key", return_value="test-key"), \
             patch("a_data.live._weather_request", side_effect=weather), \
             patch("a_data.live._fetch_firms", side_effect=firms), \
             patch("a_data.live.load_boundary", return_value=(box(108, -5, 120, 5), None, None)):
            return refresh_live(self.source, destination, context_dir=context, now=now)

    def test_refresh_beyond_24_hours_then_resume_next_day_and_same_hour(self):
        first, second, third = [self.root / name for name in ("first", "second", "third")]
        original = (self.source / "history.parquet").read_bytes()
        manifest = self.run_refresh(first, "2026-01-04T12:00:00Z")
        self.assertGreater(manifest["appended_live_rows"], 24 * 40)
        self.assertEqual(manifest["unobserved_gap_rows"], 0)
        next_manifest = self.run_refresh(second, "2026-01-05T12:00:00Z", context=first)
        self.assertEqual(next_manifest["appended_live_rows"], 24 * 40)
        self.run_refresh(third, "2026-01-05T12:30:00Z", context=second)
        history = pd.read_parquet(third / "history.parquet")
        self.assertFalse(history.duplicated(["cell_id", "ts"]).any())
        live = history[history.ts > "2026-01-01T23:00:00Z"]
        self.assertTrue(live[["target_24h", "target_48h", "target_72h"]].isna().all().all())
        self.assertEqual((self.source / "history.parquet").read_bytes(), original)
        self.assertEqual(len(json.loads((third / "features.json").read_text())), 40)

    def test_long_outage_preserves_unknown_measurements_instead_of_zero(self):
        destination = self.root / "after_outage"
        manifest = self.run_refresh(destination, "2026-03-01T12:00:00Z", weather_start="2026-02-01")
        self.assertGreater(manifest["unobserved_gap_rows"], 0)
        history = pd.read_parquet(destination / "history.parquet")
        gap = history[(history.ts >= "2026-01-02") & (history.ts < "2026-02-01")]
        self.assertTrue(gap[list(WEATHER_MAP.values())].isna().all().all())
        self.assertTrue(gap[["target_24h", "target_48h", "target_72h"]].isna().all().all())
        snapshot = json.loads((destination / "features.json").read_text())
        self.assertTrue(all(row["weather"]["sm_27_81"] == .3 for row in snapshot))
