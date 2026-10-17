# Decision policy — implementation specification

Status: examples from the team playbook; **the live policy is not implemented**. Role C must agree on cooldown duration, horizon precedence and cluster adjacency before claiming these behaviors.

| Condition | Example action | Audiences |
| --- | --- | --- |
| CRITICAL | DISPATCH, highest priority | Manggala Agni, BPBD; CRITICAL demo includes messages for all five audiences |
| HIGH plus falling deep soil moisture | SMS_WARN and REWET, represented as policy allows under one active incident | MPA, BRGM |
| Adjacent CRITICAL cluster | BRIEF alongside a clustered incident | Leadership |
| Lower risk | MONITOR if the policy requires an action | Defined by C |

Resolve multiple horizons deterministically. Keep one active incident per cell; determine whether multiple action records belong to one incident without adding fields to schema 1.0 silently. Escalate on a level rise. Cluster targeting uses validated cell geometry; structured coordinates and numbers never come from an LLM.

The mock is a single fixed dispatch for the 48-hour CRITICAL fixture. It has no cooldown or clustering behavior. Water-source data is unavailable, so its field is null. All messages are simulated and explicitly labeled as such.
