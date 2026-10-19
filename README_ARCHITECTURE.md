# Peat Fire Early-Warning Agent

### System architecture

Weather, satellite hotspots and peatland geography inform surface-hotspot risk estimates for **40 cells across Indonesian Kalimantan**, with **24, 48 and 72-hour** prediction horizons. A deterministic response policy turns those estimates into simulated actions for a shared command-center dashboard.

```mermaid
flowchart TB
    subgraph sources["DATA SOURCES"]
        direction LR
        weather["Open-Meteo<br/>Modeled weather and soil moisture"]
        fire["NASA FIRMS<br/>VIIRS surface hotspots"]
        geography["Peatland GeoJSON + geoBoundaries<br/>Peat coverage and province boundaries"]
        water["OpenStreetMap / Geofabrik<br/>Water geometry"]
    end

    subgraph pipeline["PROCESSING AND DECISIONS"]
        ingest["A · Data processing<br/>Spatial alignment, hourly features and history"]
        model["B · Risk inference<br/>24 / 48 / 72-hour scores and contributing factors"]
        policy["C · Response policy<br/>Prioritization, incident grouping and deduplication"]
        publish["E · Validate and publish<br/>Schema 1.0 checks and atomic snapshots"]

        ingest -->|"features.json"| model
        model -->|"risk.json"| policy
        ingest -->|"Features and cell geometry"| policy
        water -->|"Water-source lookup"| policy
        ingest -->|"features.json + cells.geojson"| publish
        model -->|"risk.json"| publish
        policy -->|"dispatch.json"| publish
    end

    subgraph experience["DASHBOARD AND RESPONSE"]
        dashboard["D · Command-center dashboard<br/>Risk map, horizon selection and response previews"]
        audiences["Manggala Agni · MPA · BPBD · BRGM · Leadership<br/>Simulated alerts and dispatch recommendations"]
        dashboard --> audiences
    end

    platform["IBM LinuxONE · s390x deployment target<br/>Docker / systemd configuration · Verified CSV transport"]
    scheduler["Live service<br/>Hourly refresh and manual refresh"]

    weather --> ingest
    fire --> ingest
    geography --> ingest
    scheduler --> ingest
    publish -->|"Complete, validated snapshot"| dashboard
    platform -.->|"Deployment configuration"| scheduler
    platform -.->|"Deployment configuration"| model

    classDef source fill:#eff6ff,stroke:#3b82f6,color:#172554;
    classDef process fill:#f0fdfa,stroke:#0f766e,color:#134e4a;
    classDef output fill:#f0fdf4,stroke:#16a34a,color:#14532d;
    classDef platform fill:#f5f3ff,stroke:#7c3aed,color:#4c1d95;
    class weather,fire,geography,water source;
    class ingest,model,policy,publish,scheduler process;
    class dashboard,audiences output;
    class platform platform;
```

Solid arrows show application data and control flow. Dashed arrows show deployment configuration; they do not establish a verified LinuxONE deployment.

### Data sources

| Source | Contribution | Reference |
| --- | --- | --- |
| Open-Meteo | Modeled hourly weather and soil moisture | [Forecast API](https://open-meteo.com/en/docs) · [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api) |
| NASA FIRMS | Historical and near-real-time VIIRS hotspot detections | [Downloads](https://firms.modaps.eosdis.nasa.gov/download/) · [API](https://firms.modaps.eosdis.nasa.gov/api/) |
| geoBoundaries | Indonesian province boundaries | [Indonesia ADM1](https://www.geoboundaries.org/api/current/gbOpen/IDN/ADM1/) |
| OpenStreetMap / Geofabrik | Water geometry for response recommendations | [Kalimantan extract](https://download.geofabrik.de/asia/indonesia/kalimantan.html) · [Attribution and licence](https://www.openstreetmap.org/copyright) |
| Local peatland GeoJSON | Peat polygons for cell selection and peat coverage | `data/raw/Indonesia_Peat_Lands.geojson`; original source URL and licence remain unverified |

### LinuxONE integration

The repository provides Docker configurations and a systemd service template for deployment. A verified gzip CSV transport workflow addresses the Parquet reader failure observed on the team's s390x VM, preserving source values and integrity checks while leaving the original datasets and model artifacts intact. End-to-end live operation and performance on LinuxONE still require verification.

### Operating boundaries

Weather and soil moisture are modeled values. FIRMS observes surface thermal anomalies; the solution estimates future surface-hotspot emergence. Model quality remains provisional. Alerts and dispatches are simulated, and no real SMS or operational dispatch is sent.

See the [main README](README.md), [live operations guide](e_platform/LIVE_OPERATIONS.md), [data handoff](a_data/REGIONAL_HANDOFF.md) and [frozen contracts](contracts/CONTRACTS.md) for implementation and validation details.
