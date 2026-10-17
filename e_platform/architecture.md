# Architecture and ownership

```mermaid
flowchart LR
    P[Peat GeoJSON] --> A[A: Data adapter]
    W[Open-Meteo modeled weather] --> A
    F[NASA FIRMS surface hotspots] --> A
    A --> FE[features.json / Parquet]
    A --> CE[cells.geojson]
    FE --> B[B: 24/48/72h model]
    B --> R[risk.json]
    R --> C[C: Deterministic policy]
    FE --> C
    CE --> C
    C --> DI[dispatch.json / simulated log]
    R --> D[D: Command-center UI]
    DI --> D
    CE --> D
    FE --> D
    E[E: LinuxONE integration / contracts / evidence] -. deploy and validate .-> A
    E -. deploy and validate .-> B
    E -. deploy and validate .-> C
    E -. serve .-> D
```

Current scaffold: validated synthetic mocks → isolated files → local handoff viewer. Existing B inference code is preserved. Live A/C adapters and D's final product are role deliverables. Optional LLM wording belongs after deterministic policy, with structured numbers and coordinates validated. No notification is sent to a real recipient.
