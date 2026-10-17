"""Tests for the water cutoff, SMS limits, optional LLM guard and input checks."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from contracts.validate import validate_payload

from c_agent import llm, messages
from c_agent.agent import dispatch_live
from c_agent.policy import decide
from c_agent.state_store import StateStore
from c_agent.tests.test_policy import _feature, _risk
from c_agent.water import nearest_water_source

NOW = datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc)
CELL = "-2.35_114.05"
NEAR = [{"lat": -2.33, "lon": 114.02, "kind": "canal"}]
FAR = [{"lat": 0.5, "lon": 101.0, "kind": "river"}]


def _critical_inputs():
    return (
        [_feature(CELL, sm_delta=-0.06, days_since_rain=22)],
        [_risk(CELL, 48, 0.87, "CRITICAL")],
    )


def _run(rewriter=None, water=NEAR, state=None, now=NOW):
    features, risk = _critical_inputs()
    with tempfile.TemporaryDirectory() as tmp:
        store = state or StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
        # Pass as a path (will be treated as empty list if None)
        return decide(features, risk, store, now=now, water_catalogue_path=None, rewriter=rewriter)


def _fake_post(transform):
    """Fake LLM transport: reads TEMPLATE from the request, returns transform(template)."""
    def post(payload):
        request = json.loads(payload["user"])
        return json.dumps(transform(request["TEMPLATE"]), ensure_ascii=False)
    return post


def _suffix(template):
    return {
        audience: {"id": m["id"] + " Tetap waspada.", "en": m["en"] + " Stay safe."}
        for audience, m in template.items()
    }


class WaterCutoffTests(unittest.TestCase):
    target = {"lat": -2.35, "lon": 114.05}

    def test_near_source_kept(self) -> None:
        self.assertEqual(nearest_water_source(self.target, NEAR, 15.0)["kind"], "canal")

    def test_far_source_dropped_with_cutoff(self) -> None:
        self.assertIsNone(nearest_water_source(self.target, FAR, 15.0))
        self.assertIsNotNone(nearest_water_source(self.target, FAR))  # no cutoff: unchanged behaviour

    def test_decide_emits_null_water_when_no_catalogue(self) -> None:
        payload, _ = _run()
        validate_payload("dispatch", payload)
        self.assertIsNone(payload[0]["water_source"])


class MessageTests(unittest.TestCase):
    ctx = {
        "lat": -10.55, "lon": 114.55, "risk_score": 0.99, "horizon_h": 48,
        "sm_27_81": 0.123, "sm_27_81_delta_7d": -0.123, "days_since_rain": 123,
        "cluster_size": 12, "cluster_cell_ids": [CELL], "top_factors": [], "water_source": None,
    }

    def test_sms_limit_both_languages(self) -> None:
        for builder in (messages.sms_warn_messages, messages.critical_messages):
            sms = builder(self.ctx)["mpa"]
            for lang in ("id", "en"):
                self.assertLessEqual(len(sms[lang]), llm.SMS_MAX_CHARS, sms[lang])

    def test_decline_is_not_written_with_a_minus_sign(self) -> None:
        sms = messages.sms_warn_messages(self.ctx)["mpa"]
        self.assertIn("fell 0.12", sms["en"])
        self.assertIn("turun 0.12", sms["id"])
        self.assertNotIn("fell -", sms["en"])


class RewriterTests(unittest.TestCase):
    def test_no_key_means_no_rewriter(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(llm.make_rewriter())

    def test_provider_choice_from_environment(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, clear=True):
            self.assertEqual(llm._pick_provider(None), ("gemini", "g"))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=True):
            self.assertEqual(llm._pick_provider(None), ("anthropic", "a"))
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True):
            self.assertEqual(llm._pick_provider(None), ("gemini", "k"))
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "LLM_PROVIDER": "anthropic"}, clear=True):
            self.assertIsNone(llm._pick_provider(None))

    def test_gemini_request_shape_and_response_parsing(self) -> None:
        seen = {}

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["key"] = request.get_header("X-goog-api-key")
            seen["body"] = json.loads(request.data)
            reply = {"candidates": [{"content": {"parts": [
                {"text": "ignored reasoning", "thought": True},
                {"text": '{"ok": 1}'},
            ]}}]}
            return Reply(json.dumps(reply).encode())

        post = llm._gemini_post("secret", "gemini-test", 5.0)
        with mock.patch("c_agent.llm.urllib.request.urlopen", fake_urlopen):
            text = post({"system": "S", "user": "U"})
        self.assertEqual(text, '{"ok": 1}')
        self.assertIn("models/gemini-test:generateContent", seen["url"])
        self.assertNotIn("secret", seen["url"])  # key goes in a header, never the URL
        self.assertEqual(seen["key"], "secret")
        self.assertEqual(seen["body"]["systemInstruction"]["parts"][0]["text"], "S")
        self.assertEqual(seen["body"]["contents"][0]["parts"][0]["text"], "U")
        self.assertEqual(seen["body"]["generationConfig"]["responseMimeType"], "application/json")

    def test_accepts_valid_rewrite(self) -> None:
        logs: list[str] = []
        rewriter = llm.make_rewriter(post=_fake_post(_suffix), log=logs.append)
        payload, _ = _run(rewriter)
        validate_payload("dispatch", payload)
        self.assertTrue(payload[0]["messages"]["manggala_agni"]["en"].endswith("Stay safe."))
        self.assertEqual(logs, [])

    def test_accepts_fenced_json(self) -> None:
        def post(payload):
            template = json.loads(payload["user"])["TEMPLATE"]
            return "```json\n" + json.dumps(_suffix(template)) + "\n```"
        payload, _ = _run(llm.make_rewriter(post=post))
        self.assertTrue(payload[0]["messages"]["bpbd"]["en"].endswith("Stay safe."))

    def _assert_falls_back(self, transform) -> None:
        logs: list[str] = []
        baseline, _ = _run(None)
        payload, _ = _run(llm.make_rewriter(post=_fake_post(transform), log=logs.append))
        self.assertEqual(payload[0]["messages"], baseline[0]["messages"])
        self.assertTrue(any("rejected" in line for line in logs), logs)

    def test_rejects_invented_number(self) -> None:
        def bad(template):
            out = _suffix(template)
            out["manggala_agni"]["en"] += " Risk is 87%."
            return out
        self._assert_falls_back(bad)

    def test_rejects_missing_simulation_label(self) -> None:
        def bad(template):
            out = _suffix(template)
            out["leadership"]["en"] = "Urgent: " + out["leadership"]["en"]
            return out
        self._assert_falls_back(bad)

    def test_rejects_long_sms(self) -> None:
        def bad(template):
            out = _suffix(template)
            out["mpa"]["en"] = "Simulation: " + "stay alert " * 20
            return out
        self._assert_falls_back(bad)

    def test_rejects_changed_audiences(self) -> None:
        self._assert_falls_back(lambda template: {"mpa": next(iter(template.values()))})

    def test_transport_error_falls_back_without_blocking(self) -> None:
        logs: list[str] = []

        def boom(_payload):
            raise TimeoutError("network down")

        baseline, _ = _run(None)
        payload, _ = _run(llm.make_rewriter(post=boom, log=logs.append))
        self.assertEqual(payload, baseline)
        self.assertTrue(any("unavailable" in line for line in logs))

    def test_reused_incident_does_not_call_llm_again(self) -> None:
        calls: list[int] = []

        def post(payload):
            calls.append(1)
            return _fake_post(_suffix)(payload)

        rewriter = llm.make_rewriter(post=post)
        with tempfile.TemporaryDirectory() as tmp:
            state = StateStore(Path(tmp) / "incidents.json", cooldown_hours=6)
            _run(rewriter, state=state)
            first = len(calls)
            _run(rewriter, state=state, now=NOW.replace(hour=10))  # inside cooldown
        self.assertGreater(first, 0)
        self.assertEqual(len(calls), first)


class InputCheckTests(unittest.TestCase):
    def test_missing_cells_geojson_gives_a_clear_stop(self) -> None:
        features, risk = _critical_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "features.json").write_text(json.dumps(features))
            (data / "risk.json").write_text(json.dumps(risk))
            with self.assertRaises(SystemExit) as caught:
                dispatch_live(data, data / "dispatch.json", state_path=data / "s.json", log_path=data / "n.log")
            self.assertIn("cells.geojson", str(caught.exception))
            self.assertFalse((data / "dispatch.json").exists())


if __name__ == "__main__":
    unittest.main()
