# Public RL datasets

| Dataset | Derived rows | Role | Boundary |
|---|---:|---|---|
| UCI Appliances Energy Prediction | 19,735 | Original energy regression benchmark | Not port or AGV production data |
| UCI Individual Household Electric Power, 5-minute | 409,887 | Large-scale energy algorithm benchmark | Not port or terminal production data |
| NOAA LA–Long Beach AIS, 2024-12-25 observed minutes | 710 | Measured port-traffic planning scenario | Service, backlog and wait are calibrated proxies |

Every derived CSV has an adjacent provenance JSON containing source URL, license or
government-material notice, transformations, source and derived hashes, and scope notice.

Rebuild commands:

```bash
.venv/bin/python scripts/fetch_public_rl_dataset.py
.venv/bin/python scripts/fetch_large_public_rl_dataset.py
.venv/bin/python scripts/fetch_noaa_port_ais_dataset.py
```

The NOAA source archive is large. The committed CSV contains only minute buckets with
published AIS messages inside the declared WGS84 bounding box; it does not synthesize
vessels or fill empty minutes.
