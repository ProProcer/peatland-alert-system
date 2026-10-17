"""Tests for extended features: social media, email, summary, CSV export."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from c_agent.email import generate_batch_email_summary, generate_email_notification
from c_agent.social_media import generate_social_media_posts, twitter_post
from c_agent.summary import export_to_csv, generate_risk_distribution, generate_summary


def _dispatch(
    dispatch_id: str = "d_20261017_0001",
    cell_id: str = "-2.35_114.05",
    action: str = "DISPATCH",
    priority: int = 1,
    water_source: dict | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "dispatch_id": dispatch_id,
        "cell_id": cell_id,
        "ts": "2026-10-17T09:05:00Z",
        "action": action,
        "priority": priority,
        "target": {"lat": -2.35, "lon": 114.05},
        "audiences": ["manggala_agni", "mpa", "bpbd", "brgm", "leadership"],
        "messages": {
            "manggala_agni": {
                "id": "Simulasi: siapkan patroli ke -2.35, 114.05.",
                "en": "Simulation: prepare a patrol to -2.35, 114.05.",
            },
            "mpa": {
                "id": "Simulasi: warga waspada.",
                "en": "Simulation: communities stay alert.",
            },
            "bpbd": {
                "id": "Simulasi: koordinasikan kesiapsiagaan.",
                "en": "Simulation: coordinate readiness.",
            },
            "brgm": {
                "id": "Simulasi: tinjau pembasahan.",
                "en": "Simulation: assess rewetting.",
            },
            "leadership": {
                "id": "Simulasi: sel kritis.",
                "en": "Simulation: critical cell.",
            },
        },
        "water_source": water_source,
        "rationale": "Risk 0.91 for 72h; 22 days since rain.",
        "status": "PENDING",
    }


class SocialMediaTests(unittest.TestCase):
    def test_twitter_post_under_280_chars(self) -> None:
        post = twitter_post(_dispatch())
        self.assertLessEqual(len(post["id"]), 280)
        self.assertLessEqual(len(post["en"]), 280)
    
    def test_twitter_post_has_simulation_label(self) -> None:
        post = twitter_post(_dispatch())
        self.assertIn("SIMULASI", post["id"])
        self.assertIn("SIMULATION", post["en"])
    
    def test_facebook_post_more_detailed(self) -> None:
        from c_agent.social_media import facebook_post
        post = facebook_post(_dispatch())
        self.assertGreater(len(post["id"]), len(twitter_post(_dispatch())["id"]))
        self.assertIn("Prioritas", post["id"])
        self.assertIn("Priority", post["en"])
    
    def test_generate_social_media_posts_for_multiple(self) -> None:
        dispatches = [_dispatch("d_1", "-2.35_114.05"), _dispatch("d_2", "-2.45_114.15")]
        posts = generate_social_media_posts(dispatches)
        self.assertEqual(len(posts["twitter"]), 2)
        self.assertEqual(len(posts["facebook"]), 2)
        self.assertEqual(posts["total_dispatches"], 2)


class EmailTests(unittest.TestCase):
    def test_email_subject_has_simulation_label(self) -> None:
        from c_agent.email import email_subject
        subject = email_subject(_dispatch())
        self.assertIn("SIMULASI", subject["id"])
        self.assertIn("SIMULATION", subject["en"])
    
    def test_email_body_contains_all_messages(self) -> None:
        from c_agent.email import email_body
        body = email_body(_dispatch())
        for audience in ["manggala_agni", "mpa", "bpbd", "brgm", "leadership"]:
            self.assertIn(audience.upper(), body["id"])
            self.assertIn(audience.upper(), body["en"])
    
    def test_batch_email_summary_counts_correctly(self) -> None:
        dispatches = [
            _dispatch("d_1", action="DISPATCH"),
            _dispatch("d_2", action="SMS_WARN"),
            _dispatch("d_3", action="REWET"),
        ]
        summary = generate_batch_email_summary(dispatches)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["critical_count"], 1)
        self.assertEqual(summary["high_count"], 2)
    
    def test_batch_email_summary_empty(self) -> None:
        summary = generate_batch_email_summary([])
        self.assertEqual(summary["count"], 0)
        self.assertIn("Tidak ada", summary["body"]["id"])


class SummaryTests(unittest.TestCase):
    def test_summary_counts_actions(self) -> None:
        dispatches = [
            _dispatch("d_1", action="DISPATCH"),
            _dispatch("d_2", action="SMS_WARN"),
            _dispatch("d_3", action="DISPATCH"),
        ]
        summary = generate_summary(dispatches)
        self.assertEqual(summary["total_dispatches"], 3)
        self.assertEqual(summary["by_action"]["DISPATCH"], 2)
        self.assertEqual(summary["by_action"]["SMS_WARN"], 1)
    
    def test_summary_counts_audiences(self) -> None:
        dispatches = [_dispatch(), _dispatch()]
        summary = generate_summary(dispatches)
        self.assertEqual(summary["by_audience"]["manggala_agni"], 2)
        self.assertEqual(summary["by_audience"]["mpa"], 2)
    
    def test_summary_counts_water_sources(self) -> None:
        dispatches = [
            _dispatch("d_1", "-2.35_114.05", water_source={"lat": -2.33, "lon": 114.02, "distance_km": 4.0, "kind": "canal"}),
            _dispatch("d_2", "-2.45_114.15", water_source=None),
        ]
        summary = generate_summary(dispatches)
        self.assertEqual(summary["with_water_source"], 1)
        self.assertEqual(summary["without_water_source"], 1)
    
    def test_risk_distribution_classifies_correctly(self) -> None:
        dispatches = [
            _dispatch(action="DISPATCH"),
            _dispatch(action="SMS_WARN"),
            _dispatch(action="REWET"),
        ]
        dist = generate_risk_distribution(dispatches)
        self.assertEqual(dist["critical"], 1)
        self.assertEqual(dist["high"], 2)
        self.assertEqual(dist["total"], 3)


class CSVExportTests(unittest.TestCase):
    def test_csv_export_creates_file(self) -> None:
        dispatches = [_dispatch()]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dispatch.csv"
            export_to_csv(dispatches, output)
            self.assertTrue(output.exists())
    
    def test_csv_export_has_correct_headers(self) -> None:
        dispatches = [_dispatch()]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dispatch.csv"
            export_to_csv(dispatches, output)
            with output.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                self.assertIn("dispatch_id", headers)
                self.assertIn("cell_id", headers)
                self.assertIn("action", headers)
    
    def test_csv_export_empty_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dispatch.csv"
            export_to_csv([], output)
            self.assertTrue(output.exists())
            content = output.read_text(encoding="utf-8")
            self.assertIn("dispatch_id", content)


if __name__ == "__main__":
    unittest.main()
