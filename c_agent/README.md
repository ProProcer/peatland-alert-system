# Role C — Agent engineer

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder and `data/processed/dispatch.json`. Decisions use risk, features and cells; notifications remain simulated.

```bash
bash scripts/setup.sh c
source .venv/bin/activate
make mock
python -m c_agent.agent --mock --data-dir data/demo --output data/demo/dispatch.json
python -m contracts.validate --kind dispatch data/demo/dispatch.json
```

`agent.py --mock` validates the three inputs and replays `mock_output.json`; it is a fixed fixture, not the decision policy. It contains a CRITICAL dispatch with all five bilingual audience messages and `water_source: null`. The live entry point exits until implemented. Start the real policy in `agent.py`, record decisions in `decision_rules.md`, keep small inputs in `fixtures/`, and add behavior tests in `tests/`.

Build next:

1. Implement deterministic policy before message generation. Start with the examples in `decision_rules.md`; define how multiple horizons resolve into one cell's active incident.
2. Persist deduplication and cooldown state in the ignored `state/` directory. Escalate only when severity rises; cluster adjacent CRITICAL cells into one incident and target.
3. Use structured coordinates/numbers from validated inputs. An optional LLM can phrase messages and rationale; it cannot invent destinations, measurements or actions. Include Indonesian `id` and English `en` for every listed audience.
4. Decide whether to add documented OSM canal/river data or a handmade fixture. Keep `water_source: null` until data exists; do not fabricate routing or distance.
5. Write `dispatch.json` atomically; append simulated notifications to ignored `logs/`. Make `--data-dir` and `--output` work in the live adapter so E can run the pipeline anywhere.

Done when CRITICAL input creates a valid dispatch with all five messages, reruns do not duplicate active incidents, escalation is tested, and no real notification is sent.
