"""Hourly A -> B -> C refresh with immutable snapshots and atomic publication."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "data/runtime/live"
FEEDS = ("features.json", "cells.geojson", "risk.json", "dispatch.json")


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def current_snapshot(runtime=DEFAULT_RUNTIME):
    """Resolve one completed generation. No moving feed-by-feed aliases."""
    runtime = Path(runtime).resolve()
    pointer = runtime / "current.json"
    if not pointer.is_file():
        return None
    value = json.loads(pointer.read_text(encoding="utf-8"))
    directory = (runtime / value["directory"]).resolve()
    if not directory.is_relative_to(runtime / "snapshots") or not directory.is_dir():
        raise ValueError("Invalid published live snapshot path")
    if not all((directory / name).is_file() for name in (*FEEDS, "history.parquet", "pipeline_manifest.json")):
        raise ValueError("Published live snapshot is incomplete")
    return directory


def service_status(runtime=DEFAULT_RUNTIME):
    path = Path(runtime) / "status.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"state": "not_started"}
    directory = current_snapshot(runtime)
    if directory:
        manifest = json.loads((directory / "pipeline_manifest.json").read_text(encoding="utf-8"))
        value.update(snapshot=manifest["snapshot"], published_at=manifest["published_at"],
                     weather_model=manifest["weather_model"], generation=directory.name)
        stamp = datetime.fromisoformat(manifest["snapshot"].replace("Z", "+00:00"))
        value["age_seconds"] = max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
        value["stale"] = value["age_seconds"] > 3 * 3600
    else:
        value.update(snapshot=None, stale=True)
    return value


@contextmanager
def pipeline_lock(runtime):
    """OS releases this advisory lock on crash; no stale PID lock to clear."""
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "pipeline.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("A live pipeline refresh is already running") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def redact(message):
    # Never publish credentials from environment, .env, or a provider URL.
    import re
    secrets = [os.environ.get("FIRMS_MAP_KEY", "")]
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "FIRMS_MAP_KEY":
                secrets.append(value.strip().strip("\"'"))
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return re.sub(r"(/(?:area|data_availability)/csv/)[^/\s]+/", r"\1[redacted]/", message)[:1000]


def _stages():
    from a_data.live import refresh_live
    from b_model.predict import run_predictions
    from c_agent.agent import dispatch_live
    return refresh_live, run_predictions, dispatch_live


def refresh_once(runtime=DEFAULT_RUNTIME, *, source_dir=None, model_dir=None,
                 water_sources=None, stages=None):
    """Publish a complete validated generation; failures retain last good data."""
    from contracts.validate import validate_directory
    runtime = Path(runtime).resolve()
    source_dir = Path(source_dir or ROOT / "data/demo/role_a_real/regional_40").resolve()
    model_dir = Path(model_dir or ROOT / "b_model/model_regional_40").resolve()
    water_sources = Path(water_sources or ROOT / "data/demo/role_a_real/water_sources.geojson").resolve()
    if runtime == source_dir or runtime.is_relative_to(source_dir) or source_dir.is_relative_to(runtime):
        raise ValueError("Runtime storage must be separate from the historical source")
    if runtime.is_relative_to((ROOT / "data/processed").resolve()) or runtime.is_relative_to(model_dir):
        raise ValueError("Runtime storage must not overlap processed data or model artifacts")
    with pipeline_lock(runtime):
        previous = current_snapshot(runtime)
        generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
        work = runtime / "snapshots" / generation
        work.mkdir(parents=True)
        write_json(runtime / "status.json", {"state": "refreshing", "started_at": utc_now(),
                   "last_success_available": previous is not None})
        try:
            ingest, predict, dispatch = stages or _stages()
            ingest(source_dir, work, context_dir=previous)
            predict(features_path=work / "features.json", history_path=work / "history.parquet",
                    model_dir=model_dir, output_path=work / "risk.json")
            # State belongs to this generation until the generation is committed.
            if previous and (previous / "agent_state.json").exists():
                shutil.copyfile(previous / "agent_state.json", work / "agent_state.json")
            dispatch(data_dir=work, output=work / "dispatch.json", state_path=work / "agent_state.json",
                     log_path=work / "notifications.log", water_sources=water_sources, use_llm=False)
            validate_directory(work)
            features = json.loads((work / "features.json").read_text(encoding="utf-8"))
            risk = json.loads((work / "risk.json").read_text(encoding="utf-8"))
            times = {row["ts"] for row in features}
            if len(times) != 1 or {row["ts"] for row in risk} != times:
                raise ValueError("Live predictions and features must share one snapshot hour")
            live = json.loads((work / "live_manifest.json").read_text(encoding="utf-8"))
            manifest = {"mode": "live", "schema_version": "1.0", "snapshot": next(iter(times)),
                        "published_at": utc_now(), "cell_count": len(features), "risk_records": len(risk),
                        "model_dir": str(model_dir), "weather_model": live["weather"]["model"],
                        "simulation": True, "previous_generation": previous.name if previous else None}
            write_json(work / "pipeline_manifest.json", manifest)
            # Staging duplicates the published files. Raw provider caches stay
            # with their generation for provenance and troubleshooting.
            for name in (".staging",):
                target = (work / name).resolve()
                if target.is_relative_to(work.resolve()) and target.is_dir():
                    shutil.rmtree(target)
            write_json(runtime / "current.json", {"directory": f"snapshots/{generation}", "snapshot": manifest["snapshot"]})
            write_json(runtime / "status.json", {"state": "ready", "completed_at": utc_now(), "last_success_available": True})
            try:
                prune_snapshots(runtime, keep=4)
            except OSError as exc:
                print(f"Live snapshot published; retention cleanup deferred: {redact(str(exc))}", flush=True)
            return manifest
        except Exception as exc:
            write_json(runtime / "status.json", {"state": "error", "failed_at": utc_now(),
                       "error": redact(str(exc)), "last_success_available": previous is not None})
            raise


def prune_snapshots(runtime, keep=4):
    """Bound runtime disk use, always retaining the current successful snapshot."""
    root = (Path(runtime).resolve() / "snapshots").resolve()
    active = current_snapshot(runtime)
    candidates = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    retained = set(candidates[:keep]) | ({active} if active else set())
    for path in candidates:
        target = path.resolve()
        if path not in retained and target != root and target.is_relative_to(root):
            shutil.rmtree(target)


class Scheduler:
    def __init__(self, runtime, *, interval=3600, **options):
        if not 60 <= interval <= 86400:
            raise ValueError("Refresh interval must be 60..86400 seconds")
        self.runtime, self.interval, self.options = runtime, interval, options
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="live-refresh", daemon=True)

    def loop(self):
        while not self.stop.is_set():
            try:
                manifest = refresh_once(self.runtime, **self.options)
                print(f"Live snapshot published: {manifest['snapshot']} ({manifest['cell_count']} cells)", flush=True)
            except Exception as exc:
                print(f"Live refresh failed; retaining last good snapshot: {redact(str(exc))}", flush=True)
            # Failure retries use the same interval; no quota-consuming tight loop.
            self.stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()


def main():
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(variable, "2")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Refresh once without serving or scheduling")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/demo/role_a_real/regional_40")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "b_model/model_regional_40")
    parser.add_argument("--interval-seconds", type=float, default=3600)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    options = {"source_dir": args.source_dir, "model_dir": args.model_dir}
    if args.once:
        try:
            print(json.dumps(refresh_once(args.runtime_dir, **options), indent=2))
        except Exception as exc:
            raise SystemExit(redact(str(exc))) from None
        return
    from d_frontend.serve_demo import make_server
    scheduler = Scheduler(args.runtime_dir, interval=args.interval_seconds, **options)
    with make_server(port=args.port, host=args.host, live_root=args.runtime_dir) as server:
        def stop(signum, frame):
            scheduler.close()
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        scheduler.start()
        print(f"Automatic live dashboard: http://{args.host}:{server.server_port}; interval={args.interval_seconds:g}s", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.close()


if __name__ == "__main__":
    main()
