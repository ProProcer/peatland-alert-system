# Decision policy — Role C (schema 1.0)

Status: **live deterministic policy implemented** in `policy.py`. Messages are templated from structured fields only (no LLM). Alerts are simulated to `logs/`; no real SMS is sent.

Water candidates are owned by Role A (`a_data/mock_water_sources.json`, see `a_data/WATER_HANDOFF.md`). Role C only computes nearest-to-`target` Haversine distance (R = 6371.0088 km) and emits the schema 1.0 four-field `water_source`. If the catalogue is missing or empty → `water_source: null`.

## Horizon resolution

For each `cell_id`, pick one driving risk row:

1. Highest `risk_level` (CRITICAL > HIGH > MODERATE > LOW)
2. Then highest `risk_score`
3. Then shortest `horizon_h` (24 before 48 before 72)

## Actions

| Condition | Action(s) | Priority | Audiences |
| --- | --- | --- | --- |
| Driving level CRITICAL | `DISPATCH` | 1 | All five: `manggala_agni`, `mpa`, `bpbd`, `brgm`, `leadership` |
| CRITICAL cluster of 2+ edge-adjacent cells | additional `BRIEF` | 2 | `leadership` |
| HIGH and `sm_27_81_delta_7d < 0` (not null) | `SMS_WARN` then `REWET` | 2 / 3 | `mpa` / `brgm` |
| MODERATE or LOW, or HIGH without falling deep moisture | none | — | — |

Edge-adjacent means centers differ by exactly `0.1°` on one axis and `0` on the other (4-connected on the peat grid). Cluster target is the mean of member cell centers (named `lat` / `lon`). Primary `cell_id` on the record is the member with the strongest driving risk.

## Water cutoff

The nearest catalogue source is attached only if it is within 15 km of the dispatch `target` (`DEFAULT_MAX_WATER_KM`, CLI `--max-water-km`, `0` disables). Beyond that, `water_source` is `null` rather than pointing a field team at a distant canal. 15 km is a team choice; change it in `c_agent/water.py` if the demo region needs another value.

## Messages

Templates in `messages.py` are the source of truth. Every message starts with `Simulasi` / `Simulation`. The `mpa` message is an SMS (≤160 characters, tested). A decline is written as a magnitude ("fell 0.06"), never "fell -0.06".

Optional LLM phrasing (`--llm`, `llm.py`) may only rephrase. It is rejected, with the template used instead, if it changes the audience set, drops the simulation label, introduces any number not present in the facts or template, exceeds SMS length, or the call fails. It runs only when a new dispatch is minted.

## Dedupe, cooldown, escalation

State file: `c_agent/state/incidents.json` (gitignored). Default cooldown: **6 hours**.

- One active incident per cell (cluster members share one incident).
- Same severity inside cooldown → reuse prior dispatch IDs (no new mint, no new log lines).
- Severity rise → mint new dispatch(es) and replace state.
- Cooldown expired at same severity → mint again.
- Severity fall / condition no longer met → clear state; no action this run.

## Coordinates and nulls

JSON uses `lat` / `lon`. GeoJSON from Role A stays `[lon, lat]` and is not rewritten here. Missing measurements remain `null`. Lookup uses the dispatch `target` (not `cell_id` alone), matching A's shifted-target example.
