# Automatic live dashboard

The service refreshes all 40 configured Kalimantan cells immediately at startup
and hourly after each attempt. It fetches modeled weather and FIRMS NRT data,
validates features, runs the fixed regional model for 24/48/72 hours, generates
simulated Role C responses, validates all handoffs, and atomically publishes a
complete snapshot. The dashboard polls for published snapshots every minute.
This schedules inference; it does not retrain or change risk thresholds.

## Install and run

From the repository root, install Python 3.12 and create a local environment:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r e_platform/requirements-live.txt
```

Linux/macOS can use `python3.12 -m venv .venv` and
`.venv/bin/python -m pip install -r e_platform/requirements-live.txt`.
Retrieve Git LFS data before first use. Put the private `FIRMS_MAP_KEY` in the
ignored `.env` file, or set it in the service environment. Never commit the key.

```powershell
# Dashboard + background hourly refresh. Leave the process running.
.venv/Scripts/python.exe -m e_platform.live_service --port 8001

# Or launch a hidden background process on Windows:
powershell -File scripts/start_live.ps1 -Background

# Optional one-shot run, without the HTTP server:
.venv/Scripts/python.exe -m e_platform.live_service --once
```

Open **http://127.0.0.1:8001**. This command serves live data; the older
`python -m d_frontend.serve_demo` command deliberately remains a historical demo.
The live server never substitutes historical/static mocks when live ingestion
fails or has not yet produced a complete snapshot. Its initial page waits and
retries. A failed later refresh retains the last successful snapshot and exposes
the failure/staleness in the page and `/live/status`.

The adapter uses `models=dwd_icon_global` from `data/raw/open-meteo_api.md` and
publishes only weather hours at/before retrieval time. Predictions refer to the
following 24/48/72 hours, not to forecasts anchored to the old October 16 replay.
Live modeled weather/NRT coverage and model quality remain provisional.

## Keep it running across sessions

On Windows, register the current user's logon task:

```powershell
powershell -File scripts/install_live_task.ps1
```

The task is `PeatlandLiveDashboard`. It runs at login, restarts on process failure,
and does not require the chat or editor to remain open. The computer must be on,
awake, logged in and connected to the internet. Use Task Scheduler to inspect or
disable it; stop the running process before switching to another server on 8001.
The background launcher records its PID under `data/runtime/live/service.pid`.

On an always-on Linux/LinuxONE host, edit the `/opt/peatland-alert-system` paths
in `systemd/peatland-live.service` to the installed checkout/environment, then
install and enable it with the host administrator. The unit runs at boot and
restarts on failure. Dependency/latency validation on s390x is still required;
the template does not establish hardware compatibility.

Docker alternative (after configuring `.env` and retrieving LFS inputs):

```bash
docker compose --profile live up -d --build live
```

Historical source files are mounted read-only. The live service uses a separate
runtime volume and `restart: unless-stopped`. Docker must be running and
configured to start after host reboot for this to be automatic.

## Publication and failure behavior

- Runtime data, raw request caches, history context, simulated logs and status
  stay in ignored `data/runtime/live/`; original training artifacts and historical
  source bundles are read-only. The last four generations are retained, plus
  the current successful one if recent failures would otherwise evict it.
- A file lock prevents concurrent scheduled/manual refreshes. New files are
  built in a private generation and validated together. A single atomic pointer
  publishes the generation only after A, B and C succeed. Browser requests and
  response summaries use generation-specific URLs so a refresh cannot mix feeds.
- The next run resumes history and incident state from the last successful
  generation. Same-hour reruns replace that hour's live context, without duplicate
  history keys. No live hour receives a future training label.
- Restarting after a gap is supported. Where provider lookback cannot reconstruct
  older observations, measurements/labels remain null; cell metadata and a
  manifest gap count describe the missing period. It is not filled with zero.
- Retries occur at the configured interval, not in a tight loop. Raw provider
  caches remain private with each generation. Credentials are redacted from
  public status/errors. No real SMS, email or dispatch is sent.
- `/live/status` reports the last success, error and data age. Data older than
  three hours is marked stale. HTTP health establishes that the service is
  reachable; inspect `state`/`stale` to assess data freshness.

Use `--interval-seconds` to change the default 3600 seconds (allowed range:
60–86400). Frequent provider requests consume quota. The scheduler waits this
interval after a run completes. Schema 1.0 and the selected model's thresholds
are unchanged; automatic collection is not evidence of operational model quality.

## Verification

```bash
python -m unittest discover -s e_platform/tests -v
python -m unittest a_data.tests.test_live_continuity d_frontend.test_serve_demo -v
node d_frontend/test_data.cjs
node d_frontend/test_status.cjs
python -m contracts.validate
```

The tests mock provider responses for restart/outage cases; software tests do not
claim fire-prediction performance. A live run requires valid provider credentials.
No new third-party dependency was introduced by the scheduling/server code.
