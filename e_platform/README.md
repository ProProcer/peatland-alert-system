# Role E — Platform, integration and pitch

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder, root integration files, `scripts/`, `config/`, `contracts/` and CI. Coordinate root README changes with the team. `mock_output.json` is a dispatch integration fixture, not a new contract.

```bash
bash scripts/setup.sh e
source .venv/bin/activate
make validate
make test
make demo
```

`scripts/run_pipeline.sh --mock` replays A → B → C into `data/demo/` and validates cross-file references. It never trains or overwrites B's artifacts. The live pipeline calls the same role CLIs without `--mock`; A and C currently fail with clear implementation instructions. Do not replace live failures with a synthetic result.

`serve.py` serves only D's directory and four named handoff feeds under `/data/`. Its default bind is localhost. The frontend works with a plain static server and bundled mocks when the shared handoffs are absent. This is a development server, not a production deployment.

## Containers and LinuxONE

```bash
docker compose config
docker compose up --build
# Optional model tooling image (dependencies / architecture must be checked).
docker compose --profile model build model
```

The default `e_platform/Dockerfile` runs the offline integration demo. `docker/model.Dockerfile` provides an isolated image for the existing B implementation. Use repository-root build context. Add separate production stage images as A and C implement their adapters; the current demo container does not establish live ingestion or agent readiness.

No architecture is forced in Compose. Confirm actual installation and execution on the team's `s390x` LinuxONE instance; do not infer compatibility from an x86 build. Record Python / dependency versions, backend choice (Snap ML or sklearn), CPU/memory and latency. Model inference must finish within one minute; A refresh within two. Capture evidence under `evidence/`, including instance dashboard, containers, inference and resource use. Do not record credentials.

### Portable historical training inputs

The installed Anaconda PyArrow 17/19 readers on the team's s390x VM failed on
the original regional Parquet. The version 17 error interpreted the little-endian
17,923-byte footer length as 54,919,168 bytes. Export a separate gzip CSV on a
machine that can read the original Parquet:

```bash
python -m e_platform.portable_history export --output /tmp/portable-history
```

The export checks the frozen source fingerprint and verifies every value, dtype,
null and row through an exact CSV round trip. Transfer both `history.csv.gz` and
`history-manifest.json` to the VM. On LinuxONE, from the repository root:

```bash
/workspace/env/bin/python -m e_platform.portable_history train \
  --bundle /workspace/portable-history --output /workspace/outputs/training-NEW
```

Use a fresh output directory. This runner reproduces the three already-selected
regional logistic models and three dryness baselines on the frozen final-period
split. It reuses B's fit, calibration, preprocessing, metrics and artifact-export
helpers, retaining 72-hour gaps and per-horizon regularization. It verifies the
portable values again on the destination and writes models, metrics, source and
partition records, inference output and a resource report separately. It does
not rerun the 36-fit model comparison or promote new artifacts. Retrospective
reproduction is not independent validation; a failed quality gate stays failed.
Source data and the current B handoff are read-only. Libraries used here are
already in the root inventory; gzip/CSV transport adds no package dependency.

In the managed cloud environment, preserve inherited proxies and TLS validation. If a build needs a session CA, use the optional Compose overlay:

```bash
PROXY_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt docker compose -f docker-compose.yml -f e_platform/compose.proxy.yml build
```

The bundle is mounted as a build secret only. The Dockerfiles use pip's ordinary trust when no secret is supplied, and the mounted bundle when supplied. Registry egress and daemon trust must be configured by the environment, separately from build-step trust.

## Integration and submission

- Share LinuxONE / Jupyter access instructions after confirming both mandatory IBM labs and the Oct 16 setup session.
- Keep schema 1.0 frozen and require `make validate`; CI runs contract and scaffold tests. B's full model tests are separate because they need the scientific stack and artifacts.
- Agree on the demo province and water-source decision early. Current setup selects Central Kalimantan and null water sources. Record changes in `config/demo.json` and tell the team.
- Use [team-prompts.md](team-prompts.md) to start each role's agent session.
- Update [architecture.md](architecture.md), [submission/checklist.md](submission/checklist.md) and [submission/demo-script.md](submission/demo-script.md).
- Feature freeze at hour 18; after that focus on bugs, evidence and the video. Submit with at least 30 minutes of buffer.

The scaffold has no deployed system, verified IBM access, recorded video, real data acquisition, or evaluated model results. Those are the team's remaining deliverables, not claims made by this setup.
